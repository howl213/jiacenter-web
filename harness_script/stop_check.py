#!/usr/bin/env python3
"""Stop 훅. 끝내려 할 때 아래 중 하나라도 걸리면 한 번 막고, 이유를 Claude 에게 돌려준다(Claude Code 가 그 이유를 받아 이어서 일한다).

  1) 이번 턴에 src/ 또는 하네스(harness_script/, .claude/settings.json)를 고쳤고, 답변이 "N개 통과"류의 통과를 주장하는데
     그 범위의 검증 성공 증거가 없다(실행 기록 없음·실패·결과 불명). 테스트를 안 돌린 것 자체는 막지 않는다 — 근거 없는 주장만 막는다.
     증거는 세션 기록의 도구 호출·결과 본문·종료 상태를 함께 본다. 다른 범위의 테스트는 증거가 아니다.
  2) 방금 한 마지막 답변에 "완벽하다/문제없다/안전하다" 같은 단정이 있는데 "확인하지 못한 것"이 없다
  3) 점검 자체를 못 했다(입력 JSON 이 깨졌다, 세션 기록을 못 읽었다, git status 가 실패했다, 점검 중 예기치 않은 오류)
     — 이때는 "통과"로 두지 않고 막되, 답에 "점검하지 못했다"고 알리게 한다. 검증했다고 쓰게 두지 않기 위해서다.

이 훅은 manage.py check 같은 검사 명령을 직접 실행하지 않는다(#19) — 검사는 Claude 가 승인받아 돌리고 훅은 그 기록만 읽는다.
막을 것은 없고 결과 불명 안내만 있으면 막지 않고 systemMessage 로 사용자에게만 알린다(모델을 다시 부르지 않는다).

되풀이 방지: stop_hook_active 가 켜져 있으면(이미 이 훅 때문에 이어서 일하는 중) 같은 점검을 다시 하고, 해결됐으면 말없이 통과한다.
문제가 남았거나 새 문제가 나와도 두 번째로 막지 않는다 — 대신 사용자에게 systemMessage 로만
해결되지 않은 것을 알린다(additionalContext 는 모델을 다시 불러 훅이 반복되므로 쓰지 않는다. 이전 사유를 저장하지 않으므로 같은 문제인지 새 문제인지는 구분하지 않는다). Claude Code 쪽에도 연속 차단 상한이 있다.
입력 JSON 을 읽지 못하면 stop_hook_active 를 알 수 없으므로 이 정책 밖이다 — 기존처럼 막는다(fail-closed).
"사용자가 직접 확인해야 하는가"는 스크립트가 알 수 없다 — 그 판단은 CLAUDE.md 2절 3번 줄이 Claude 에게 맡긴다.
2)번과 1)의 통과 주장 탐지는 문장 모양만 보는 거친 검사라 틀릴 수 있다. 전체 테스트는 여기서 돌리지 않는다(harness_script/verify.sh 와 CI 가 한다).

이 훅이 쓰는 입력 필드(확인한 것만): 훅 입력의 transcript_path · stop_hook_active · last_assistant_message,
세션 기록(JSONL)의 assistant tool_use(id, name, input), user tool_result(tool_use_id, is_error, content).
그 밖의 필드는 확인하지 않았고 쓰지 않는다.

테스트 성공 여부의 근거와 한계: is_error 하나로 성공을 판정하지 않는다. 성공은 결과 본문의 `Ran N tests`(N≥1)와 `OK` 같은 양의 증거가 있고,
명령이 파이프·`;`·`||` 로 결과를 가리지 않으며, is_error 가 false 로 명시됐을 때만 인정한다. 본문은 끝 4KB 만 본다.
4KB 를 넘어 앞이 잘린 결과는 성공으로 확정하지 않는다(보이는 끝에 실패 표지가 있으면 실패, 없으면 불명).
정적·구조 검사(check_leaks.sh 등)와 Django 검사(manage.py check 등), verify.sh 는 성공 기준을 아직 정하지 않았으므로 성공으로 인정하지 않고 불명으로 둔다.
세션 기록 파일이 아예 없을 때만(경로 없음·파일 없음) 기록으로 볼 것이 없어 이 검사를 건너뛴다.
"""
import collections
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_guard import SHELLS, segments, split_heredocs, strip_wrappers  # noqa: E402  (같은 폴더의 모듈)

