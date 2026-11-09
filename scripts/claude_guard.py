#!/usr/bin/env python3
"""Claude Code PreToolUse(Bash) 훅. 내가 하는 위험한 명령을 실행 전에 막거나 사용자에게 묻는다.

- 차단(종료 코드 2): `git commit --no-verify` (pre-commit 의 누출 검사를 건너뛰는 것)
- 확인(ask): 우리 저장소가 아닌 곳으로 쓰는 명령(git push, gh ... --repo/-R, gh api 쓰기),
             강제 푸시, 새 저장소 만들기, 실제 DB 에 `manage.py migrate`
파일 내용 검사는 하지 않는다 — 그건 scripts/check_leaks.sh 가 git 훅과 CI 에서 한다.
"""
import json
import re
import subprocess
import sys

OURS = 'howl213/jiacenter-web'   # jiacenter-web, jiacenter-web-portfolio 모두 이 접두사


def ask(reason):
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'ask',
        'permissionDecisionReason': reason}}, ensure_ascii=False))
    sys.exit(0)


def remote_url(cwd, remote='origin'):
    r = subprocess.run(['git', '-C', cwd or '.', 'remote', 'get-url', remote],
                       capture_output=True, text=True)
    return r.stdout.strip()


def without_heredocs(text):
    """heredoc 본문(파일에 쓸 글, 스크립트 원문)은 실행되는 명령이 아니므로 뺀다.

    이걸 안 하면 문서에 `git commit --no-verify` 라고 쓰기만 해도 훅이 막는다 —
    2026-11-09 실제로 내 문서 수정 명령이 이 훅에 막혔다.
    """
    return re.sub(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\b", '<<HEREDOC', text, flags=re.S)


def without_quotes(text):
    return re.sub(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'', '""', text)


def main():
    data = json.load(sys.stdin)
    cmd = without_heredocs((data.get('tool_input') or {}).get('command', ''))
    cwd = data.get('cwd')

    # shortcut: 짧은 형태(-n)는 -m 메시지 안의 글자와 구분하기 어려워 --no-verify 만 본다. 필요하면 파서로 바꾼다.
    # 따옴표 안의 글(-m "... --no-verify ...")은 실행 인자가 아니므로 이 검사에서는 뺀다.
    bare = without_quotes(cmd)
    if re.search(r'\bgit\s+(-\S+\s+)*commit\b', bare) and '--no-verify' in bare:
        print('git commit --no-verify 는 누출 검사를 건너뜁니다. 검사에 걸렸다면 내용을 고치세요. '
              '검사 자체를 건너뛰어야 하면 사용자가 직접 실행합니다.', file=sys.stderr)
        sys.exit(2)

    if re.search(r'\bgit\s+(-\S+\s+)*push\b', cmd):
        if re.search(r'--force\b|--force-with-lease|\s-f\b', cmd):
            ask('강제 푸시는 원격의 이력을 덮어씁니다. 진행할까요?')
        m = re.search(r'\bpush\b(?:\s+-\S+)*\s+(\S+)', cmd)
        remote = m.group(1) if m and not m.group(1).startswith('-') else 'origin'
        url = remote_url(cwd, remote) or remote
        if OURS not in url:
            ask(f'우리 저장소가 아닌 곳으로 푸시합니다 ({url}). 올리는 파일에 개인정보·답안지·내부 문서가 없는지 확인했나요?')

    for m in re.finditer(r'\bgh\b.*?(?:--repo|-R)[ =](\S+)', cmd):
        if not m.group(1).startswith(OURS):
            ask(f'다른 저장소({m.group(1)})에 쓰는 gh 명령입니다. 진행할까요?')
    for m in re.finditer(r'\bgh\s+api\b.*?(?:-X|--method)\s+(POST|PUT|PATCH|DELETE)\b.*?repos/([^\s/]+/[^\s/]+)', cmd):
        if not m.group(2).startswith(OURS):
            ask(f'다른 저장소({m.group(2)})에 쓰는 API 호출입니다. 진행할까요?')
    if re.search(r'\bgh\s+repo\s+(create|delete|edit)\b', cmd):
        ask('저장소를 만들거나 바꾸거나 지우는 명령입니다. 공개 범위와 대상 이름을 확인했나요?')

    if re.search(r'manage\.py\s+migrate\b', cmd) and '--settings' not in cmd:
        ask('실제 db.sqlite3 에 마이그레이션을 적용합니다. 진행할까요?')


if __name__ == '__main__':
    main()
