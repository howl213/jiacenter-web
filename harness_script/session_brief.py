#!/usr/bin/env python3
"""SessionStart 훅. 새 세션이 열릴 때 지금 상태를 한 번에 알려 준다.

사람이 매번 묻던 것들(브랜치, 미커밋 변경, 푸시 안 한 커밋, 적용 안 된 마이그레이션, 훅 설정)을 보여 준다. 정상이면 한 줄, 경고만 따로 줄을 늘린다.
네트워크는 origin/main 을 가져오는 한 번(6초 제한)만 쓴다. 무엇이든 실패하면 아무 말도 하지 않는다 — 세션 시작을 막으면 안 된다.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def run(*cmd, timeout=6):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def main():
    root = os.environ.get('CLAUDE_PROJECT_DIR') or '.'
    os.chdir(root)
    branch = run('git', 'rev-parse', '--abbrev-ref', 'HEAD')
    kind = 'vuln' if branch.startswith('vuln') else 'main 계열'
    # 정상이면 이 한 줄이 전부다. 목표·규칙 안내는 CLAUDE.md 가 이미 하므로 여기서 되풀이하지 않는다.
    status = [f'[상태] {branch} ({kind})']
    warnings = []

    dirty = len([l for l in run('git', 'status', '--porcelain').splitlines() if l])
    status.append(f'미커밋 {dirty}개' if dirty else '깨끗함')

    upstream = run('git', 'rev-parse', '--abbrev-ref', '@{u}')
    ahead = run('git', 'rev-list', '--count', '@{u}..HEAD') if upstream else ''
    status.append(f'푸시 안 한 커밋 {ahead}개' if ahead not in ('', '0') else
                  ('상위 브랜치 없음' if not upstream else '푸시할 것 없음'))

    py = Path('.venv/bin/python')
    if py.exists() and Path('src/manage.py').exists():
        plan = run(str(py.resolve()), 'src/manage.py', 'showmigrations', '--plan', timeout=15)
        pending = sum(1 for l in plan.splitlines() if l.strip().startswith('[ ]'))
        if pending:
            warnings.append(f'적용 안 된 마이그레이션 {pending}개 — 로컬 DB 에는 `src/manage.py migrate` 가 필요하다(사용자가 직접)')
        else:
            status.append('마이그레이션 적용됨')

    if run('git', 'config', 'core.hooksPath') != '.githooks':
        warnings.append('경고: git pre-commit 훅이 꺼져 있다 — `git config core.hooksPath .githooks`')
    if not run('git', 'config', 'user.email').endswith('@users.noreply.github.com'):
        warnings.append('참고: git 작성자 이메일이 개인 주소다(커밋마다 박힘)')
    try:   # 병합된 규칙은 로컬에 받아야 새 세션에 적용된다. 오프라인이면 조용히 넘어간다.
        run('git', 'fetch', '-q', 'origin', 'main', timeout=6)
        behind = run('git', 'rev-list', '--count', 'HEAD..origin/main')
        if behind not in ('', '0'):
            warnings.append(f'경고: 이 작업 폴더에 origin/main 의 {behind}개 커밋이 없다 — 병합된 규칙·지침이 반영되지 않았을 수 있다. 병합 뒤에는 `git pull` 이 필요하다')
    except Exception:
        pass
    if kind == 'vuln' and Path('docs/vuln-manifest.md').exists():
        warnings.append('취약점 목록: docs/vuln-manifest.md')
    lines = [' · '.join(status)] + warnings

    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                             'additionalContext': '\n'.join(lines)}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit(0)