CLAIM = re.compile(r'완벽|문제\s*없|안전합니다|안전해요|안전하다|허점이?\s*없|걱정\s*없')
NEGATION = re.compile(r'않|아니|못\s|금지|말하지|쓰지|뜻이|라고\s*(말|쓰|적)')
HEDGE = re.compile(r'확인하지\s*못|확인\s*못|미확인|검증하지\s*못|보지\s*못|못\s*봤|안\s*한\s*것')
EDIT_TOOLS = {'Edit', 'Write', 'NotebookEdit'}
TAIL = 4096   # 결과 본문은 끝 4KB 만 판정한다. 보관은 TAIL+1 글자 — TAIL 을 넘으면 잘렸다는 표시로 쓴다(shortcut: 잘린 앞쪽의 실패 표지는 못 본다, 그래서 잘린 결과는 성공으로 안 친다)

# --- 검증 명령 분류 -------------------------------------------------------------------------------------------------
PYTHON = re.compile(r'python[\d.]*')
STATIC_SCRIPTS = {'check_leaks.sh', 'check_track.py', 'check_manifest.py'}
SCOPE_PATH = re.compile(r'^(?:\./)?(harness_script|src)(?:$|[/.:])')
VALUE_FLAGS = {'-p', '-t', '-k', '-m', '-c', '--pattern', '--top-level-directory', '--maxfail', '--rootdir'}   # 값을 따로 받는 옵션
REDIRECT = re.compile(r'\d*>&\d+|&>>?\s*\S+|\d*>>?\s*\S+')   # 2>&1 같은 리다이렉션의 & 를 연산자로 오인하지 않으려고 먼저 걷어 낸다
UNRELIABLE = re.compile(r';|\|\||\||(?<!&)&(?!&)')            # &&(앞이 성공해야 다음이 돈다)만 믿는다. 파이프·;·||·& 는 종료 코드가 테스트의 것이 아닐 수 있다
Cmd = collections.namedtuple('Cmd', 'kind scopes reliable')   # kind: test|verify|static|django|mixed|None


def is_test_tokens(toks):
    """단순 명령 하나가 테스트를 실제로 돌리는 것인가. `echo pytest` 처럼 글자만 든 것은 아니다."""
    name, args = os.path.basename(toks[0]), toks[1:]
    if PYTHON.fullmatch(name):
        for k, a in enumerate(args):
            if os.path.basename(a) == 'manage.py':
                return args[k + 1:k + 2] == ['test']
            if a == '-m':
                return args[k + 1:k + 2] in (['unittest'], ['pytest'])
        return False
    if name == 'manage.py':
        return args[:1] == ['test']
    if name in ('pytest', 'py.test'):
        return True
    if name in SHELLS:
        return bool(args) and os.path.basename(args[0]) == 'verify.sh'
    return name == 'verify.sh'


def test_scopes(toks):
    """테스트 명령 하나가 덮는 범위({'src','harness'}). 대상을 알 수 없으면 빈 집합."""
    name, args = os.path.basename(toks[0]), toks[1:]
    if name == 'manage.py' or any(os.path.basename(a) == 'manage.py' for a in args):
        return frozenset(('src',))
    if '-m' in args:   # python -m unittest|pytest 뒤의 인자만 본다
        args = args[args.index('-m') + 2:]
    scopes, i = set(), 0
    while i < len(args):
        a = args[i]
        if a in ('-s', '--start-directory'):
            target, i = (args[i + 1] if i + 1 < len(args) else ''), i + 2
        elif a in VALUE_FLAGS:
            i += 2
            continue
        elif a.startswith('-s') and not a.startswith('--') and len(a) > 2:
            target, i = a[2:], i + 1
        elif a.startswith('-'):
            i += 1
            continue
        else:
            target, i = a, i + 1
        m = SCOPE_PATH.match(target)
        if m:
            scopes.add('src' if m.group(1) == 'src' else 'harness')
    return frozenset(scopes)


