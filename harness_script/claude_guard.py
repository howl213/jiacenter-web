#!/usr/bin/env python3
"""Claude Code PreToolUse(Bash) 훅. 내가 하는 위험한 명령을 실행 전에 막거나 사용자에게 묻는다.

- 차단(종료 코드 2): `git commit` 의 훅 건너뛰기(--no-verify, -n, core.hooksPath 바꿔치기),
                    입력(JSON, tool_input.command)을 읽지 못한 경우
- 확인(ask): 사람이 정하는 지점(CLAUDE.md 0절 표)에 해당하는 명령 —
             타 저장소로 쓰기, 강제 푸시·되돌리기 어려운 git 명령, 새 저장소 만들기, 병합, main 에 직접 커밋·푸시·병합,
             실제 DB 를 바꾸는 명령, 팀에 넘길 폴더 만들기, 분석할 수 없는 구조
파일 내용 검사는 하지 않는다 — 그건 harness_script/check_leaks.sh 가 git 훅과 CI 에서 한다.

분석 방식: 명령 문자열을 `shlex` 로 토큰으로 나눠 (연산자 `; && || |` 와 줄바꿈 단위로) 단순 명령마다
`git` 전역 옵션(-C, -c 등)을 걷어 낸 뒤 서브명령과 인자를 본다. 명령을 실제로 실행하지는 않는다.
`bash -c '...'`, `eval`, 셸로 들어가는 heredoc 의 속 문자열은 같은 방식으로 다시 본다.
막을 것과 물을 것이 섞이면 막는 쪽이 이긴다.

한계(완전한 셸 파서가 아니다): 변수 확장(`$X`), 따옴표 안의 명령 치환(`"$(...)"`), 별칭·함수,
파이썬 등이 만드는 하위 프로세스, 파일에 써 두었다가 나중에 돌리는 스크립트는 보지 못한다.
`shlex` 로 읽을 수 없거나(따옴표가 안 닫힘 등) 파이프로 셸에 넘기는 것은 보수적으로 ask 로 돌린다.
"""
import json
import os
import re
import shlex
import subprocess
import sys

OURS = 'howl213/jiacenter-web'   # jiacenter-web, jiacenter-web-portfolio 모두 이 접두사
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh'}
WRAPPERS = {'command', 'builtin', 'env', 'exec', 'nohup', 'time', 'sudo', 'nice'}
KEYWORDS = {'{', '!', 'if', 'then', 'else', 'elif', 'while', 'until', 'do'}   # 뒤에 명령이 바로 오는 셸 예약어
ASSIGN = re.compile(r'[A-Za-z_]\w*=')
MAX_DEPTH = 4
BASE = '.'   # 훅이 받은 cwd. -C·cd 로 바뀌었는지 가를 때 쓴다

GIT_GLOBAL_VALUE = {'--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env', '--exec-path'}
COMMIT_VALUE_SHORT = 'mFCctSu'   # 값을 받는 짧은 옵션. S, u 는 값이 붙어서만 온다
COMMIT_VALUE_NEXT = 'mFCct'      # 그중 값이 다음 토큰으로 올 수 있는 것
COMMIT_VALUE_LONG = {'--message', '--file', '--author', '--date', '--reedit-message', '--reuse-message', '--fixup',
                     '--squash', '--template', '--cleanup', '--pathspec-from-file', '--trailer'}
GH_API_FIELD = {'-f', '-F', '--field', '--raw-field', '--input'}   # 쓰면 gh 가 메서드를 POST 로 바꾼다
GH_API_VALUE = GH_API_FIELD | {'-X', '--method', '-H', '--header', '-q', '--jq', '-t', '--template',
                               '--hostname', '--cache', '-p', '--preview', '-R', '--repo'}

found = []   # (수준, 이유). 끝에서 한꺼번에 판정한다


def block(reason):
    found.append(('block', reason))


def ask(reason):
    found.append(('ask', reason))


def decide():
    blocks = list(dict.fromkeys(r for lv, r in found if lv == 'block'))
    if blocks:
        print(' / '.join(blocks), file=sys.stderr)
        sys.exit(2)
    asks = list(dict.fromkeys(r for lv, r in found if lv == 'ask'))
    if asks:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'ask',
            'permissionDecisionReason': ' / '.join(asks)}}, ensure_ascii=False))


