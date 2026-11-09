#!/usr/bin/env python3
"""취약점 삽입 목록(docs/vuln-manifest.md)의 `vuln(A0N)` 표시마다 그 이름의 커밋이 있는지 본다.

목록에는 있는데 커밋이 없거나(심지 않았거나 이력이 바뀜), 커밋은 있는데 목록에 없으면 팀에 줄 W8 목록이 틀린다.
vuln 갈래가 아니면(목록 파일이 없으면) 아무것도 하지 않는다.
"""
import re
import subprocess
import sys
from pathlib import Path

path = Path('docs/vuln-manifest.md')
if not path.exists():
    sys.exit(0)

listed = set(re.findall(r'`(vuln\(A\d\d\)[^`]*)`', path.read_text(encoding='utf-8')))
subjects = subprocess.run(['git', 'log', '--format=%s'], capture_output=True, text=True).stdout.splitlines()
committed = {re.match(r'(vuln\(A\d\d\))', s).group(1) for s in subjects if s.startswith('vuln(')}
listed_keys = {re.match(r'(vuln\(A\d\d\))', x).group(1) for x in listed}

missing = sorted(listed_keys - committed)
unlisted = sorted(committed - listed_keys)
for m in missing:
    print(f'목록 검사: {m} 가 목록에 있으나 같은 이름의 커밋이 없다', file=sys.stderr)
for u in unlisted:
    print(f'목록 검사: {u} 커밋이 있으나 목록에 없다', file=sys.stderr)
sys.exit(1 if missing or unlisted else 0)