def segment_kind(toks):
    """단순 명령 하나의 검증 유형 (유형, 범위). 검증 명령이 아니면 None."""
    name, args = os.path.basename(toks[0]), toks[1:]
    if is_test_tokens(toks):
        if name in SHELLS or name == 'verify.sh':
            return 'verify', frozenset(('src', 'harness'))
        return 'test', test_scopes(toks)
    first = next((a for a in args if not a.startswith('-')), '')
    runner = name in SHELLS or bool(PYTHON.fullmatch(name))
    if name in STATIC_SCRIPTS or (runner and os.path.basename(first) in STATIC_SCRIPTS):
        return 'static', frozenset()
    rest = None
    if name == 'manage.py':
        rest = args
    elif PYTHON.fullmatch(name) and os.path.basename(first) == 'manage.py':
        rest = args[args.index(first) + 1:]
    if rest and rest[0] in ('check', 'makemigrations'):
        return 'django', frozenset()
    return None


def classify_command(command):
    """Bash 명령 한 줄을 Cmd(유형, 대상 범위, 신뢰 가능 여부) 로 분류한다. 검증 명령이 아니면 유형이 None.

    신뢰 가능: 파이프·`;`·`||`·`&` 없이 단일 명령이거나 `&&` 로만 이은 것. 아니면 종료 코드가 검증 명령의 것이 아닐 수 있어 성공을 인정하지 않는다.
    서로 다른 유형을 한 줄에 이으면 'mixed' (성공으로 인정하지 않는다).
    """
    text = split_heredocs(str(command))[0]
    found = []
    for toks, _ in (segments(text) or []):
        toks = strip_wrappers(toks)[1]
        hit = segment_kind(toks) if toks else None
        if hit:
            found.append(hit)
    if not found:
        return Cmd(None, frozenset(), True)
    kinds = {k for k, _ in found}
    scopes = frozenset().union(*[s for _, s in found])
    return Cmd(kinds.pop() if len(kinds) == 1 else 'mixed', scopes, not UNRELIABLE.search(REDIRECT.sub(' ', text)))


# --- 결과 본문 판정 -------------------------------------------------------------------------------------------------
RAN = re.compile(r'^Ran (\d+) tests? in ', re.M)
OK_LINE = re.compile(r'^OK(?: \(.*\))?\s*$', re.M)
FAIL_MARK = re.compile(r'^FAILED\b|^(?:FAIL|ERROR): \S+ \(|Traceback \(most recent call last\)|^Exit code [1-9]', re.M)
VERIFY_FAIL = re.compile(r'^실패  |실패한 항목이 있다', re.M)


def parse_result(kind, body, status, reliable=True):
    """검증 명령의 결과를 'success'|'failure'|'unclear' 로 판정한다.

    status 는 turn_tool_uses 의 'ok'|'error'|None. 성공은 양의 증거(Ran N≥1 + OK, 실패 표지 없음, is_error 거짓, 신뢰할 수 있는 명령)가 전부 있을 때만이다.
    실패 표지는 성공 표지보다 우선한다. body 가 TAIL 보다 길면 앞이 잘린 것이라 성공으로 확정하지 않는다(끝에 실패 표지가 있으면 실패, 없으면 불명). 정적·Django 검사·mixed 는 성공 기준이 없어 항상 불명이고, verify.sh 는 단계별 어댑터가 없어 실패만 가려낸다.
    """
    if kind not in ('test', 'verify'):
        return 'unclear'
    text = body[-TAIL:] if isinstance(body, str) else ''
    truncated = isinstance(body, str) and len(body) > TAIL
    if FAIL_MARK.search(text) or (kind == 'verify' and VERIFY_FAIL.search(text)):
        return 'failure'
    if status == 'error':
        return 'failure' if reliable else 'unclear'   # 파이프 뒤의 종료 코드는 다른 명령의 것일 수 있다
    if kind == 'verify' or status != 'ok' or not reliable or truncated:
        return 'unclear'
    ran = [int(n) for n in RAN.findall(text)]
    if not ran or min(ran) < 1 or len(OK_LINE.findall(text)) < len(ran):   # Ran 0 tests·요약 없음·OK 가 모자란 요약은 성공이 아니다
        return 'unclear'
    return 'success'


