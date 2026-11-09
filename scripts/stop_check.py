#!/usr/bin/env python3
"""Stop 훅. 코드를 바꾼 채로 끝내려 할 때 빠른 검사만 돌려서 문제가 있으면 알린다.

막지는 않는다(경고만). 막으면 고치지 못하는 상황에서 같은 검사를 되풀이하게 된다.
전체 테스트는 여기서 돌리지 않는다 — 그건 scripts/verify.sh(/verify)와 CI 가 한다.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def run(*cmd, timeout=30):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    if data.get('stop_hook_active'):
        return
    os.chdir(os.environ.get('CLAUDE_PROJECT_DIR') or '.')
    changed = [l[3:] for l in run('git', 'status', '--porcelain')[1].splitlines()]
    if not any(f.startswith(('center/', 'config/')) for f in changed):
        return
    py = '.venv/bin/python' if Path('.venv/bin/python').exists() else 'python3'
    problems = []
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
