#!/usr/bin/env python3
"""SessionStart 훅. 새 세션이 열릴 때 지금 상태를 한 번에 알려 준다.

사람이 매번 묻던 것들(브랜치, 미커밋 변경, 푸시 안 한 커밋, 적용 안 된 마이그레이션, 훅 설정)을 보여 준다.
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
    kind = 'vuln(팀 실습용, 일부러 취약함)' if branch.startswith('vuln') else 'main 계열(안전한 껍데기)'
    lines = [f'[프로젝트 상태] 브랜치 {branch} — {kind}']

    dirty = len([l for l in run('git', 'status', '--porcelain').splitlines() if l])
    lines.append(f'미커밋 변경 {dirty}개' if dirty else '작업 트리 깨끗함')

    ahead = run('git', 'rev-list', '--count', '@{u}..HEAD') if run('git', 'rev-parse', '--abbrev-ref', '@{u}') else ''
    lines.append(f'푸시 안 한 커밋 {ahead}개' if ahead not in ('', '0') else
                 ('상위 브랜치 없음(아직 푸시 안 함)' if not run('git', 'rev-parse', '--abbrev-ref', '@{u}') else '푸시할 커밋 없음'))

    py = Path('.venv/bin/python')
    if py.exists() and Path('manage.py').exists():
        plan = run(str(py), 'manage.py', 'showmigrations', '--plan', timeout=15)
        pending = sum(1 for l in plan.splitlines() if l.strip().startswith('[ ]'))
        if pending:
            lines.append(f'적용 안 된 마이그레이션 {pending}개 — 로컬 DB 에는 `manage.py migrate` 가 필요하다(사용자가 직접)')

    if run('git', 'config', 'core.hooksPath') != '.githooks':
        lines.append('경고: git pre-commit 훅이 꺼져 있다 — `git config core.hooksPath .githooks`')
    if not run('git', 'config', 'user.email').endswith('@users.noreply.github.com'):
        lines.append('참고: git 작성자 이메일이 개인 주소다(커밋마다 박힘)')
    try:   # 병합된 규칙은 로컬에 받아야 새 세션에 적용된다. 오프라인이면 조용히 넘어간다.
        run('git', 'fetch', '-q', 'origin', 'main', timeout=6)
        behind = run('git', 'rev-list', '--count', 'HEAD..origin/main')
        if behind not in ('', '0'):
            lines.append(f'경고: 이 작업 폴더에 origin/main 의 {behind}개 커밋이 없다 — 병합된 규칙·지침이 반영되지 않았을 수 있다. 병합 뒤에는 `git pull` 이 필요하다')
    except Exception:
        pass
    lines.append('목표 ① main = 실제 구현용 안전한 껍데기(모의 값만, 실제 전환은 사용자 허락)  ② vuln = 팀 OWASP 실습용 취약 표면(로컬 전용). 작업이 어느 쪽인지 먼저 말한다')
    lines.append('마지막 커밋: ' + run('git', 'log', '-1', '--format=%h %s')[:70])
    lines.append('규칙 네 줄: CLAUDE.md 2절(질문마다 훅이 같은 줄을 다시 넣는다). 문서는 낡았을 수 있다 — 코드가 기준이다' + (', 취약점 목록: docs/vuln-manifest.md' if Path('docs/vuln-manifest.md').exists() else ''))

    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                             'additionalContext': '\n'.join(lines)}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit(0)