# --- 통과 주장 탐지 (D2 설계) ---------------------------------------------------------------------------------------
FENCE = re.compile(r'```.*?```', re.S)
INLINE_CODE = re.compile(r'`[^`\n]*`')
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」')
BLOCKQUOTE = re.compile(r'^\s*>.*$', re.M)
PASS_PATTERNS = (
    re.compile(r'\d+\s*[개건]\s*(?:가|이|은|는|도|를)?\s*통과(?!시)'),                                            # 숫자 + 개/건 + 통과
    re.compile(r'(?:시험|테스트|검사|점검)[^.\n]{0,15}통과(?:했|됐|되었|하였|합니다|해요|함(?![가-힣]))'),        # 시험·검사 문맥의 통과했다
    re.compile(r'모두\s*통과(?!시)'),                                                                            # 모두 통과
)
NOT_A_CLAIM = re.compile(r'\?|까요|인가요|면\s|다면|려면|경우|예정|예상|할\s*것|될\s*것|추정|권장|바랍니다|하세요|해야|필요|사용자가|팀원|말씀하신|알려\s*주신|\bCI\b|훅|pass-through')
ZERO_FAIL = re.compile(r'실패\s*0\s*[건개]|0\s*[건개]\s*실패')
SENTENCES = re.compile(r'(?<=[.!?다요])\s+|\n')


def pass_claims(text):
    """답변에서 검증 통과 주장을 문장 단위로 찾아 [(유형, 문장 앞 60자)] 로 돌려준다. 유형은 'test'(기본)|'check'(검사·점검 문맥).

    코드 블록·백틱·큰따옴표 인용·인용 줄은 지우고 본다. 부정·질문·조건·예정·권고·결과 중계·미확인 문장은 주장이 아니다.
    같은 문장 안에 실패도 함께 보고하면 부분 결과 보고로 보고 면제한다. 면제는 문장 단위다 — "3개 실패. 47개 통과." 처럼 나뉘면 뒤 문장은 주장이다.
    답변 전체 HEDGE 면제는 쓰지 않는다. "수정 완료" 같은 작업 완료 표현은 패턴에 없다.
    """
    if not isinstance(text, str) or not text:
        return []
    clean = BLOCKQUOTE.sub('', INLINE_CODE.sub('', QUOTED.sub('', FENCE.sub('', text))))
    claims = []
    for s in (x.strip() for x in SENTENCES.split(clean)):
        if not s or not any(p.search(s) for p in PASS_PATTERNS):
            continue
        if NEGATION.search(s) or HEDGE.search(s) or NOT_A_CLAIM.search(s):
            continue
        if re.search(r'실패|FAIL', s) and not ZERO_FAIL.search(s):
            continue
        check_only = re.search(r'검사|점검', s) and not re.search(r'시험|테스트', s)
        claims.append(('check' if check_only else 'test', s[:60]))
    return claims


# --- 세션 기록 ------------------------------------------------------------------------------------------------------
def entries(transcript_path):
    for line in Path(transcript_path).read_text(encoding='utf-8').splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def last_assistant_text(transcript_path):
    """세션 기록(JSONL)에서 마지막 assistant 글을 꺼낸다. 형식이 다르면 빈 문자열."""
    text = ''
    for entry in entries(transcript_path):
        if entry.get('type') != 'assistant':
            continue
        content = (entry.get('message') or {}).get('content')
        if isinstance(content, list):
            parts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
            if parts:
                text = '\n'.join(parts)
    return text