def remote_url(cwd, remote='origin'):
    r = subprocess.run(['git', '-C', cwd or '.', 'remote', 'get-url', remote],
                       capture_output=True, text=True)
    return r.stdout.strip()


def repo_info(path):
    """(현재 브랜치, 읽었는가). git 저장소가 아니거나 경로가 없으면 읽지 못한 것이다."""
    if not path or not os.path.isdir(path):
        return '', False
    try:
        if subprocess.run(['git', '-C', path, 'rev-parse', '--git-dir'], capture_output=True, timeout=10).returncode:
            return '', False
        branch = subprocess.run(['git', '-C', path, 'symbolic-ref', '--short', 'HEAD'],
                                capture_output=True, text=True, timeout=10).stdout.strip()   # 첫 커밋 전에도 동작한다
    except (OSError, subprocess.TimeoutExpired):
        return '', False
    return branch, True


# ---- 문자열 → 단순 명령 토큰 -------------------------------------------------------------

HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1([^\n]*)\n(.*?)\n[ \t]*\2\b", re.S)
SHELL_TAIL = re.compile(r"(?:^|[\s;&|(`])(?:\S*/)?(?:bash|sh|zsh|dash|ksh)(?:\s[^;&|()`]*)?$")


def split_heredocs(text):
    """heredoc 본문을 뺀 글과, 셸이 실행하는 본문들을 돌려준다.

    파일에 쓸 글이나 스크립트 원문은 실행되는 명령이 아니므로 뺀다 — 안 그러면 문서에 `git commit --no-verify` 라고
    쓰기만 해도 막힌다(2026-11-09 실제 오탐). 반대로 `bash <<EOF` 처럼 셸이 받으면 본문이 곧 명령이라 따로 돌려준다.
    heredoc 를 연 줄의 나머지(`<<EOF && git commit ...`)는 남겨 둔다.
    """
    bodies = []

    def sub(m):
        if SHELL_TAIL.search(text[text.rfind('\n', 0, m.start()) + 1:m.start()]):
            bodies.append(m.group(4))
        return '<<HEREDOC' + m.group(3)
    return HEREDOC.sub(sub, text), bodies


def _newlines_to_semicolons(text):
    """따옴표 밖의 줄바꿈은 명령 구분이다. 줄 끝 `\\` 는 이어 쓰기라 뺀다."""
    out, quote, esc = [], None, False
    for ch in text:
        if esc:
            esc = False
            if ch == '\n' and quote is None:
                out.pop()
                continue
        elif ch == '\\' and quote != "'":
            esc = True
        elif quote:
            if ch == quote:
                quote = None
        elif ch in '\'"':
            quote = ch
        elif ch == '\n':
            ch = ' ; '
        out.append(ch)
    return ''.join(out)


