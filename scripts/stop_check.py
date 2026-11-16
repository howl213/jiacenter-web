#!/usr/bin/env python3
"""Stop 훅. 끝내려 할 때 아래 중 하나라도 걸리면 한 번 막고, 이유를 Claude 에게 돌려준다(Claude Code 가 그 이유를 받아 이어서 일한다).

  1) 이번 턴에 center/·config/ 코드를 고쳤는데 그 뒤로 테스트(manage.py test, verify.sh 등)를 돌린 기록이 없다
     — "할 수 있는데 안 한 확인"의 증거라서 기록으로 판정한다(세션 기록의 도구 호출).
  2) 코드가 바뀐 채인데 manage.py check 나 마이그레이션 검사가 실패한다
  3) 방금 한 마지막 답변에 "완벽하다/문제없다/안전하다" 같은 단정이 있는데 "확인하지 못한 것"이 없다

되풀이 방지: stop_hook_active 가 켜져 있으면(이미 이 훅 때문에 이어서 일하는 중) 통과시킨다. Claude Code 쪽에도 연속 차단 상한이 있다.
"사용자가 직접 확인해야 하는가"는 스크립트가 알 수 없다 — 그 판단은 CLAUDE.md 2절 3번 줄이 Claude 에게 맡긴다.
3)번은 문장 모양만 보는 거친 검사라 틀릴 수 있다. 전체 테스트는 여기서 돌리지 않는다(scripts/verify.sh 와 CI 가 한다).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CLAIM = re.compile(r'완벽|문제\s*없|안전합니다|안전해요|안전하다|허점이?\s*없|걱정\s*없')
NEGATION = re.compile(r'않|아니|못\s|금지|말하지|쓰지|뜻이|라고\s*(말|쓰|적)')
HEDGE = re.compile(r'확인하지\s*못|확인\s*못|미확인|검증하지\s*못|보지\s*못|못\s*봤|안\s*한\s*것')
EDIT_TOOLS = {'Edit', 'Write', 'NotebookEdit'}
TEST_CMD = re.compile(r'manage\.py\s+test|verify\.sh|unittest|pytest')


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


def turn_tool_uses(transcript_path):
    """마지막 사용자 입력 이후에 부른 도구들을 (이름, 입력) 순서대로 돌려준다."""
    uses = []
    for entry in entries(transcript_path):
        content = (entry.get('message') or {}).get('content')
        if entry.get('type') == 'user':
            # 도구 결과(tool_result)만 든 항목은 사용자 입력이 아니다.
            if isinstance(content, str) or (isinstance(content, list) and any(
                    isinstance(b, dict) and b.get('type') == 'text' for b in content)):
                uses = []
        elif entry.get('type') == 'assistant' and isinstance(content, list):
            uses += [(b.get('name'), b.get('input') or {}) for b in content
                     if isinstance(b, dict) and b.get('type') == 'tool_use']
    return uses


def untested_edit(uses, root):
    """이번 턴의 마지막 코드 수정 파일을 돌려준다. 그 뒤에 테스트를 돌렸으면 None."""
    last = None
    for i, (name, inp) in enumerate(uses):
        path = inp.get('file_path') or inp.get('notebook_path') or ''
        if name in EDIT_TOOLS and path:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
            if rel.startswith(('center/', 'config/')):
                last = (i, rel)
    if last is None:
        return None
    ran_test = any(n == 'Bash' and TEST_CMD.search(str(inp.get('command', ''))) for n, inp in uses[last[0] + 1:])
    return None if ran_test else last[1]


def overclaims(text):
    """단정 문장이 있는데 확인하지 못한 것(헤지)이 하나도 없으면 그 문장들을 돌려준다."""
    if not text or HEDGE.search(text):
        return []
    sentences = re.split(r'(?<=[.!?다요])\s+|\n', text)
    return [s.strip()[:60] for s in sentences if CLAIM.search(s) and not NEGATION.search(s)]


def run(*cmd, timeout=30):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    if data.get('stop_hook_active'):
        return
    root = os.environ.get('CLAUDE_PROJECT_DIR') or '.'
    os.chdir(root)
    problems = []
    path = data.get('transcript_path')
    has_transcript = bool(path) and Path(path).exists()
    if has_transcript:
        edited = untested_edit(turn_tool_uses(path), root)
        if edited:
            problems.append(f'이번 턴에 {edited} 를 고쳤는데 그 뒤로 테스트를 돌린 기록이 없다')
    # 마지막 답변은 훅이 직접 주는 값을 먼저 쓴다(종료 시점에는 세션 기록에 아직 없을 수 있다는 문서 설명).
    last = data.get('last_assistant_message') or (last_assistant_text(path) if has_transcript else '')
    claims = overclaims(last)
    if claims:
        problems.append(f'단정 표현이 있는데 "확인하지 못한 것"이 없다: "{claims[0]}"')
    changed = [l[3:] for l in run('git', 'status', '--porcelain')[1].splitlines()]
    if any(f.startswith(('center/', 'config/')) for f in changed):
        py = '.venv/bin/python' if Path('.venv/bin/python').exists() else 'python3'
        code, out = run(py, 'manage.py', 'check')
        if code:
            problems.append('manage.py check 실패: ' + out.splitlines()[-1][:120])
        code, out = run(py, 'manage.py', 'makemigrations', '--check', '--dry-run')
        if code:
            problems.append('모델이 바뀌었는데 마이그레이션 파일이 없다 (makemigrations)')
    if problems:
        reason = ('끝내기 전 점검에 걸렸다: ' + ' / '.join(problems) +
                  '. 할 수 있는 확인이면 지금 하고, 못 하는 것만 이유와 함께 "확인하지 못한 것"에 적어라. '
                  '답의 첫머리에 막힌 이유와 한 조치를 쓴다.')
        print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