def result_text(content):
    """tool_result 의 content 는 문자열이거나 {'type':'text','text':…} 블록 목록이다. 글자만 이어 붙인다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b['text'] if isinstance(b, dict) and isinstance(b.get('text'), str) else (b if isinstance(b, str) else '')
                         for b in content)
    return ''


def is_stop_feedback(entry, content):
    return entry.get('isMeta') is True and isinstance(content, str) and content.startswith('Stop hook feedback:')


def turn_tool_uses(transcript_path):
    """마지막 사용자 입력 이후에 부른 도구들을 (이름, 입력, 상태, 결과 본문) 순서대로 돌려준다.

    상태는 짝이 되는 tool_result 의 is_error 가 true 면 'error', false 면 'ok', 결과가 없거나 is_error 가 명시되지 않았으면 None.
    본문은 끝 TAIL+1 글자만 보관한다(긴 출력으로 메모리를 쓰지 않으려고, 하나 더 두는 것은 잘림 표시).
    """
    uses, by_id = [], {}
    for entry in entries(transcript_path):
        content = (entry.get('message') or {}).get('content')
        if entry.get('type') == 'user':
            # 도구 결과(tool_result)만 든 항목은 사용자 입력이 아니다. Stop 훅이 막았을 때 Claude Code 가 넣는
            # "Stop hook feedback:" 항목(isMeta, 실제 세션 기록으로 확인)도 사용자 입력이 아니므로 기록을 지우지 않는다.
            if is_stop_feedback(entry, content):
                continue
            if isinstance(content, str) or (isinstance(content, list) and any(
                    isinstance(b, dict) and b.get('type') == 'text' for b in content)):
                uses, by_id = [], {}
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') in by_id:
                        use = uses[by_id[b['tool_use_id']]]
                        use[3] = result_text(b.get('content'))[-(TAIL + 1):]
                        if isinstance(b.get('is_error'), bool):
                            use[2] = 'error' if b['is_error'] else 'ok'
        elif entry.get('type') == 'assistant' and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    if b.get('id'):
                        by_id[b['id']] = len(uses)
                    uses.append([b.get('name'), b.get('input') or {}, None, ''])
    return [tuple(u) for u in uses]


# --- 증거 판정 ------------------------------------------------------------------------------------------------------
SCOPE_LABEL = {'src': '프로젝트(src/)', 'harness': '하네스'}
WHY = {'none': '그 범위의 검증 실행 기록이 없다',
       'unclear': '검증 결과를 성공으로 확인하지 못했다(결과·범위 불명이거나 신뢰할 수 없는 명령 형태)',
       'failure': '마지막 검증이 실패했다'}


def edit_scopes(uses, root):
    """이번 턴의 편집을 범위별로 나눠 {범위: (마지막 편집 위치, root 기준 경로)} 로 돌려준다.

    src/ 는 'src', harness_script/ 와 .claude/settings.json 은 'harness'. 문서 등 나머지 경로는 어느 범위도 아니다.
    Bash 로 한 수정은 보이지 않는다(기존 한계).
    """
    found = {}
    for i, (name, inp) in enumerate((u[0], u[1]) for u in uses):
        path = inp.get('file_path') or inp.get('notebook_path') or ''
        if name in EDIT_TOOLS and isinstance(path, str) and path:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
            if rel.startswith('src/'):
                found['src'] = (i, rel)
            elif rel.startswith('harness_script/') or rel == '.claude/settings.json':
                found['harness'] = (i, rel)
    return found


def verification_runs(uses):
    """이번 턴의 검증 명령 실행들을 [(위치, Cmd, 결과)] 로 돌려준다."""
    runs = []
    for i, (name, inp, status, body) in enumerate(uses):
        cmd = classify_command(inp.get('command', '')) if name == 'Bash' else None
        if cmd and cmd.kind:
            runs.append((i, cmd, parse_result(cmd.kind, body, status, cmd.reliable)))
    return runs


def evidence_state(runs, claim_kind, after, scope=None):
    """after 번 뒤에 돌린 관련 검증의 마지막 결과: 'success'|'failure'|'unclear'|'none'(관련 검증 기록 없음).

    'test' 주장은 그 범위(scope)를 덮는 테스트·verify 만 본다. 대상 범위를 알 수 없는 테스트는 범위를 단정하지 않고 불명이다.
    'check' 주장은 정적·Django 검사·verify 를 보는데, 성공 기준이 없어 실패가 아니면 불명이다.
    """
    later = [r for r in runs if r[0] > after]
    if claim_kind == 'check':
        hits = [r for r in later if r[1].kind in ('static', 'django', 'verify', 'mixed')]
        return 'none' if not hits else ('failure' if hits[-1][2] == 'failure' else 'unclear')
    hits = [r for r in later if r[1].kind in ('test', 'verify', 'mixed') and (scope is None or scope in r[1].scopes)]
    if hits:
        return hits[-1][2]
    return 'unclear' if any(r[1].kind == 'test' and not r[1].scopes for r in later) else 'none'


def judge_evidence(uses, root, claims):
    """(차단 사유, 경고). 설계 보고서 D3 판정표를 따른다. 차단 사유는 1회 차단, 경고는 차단이 아니다.

    관련 편집이 있는 범위마다 따로 본다: 통과 주장이 있는데 그 범위의 마지막 편집 뒤 검증이 성공이 아니면(기록 없음·실패·불명) 차단 사유다.
    통과 주장이 없으면 차단하지 않고, 결과 불명이면 경고만 한다. 편집이 없으면 이번 턴 검증 결과만 본다: 실패인데 통과를 주장하면 차단, 불명이면 경고.
    편집도 검증도 없는 턴의 통과 주장은 초기 버전에서 잡지 않는다(이전 결과 중계와 구분이 어렵다).
    """
    problems, notices = [], []
    edits, runs = edit_scopes(uses, root), verification_runs(uses)
    first = {}
    for kind, sentence in claims:
        first.setdefault(kind, sentence)
    if edits:
        for scope, (idx, rel) in edits.items():
            states = [(k, evidence_state(runs, k, idx, scope)) for k in first]
            bad = [(k, s) for k, s in states if s != 'success']
            if bad:
                kind, state = bad[0]
                problems.append(f'이번 턴에 {rel} 를 고쳤고({SCOPE_LABEL[scope]} 범위) 통과를 주장했는데 {WHY[state]}: "{first[kind]}"')
            elif not first and evidence_state(runs, 'test', idx, scope) == 'unclear':
                notices.append(f'{rel} 를 고친 뒤 돌린 검증의 결과를 성공으로 확인하지 못했다. 성공이라고 쓰지 말고 결과 불명·미검증으로 쓴다.')
    else:
        for kind, sentence in first.items():
            state = evidence_state(runs, kind, -1)
            if state == 'failure':
                problems.append(f'통과를 주장했는데 이번 턴에 돌린 검증은 {WHY[state]}: "{sentence}"')
            elif state == 'unclear':
                notices.append(f'이번 턴에 돌린 검증의 결과를 성공으로 확인하지 못했다. 결과 불명으로 안내한다: "{sentence}"')
    return problems, notices


def overclaims(text):
    """단정 문장이 있는데 확인하지 못한 것(헤지)이 하나도 없으면 그 문장들을 돌려준다."""
    if not text or HEDGE.search(text):
        return []
    sentences = re.split(r'(?<=[.!?다요])\s+|\n', text)
    return [s.strip()[:60] for s in sentences if CLAIM.search(s) and not NEGATION.search(s)]


def run(*cmd, timeout=30, cwd=None):
    """(종료 코드, 출력). 시간 안에 안 끝나면 코드는 None, 실행 파일이 없으면 127."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, f'{timeout}초 안에 끝나지 않았다'
    except OSError as e:
        return 127, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def failed(label, code, out):
    if code is None:
        return f'{label} 시간 초과 ({out})'
    return f'{label} 실패 (종료 코드 {code}): ' + (out.splitlines() or ['출력 없음'])[-1][:120]


