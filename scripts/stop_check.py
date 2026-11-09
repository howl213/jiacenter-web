#!/usr/bin/env python3
"""Stop 훅. 끝내려 할 때 두 가지를 본다. 둘 다 경고만 한다(막으면 되풀이되기만 한다).

  1) 코드를 바꾼 채라면 빠른 검사 (manage.py check, 마이그레이션 누락)
  2) 방금 한 마지막 답변에 "완벽하다/문제없다/안전하다" 같은 단정이 있는데 "확인하지 못한 것"이 없는지

전체 테스트는 여기서 돌리지 않는다 — 그건 scripts/verify.sh(/verify)와 CI 가 한다.
2)번은 이 프로젝트의 규칙(CLAUDE.md 2번: 확인한 것만 말한다)을 문장 모양으로 거칠게 보는 것이라 틀릴 수 있다.
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


def last_assistant_text(transcript_path):
    """세션 기록(JSONL)에서 마지막 assistant 글을 꺼낸다. 형식이 다르면 빈 문자열."""
    text = ''
    for line in Path(transcript_path).read_text(encoding='utf-8').splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get('type') != 'assistant':
            continue
        content = (entry.get('message') or {}).get('content')
        if isinstance(content, list):
            parts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
            if parts:
                text = '\n'.join(parts)
    return text


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
    os.chdir(os.environ.get('CLAUDE_PROJECT_DIR') or '.')
    problems = []
    path = data.get('transcript_path')
    if path and Path(path).exists():
        claims = overclaims(last_assistant_text(path))
        if claims:
            problems.append(f'단정 표현이 있는데 "확인하지 못한 것"이 없다: "{claims[0]}"')
    changed = [l[3:] for l in run('git', 'status', '--porcelain')[1].splitlines()]
    if not any(f.startswith(('center/', 'config/')) for f in changed):
        if problems:
            print(json.dumps({'systemMessage': '끝내기 전 점검: ' + ' / '.join(problems)}, ensure_ascii=False))
        return
    py = '.venv/bin/python' if Path('.venv/bin/python').exists() else 'python3'
    code, out = run(py, 'manage.py', 'check')
    if code:
        problems.append('manage.py check 실패: ' + out.splitlines()[-1][:120])
    code, out = run(py, 'manage.py', 'makemigrations', '--check', '--dry-run')
    if code:
        problems.append('모델이 바뀌었는데 마이그레이션 파일이 없다 (makemigrations)')
    if problems:
        print(json.dumps({'systemMessage': '끝내기 전 점검: ' + ' / '.join(problems)}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