def segments(text):
    """연산자로 나눈 단순 명령들을 [(토큰 목록, 파이프로 이어받았는가)] 로 돌려준다. 못 읽으면 None."""
    lex = shlex.shlex(_newlines_to_semicolons(text), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ''   # '#' 뒤를 버리지 않는다(더 많이 보는 쪽이 안전하다)
    try:
        tokens = list(lex)
    except ValueError:
        return None
    segs = [([], False)]
    for t in tokens:
        if t and set(t) <= set(';&|()'):
            segs.append(([], t in ('|', '|&')))
        elif t.strip('`'):
            segs[-1][0].append(t.strip('`'))   # `git ...` 처럼 백틱으로 감싼 명령의 앞뒤 백틱
    return [(toks, p) for toks, p in segs if toks]


def strip_wrappers(toks):
    """앞의 환경변수 대입·sudo/env 같은 껍데기·셸 예약어를 걷어 (대입 목록, 나머지 토큰) 을 돌려준다."""
    env, toks = [], list(toks)
    while toks:
        if ASSIGN.match(toks[0]):
            env.append(toks.pop(0))
        elif toks[0] in KEYWORDS:
            toks.pop(0)
        elif os.path.basename(toks[0]) in WRAPPERS:
            toks.pop(0)
            while toks and toks[0].startswith('-'):
                toks.pop(0)
        else:
            break
    return env, toks


def _join(base, path):
    if base is None or '$' in path or '`' in path:
        return None   # 변수가 들어 있어 어느 폴더인지 알 수 없다
    return os.path.normpath(os.path.join(base, os.path.expanduser(path)))


def _short(arg):
    """`-fu` 같은 짧은 옵션 묶음의 글자들. 긴 옵션이나 값이면 빈 문자열."""
    return arg[1:] if arg.startswith('-') and not arg.startswith('--') else ''


# ---- git ---------------------------------------------------------------------------------

def commit_skips_hook(rest):
    """`git commit` 인자에서 훅을 건너뛰는 옵션(--no-verify, -n)을 실제 옵션 자리에서만 찾는다."""
    i = 0
    while i < len(rest):
        a, i = rest[i], i + 1
        if a == '--':
            break
        if a.startswith('--'):
            name = a.split('=')[0]
            if name == '--no-verify' or (len(name) > 5 and '--no-verify'.startswith(name)):   # git 은 줄임말도 받는다
                return True
            if '=' not in a and a in COMMIT_VALUE_LONG:
                i += 1
            continue
        for k, ch in enumerate(_short(a), 1):
            if ch == 'n':
                return True
            if ch in COMMIT_VALUE_SHORT:
                if k == len(a) - 1 and ch in COMMIT_VALUE_NEXT:
                    i += 1   # 값이 다음 토큰이라 그 토큰은 옵션이 아니다 (-m -n 의 -n)
                break
    return False


def git_check(args, cwd):
    repo, confs, odd, i = cwd, [], False, 0
    while i < len(args) and args[i].startswith('-'):
        a = args[i]
        name, eq, val = a.partition('=')
        if a == '-C' and i + 1 < len(args):
            repo, i = _join(repo, args[i + 1]), i + 2
        elif a == '-c' and i + 1 < len(args):
            confs.append(args[i + 1])
            i += 2
        elif name in GIT_GLOBAL_VALUE:
            odd = odd or name in ('--git-dir', '--work-tree')   # 저장소를 직접 가리킨다 → 브랜치를 읽을 수 없다
            if name == '--config-env':
                confs.append(val if eq else (args[i + 1] if i + 1 < len(args) else ''))
            i += 1 if eq else 2
        else:
            i += 1
    sub, rest = (args[i], args[i + 1:]) if i < len(args) else (None, [])

    if any('core.hookspath' in c.lower() for c in confs):
        block('git 의 core.hooksPath 를 바꿔 훅(누출 검사)을 건너뛰려 합니다. 검사에 걸렸다면 내용을 고치세요. '
              '검사 자체를 건너뛰어야 하면 사용자가 직접 실행합니다.')
    if sub == 'config' and any(a.lower() == 'core.hookspath' for a in rest):
        pos = [a for a in rest if not a.startswith('-')]
        writes = len(pos) > 1 or any(a.startswith('--unset') or a == '--replace-all' for a in rest)
        if writes and '.githooks' not in rest:   # `git config core.hooksPath .githooks` 는 CLAUDE.md 가 시키는 설정이다
            block('core.hooksPath 를 .githooks 가 아닌 곳으로 바꾸거나 지우면 누출 검사 훅이 꺼집니다. 사용자가 직접 실행합니다.')
    if sub == 'commit' and commit_skips_hook(rest):
        block('git commit --no-verify(-n) 는 누출 검사를 건너뜁니다. 검사에 걸렸다면 내용을 고치세요. '
              '검사 자체를 건너뛰어야 하면 사용자가 직접 실행합니다.')

    pos = [a for a in rest if not a.startswith('-')]
    if sub == 'push':
        short = ''.join(_short(a) for a in rest)
        if any(a in ('--force', '--force-if-includes') or a.startswith('--force-with-lease') for a in rest) \
                or 'f' in short or any(p.startswith('+') for p in pos):
            ask('강제 푸시는 원격의 이력을 덮어씁니다. 진행할까요?')
        if '--delete' in rest or 'd' in short or any(p.startswith(':') for p in pos):
            ask('작업을 지우거나 이력을 다시 쓰는 git 명령입니다. 진행할까요?')
        remote = pos[0] if pos else 'origin'
        url = remote_url(repo, remote) if repo and not odd else ''
        url = url or remote
        if OURS not in url:
            ask(f'우리 저장소가 아닌 곳으로 푸시합니다 ({url}). 올리는 파일에 개인정보·답안지·내부 문서가 없는지 확인했나요?')
    elif (sub == 'reset' and '--hard' in rest) or sub in ('filter-repo', 'filter-branch', 'rebase') \
            or (sub == 'clean' and ('--force' in rest or 'f' in ''.join(_short(a) for a in rest))) \
            or (sub == 'branch' and 'D' in ''.join(_short(a) for a in rest)):
        # 되돌리기 어려운 git 명령: 작업을 지우거나 이력을 다시 쓴다
        ask('작업을 지우거나 이력을 다시 쓰는 git 명령입니다. 진행할까요?')

    # main 보호 규칙을 걸 수 없는 플랜(GitHub Free 비공개)이라 훅이 대신 묻는다
    if sub in ('commit', 'merge', 'push'):
        branch, ok = repo_info(None if odd else repo)
        explicit = odd or repo != BASE
        pushes_main = sub == 'push' and any(p.lstrip('+').split(':')[-1] in ('main', 'refs/heads/main') for p in pos[1:])
        if not ok and explicit:
            ask('git -C·cd 로 가리킨 폴더의 브랜치를 읽지 못해 main 인지 확인할 수 없습니다. 진행할까요?')
        elif branch == 'main' or pushes_main:
            ask('main 에 직접 커밋·병합·푸시하려 합니다. 이 프로젝트는 브랜치 → PR 로 갑니다. 진행할까요?')


# ---- gh ----------------------------------------------------------------------------------

def gh_api_check(args):
    method, implicit, endpoint, j = None, False, None, 0
    while j < len(args):
        a, j = args[j], j + 1
        if a in ('-X', '--method'):
            method, j = (args[j] if j < len(args) else ''), j + 1
        elif a.startswith('--method='):
            method = a[9:]
        elif a.startswith('-X') and not a.startswith('--'):
            method = a[2:]
        elif a in GH_API_FIELD:
            implicit, j = True, j + 1
        elif a.startswith('--') and a.split('=')[0] in GH_API_FIELD:
            implicit = True
        elif a[:2] in ('-f', '-F') and len(a) > 2 and not a.startswith('--'):
            implicit = True
        elif a in GH_API_VALUE:
            j += 1
        elif not a.startswith('-') and endpoint is None:
            endpoint = a
    if method is not None and not re.fullmatch(r'[A-Za-z]+', method):
        ask('gh api 의 메서드를 읽지 못했습니다. 진행할까요?')
        return
    # 메서드를 직접 적었으면 그 값, 없으면 필드·본문 옵션이 있을 때 POST (gh 의 규칙)
    if (method.upper() if method else ('POST' if implicit else 'GET')) not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    m = re.search(r'(?:^|/)repos/([^/\s?#]+/[^/\s?#]+)', endpoint or '')
    if m and not m.group(1).startswith(OURS):
        ask(f'다른 저장소({m.group(1)})에 쓰는 API 호출입니다. 진행할까요?')
    elif '$' in (endpoint or ''):
        ask('gh api 가 쓰는 대상을 읽지 못했습니다. 진행할까요?')


def gh_check(args):
    repos, pos, i = [], [], 0
    while i < len(args):
        a, i = args[i], i + 1
        if a in ('-R', '--repo') and i < len(args):
            repos.append(args[i])
            i += 1
        elif a.startswith('--repo='):
            repos.append(a[7:])
        elif a.startswith('-R') and not a.startswith('--') and len(a) > 2:
            repos.append(a[2:])
        elif not a.startswith('-'):
            pos.append(a)
    for r in repos:
        if not r.startswith(OURS):
            ask(f'다른 저장소({r})에 쓰는 gh 명령입니다. 진행할까요?')
    if pos[:2] == ['pr', 'merge']:
        ask('병합은 사람이 정합니다. CI 결과를 확인했나요? 진행할까요?')
    if pos[:1] == ['repo'] and pos[1:2] and pos[1] in ('create', 'delete', 'edit'):
        ask('저장소를 만들거나 바꾸거나 지우는 명령입니다. 공개 범위와 대상 이름을 확인했나요?')
    if pos[:1] == ['api'] and 'api' in args:
        gh_api_check(args[args.index('api') + 1:])


# ---- 한 줄 전체 --------------------------------------------------------------------------

def plain_checks(cmd):
    """토큰으로 나누지 않고 글자로 보는 규칙들(git·gh 가 아닌 것)."""
    if re.search(r'export_for_team\.py', cmd):
        ask('팀에 넘길 폴더를 만듭니다. 폴더를 만드는 것까지이고 올리는 것은 따로 확인합니다. 진행할까요?')
    if re.search(r'manage\.py\s+migrate\b', cmd) and '--settings' not in cmd:
        ask('실제 db.sqlite3 에 마이그레이션을 적용합니다. 진행할까요?')
    # 2026-11-09 사고: 시드 명령을 로컬 DB 에 그대로 돌려 데이터가 섞였다. DB 를 바꾸는 명령은 먼저 묻는다.
    # Docker 안에서 돌리는 것(docker compose exec/run)은 로컬 DB 가 아니므로 통과시킨다.
    if (re.search(r'manage\.py\s+(seed_dummy|flush|sqlflush|loaddata|createsuperuser|changepassword|dbshell)\b', cmd)
            and not re.search(r'\bdocker\s+(compose\s+)?(exec|run)\b', cmd)):
        ask('로컬 db.sqlite3 의 데이터를 바꾸는 관리 명령입니다. 실습용 시드는 docker compose 안에서 돌리세요. 그래도 진행할까요?')
    if re.search(r'\bsqlite3\b[^|;&]*db\.sqlite3', cmd):
        ask('db.sqlite3 를 직접 엽니다. 아동 이름·연락처(모의 값이라도)가 출력에 남을 수 있습니다. 진행할까요?')


def segment(toks, piped, cwd, depth):
    """단순 명령 하나를 점검하고, 뒤따르는 명령이 쓸 작업 폴더(cd 를 반영)를 돌려준다."""
    env, toks = strip_wrappers(toks)
    if any('hookspath' in e.lower() for e in env):
        block('환경변수로 git 의 core.hooksPath 를 바꿔 훅(누출 검사)을 건너뛰려 합니다. 사용자가 직접 실행합니다.')
    if not toks:
        return cwd
    name, args = os.path.basename(toks[0]), toks[1:]
    if name == 'cd':
        return _join(cwd, args[0]) if args and args[0] != '-' else cwd
    if name in SHELLS:
        script = None
        for k, a in enumerate(args):
            if a == '<<<' and k + 1 < len(args):
                script = args[k + 1]
            elif a.startswith('-') and not a.startswith('--') and 'c' in a[1:] and k + 1 < len(args):
                script = args[k + 1]
            if script is not None:
                break
        if script is not None:
            analyze(script, cwd, depth + 1)
        elif piped and all(a.startswith('-') for a in args):
            ask('파이프로 셸에 넘기는 명령은 분석하지 못합니다. 진행할까요?')
    elif name == 'eval':
        analyze(' '.join(args), cwd, depth + 1)
    elif name == 'git':
        git_check(args, cwd)
    elif name == 'gh':
        gh_check(args)
    return cwd


def analyze(text, cwd, depth=0):
    if depth > MAX_DEPTH:
        ask('명령이 여러 겹으로 감싸여 있어 분석하지 못했습니다. 진행할까요?')
        return
    text, bodies = split_heredocs(text)
    for body in bodies:
        analyze(body, cwd, depth + 1)
    plain_checks(text)
    segs = segments(text)
    if segs is None:
        ask('명령을 해석하지 못했습니다(따옴표가 닫히지 않음 등). 무엇을 실행하는지 확인하고 진행할까요?')
        return
    for toks, piped in segs:
        cwd = segment(toks, piped, cwd, depth)


def main():
    global BASE
    try:
        data = json.load(sys.stdin)
        cmd = data['tool_input']['command']
        if not isinstance(cmd, str):
            raise TypeError('command 가 글자가 아님')
    except (ValueError, KeyError, TypeError) as e:
        # 위험한 명령이 검사 없이 지나가지 않도록 입력을 읽지 못하면 막는다
        print(f'claude_guard: 훅 입력(JSON, tool_input.command)을 읽지 못해 막습니다 ({type(e).__name__}).', file=sys.stderr)
        sys.exit(2)
    BASE = os.path.normpath(data['cwd']) if isinstance(data.get('cwd'), str) and data['cwd'] else os.getcwd()
    try:
        analyze(cmd, BASE)
    except Exception as e:   # 점검 코드 자체의 버그. 조용히 통과시키지 않고 사람에게 묻는다
        ask(f'명령 점검 중 오류가 났습니다 ({type(e).__name__}: {e}). 진행할까요?')
    decide()


if __name__ == '__main__':
    main()