def check(data, root, notices=None):
    """(고칠 수 있는 문제들, 점검 자체를 못 한 이유들). notices 리스트를 넘기면 차단 사유가 아닌 경고를 거기에 채운다(반환 모양은 그대로)."""
    problems, unverified = [], []
    notices = [] if notices is None else notices
    path = data.get('transcript_path')
    if path is not None and not isinstance(path, str):
        unverified.append('훅 입력의 transcript_path 가 글자가 아니다')
        path = None
    last = data.get('last_assistant_message')
    last = last if isinstance(last, str) else ''
    if path and Path(path).exists():
        try:
            uses = turn_tool_uses(path)
            last = last or last_assistant_text(path)   # 종료 시점에는 세션 기록에 아직 없을 수 있어 훅 입력 값을 먼저 쓴다
        except (OSError, UnicodeDecodeError) as e:
            uses = []
            unverified.append(f'세션 기록을 읽지 못해 테스트 기록을 확인하지 못했다 ({type(e).__name__})')
        found, warned = judge_evidence(uses, root, pass_claims(last))   # 예외는 잡지 않는다: main 이 "점검하지 못했다"로 막는다
        problems += found
        notices += warned
    claims = overclaims(last)
    if claims:
        problems.append(f'단정 표현이 있는데 "확인하지 못한 것"이 없다: "{claims[0]}"')
    code, out = run('git', 'status', '--porcelain', cwd=root)   # 읽기 전용 조회(#22). Django 검사는 훅이 실행하지 않는다(#19)
    if code != 0:
        unverified.append(failed('git status', code, out) + ' — 바뀐 파일을 알 수 없다')
    return problems, unverified


def unresolved(problems, unverified, notices=()):
    """재검사 뒤에도 남은 것을 사용자에게 알릴 한 줄로 쓴다. 두 번째 차단 대신 이것만 보낸다.

    문제(고칠 수 있는 것)와 점검하지 못한 것(훅 입력·기록·예기치 않은 오류)은 따로 적어 원인을 구분한다.
    """
    detail = ' '.join(x for x in (
        '해결되지 않은 문제: ' + ' / '.join(problems) + '.' if problems else '',
        '점검하지 못한 것: ' + ' / '.join(unverified) + '.' if unverified else '',
        '참고: ' + ' / '.join(notices) if notices else '') if x)
    return ('[끝내기 점검] 한 번 알렸는데도 해결되지 않아 다시 막지 않고 끝냅니다. ' + detail +
            ' 이 답변의 검증·통과 주장은 확인되지 않은 것으로 보세요.')


def emit(problems, unverified, active=False, notices=()):
    """active 가 거짓이면 한 번 막는다(decision: block). 참이면(재검사) 막지 않고 systemMessage 로 사용자에게만 알린다.

    additionalContext 는 쓰지 않는다: 실제 검증에서 이것이 모델을 다시 불러 Stop 훅이 8번 반복됐다.
    """
    parts = []
    if problems:
        parts.append('끝내기 전 점검에 걸렸다: ' + ' / '.join(problems) +
                     '. 할 수 있는 확인이면 지금 하고, 못 하는 것만 이유와 함께 "확인하지 못한 것"에 적어라. '
                     '답의 첫머리에 막힌 이유와 한 조치를 쓴다.')
    if unverified:
        parts.append('끝내기 전 점검을 하지 못했다: ' + ' / '.join(unverified) +
                     '. 점검을 통과했다·검증했다고 쓰지 말고, 점검하지 못했다는 사실을 답의 첫머리에 알려라.')
    if not parts:
        # 막을 것은 없고 안내(결과 불명 등)만 있다: 사용자에게만 알린다. decision·additionalContext 가 없어 모델을 다시 부르지 않는다.
        if notices:
            print(json.dumps({'systemMessage': '[끝내기 점검] ' + ' / '.join(notices)}, ensure_ascii=False))
        return
    if not active:
        if notices:
            parts.append('참고: ' + ' / '.join(notices))
        print(json.dumps({'decision': 'block', 'reason': ' '.join(parts)}, ensure_ascii=False))
        return
    print(json.dumps({'systemMessage': unresolved(problems, unverified, notices)}, ensure_ascii=False))


def main():
    try:
        data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
        if not isinstance(data, dict):
            raise ValueError('JSON 객체가 아니다')
    except ValueError as e:
        return emit([], [f'훅 입력(JSON)을 읽지 못했다 ({type(e).__name__})'])
    root = os.path.abspath(os.environ.get('CLAUDE_PROJECT_DIR') or '.')
    notices = []
    try:
        problems, unverified = check(data, root, notices)
    except Exception as e:   # 점검 코드 자체의 버그. 조용히 통과시키지 않고 점검하지 못했다고 알린다
        problems, unverified = [], [f'점검 중 예기치 않은 오류 ({type(e).__name__}: {str(e)[:100]})']
    emit(problems, unverified, active=bool(data.get('stop_hook_active')), notices=notices)


if __name__ == '__main__':
    main()
