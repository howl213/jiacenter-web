#!/usr/bin/env python3
"""두 갈래가 섞이지 않았는지 본다.

  main  — 실제 센터용 안전한 껍데기. 일부러 심은 취약점이 한 줄도 있으면 안 된다.
  vuln  — 팀 웹 해킹 실습용. 답안지(SECURITY_REVIEW.md)가 있으면 안 되고 삽입 목록이 있어야 한다.

  check_track.py tree              현재 작업 트리를 브랜치 종류에 맞는 규칙으로 검사한다
  check_track.py pr <base> <head>  PR 방향 검사. vuln 에서 main 으로 가는 PR 은 막는다

브랜치 이름이 vuln 으로 시작하면 vuln, 아니면 main 규칙이다.
CI 에서는 GITHUB_HEAD_REF / GITHUB_REF_NAME 을, 로컬에서는 현재 브랜치를 쓴다. TRACK_BRANCH 로 덮어쓸 수 있다.
일치한 내용은 출력하지 않고 파일 이름과 줄 번호만 알린다.
"""
import os
import re
import subprocess
import sys

MARKER = r'\[실습 A[0-9]{2}\]'            # 심은 코드 옆에 붙이는 표시
BANNER = '실습용 취약 버전'
SELF = {'scripts/check_track.py', 'scripts/test_check_track.py'}


def git(*args):
    return subprocess.run(['git', '-c', 'core.quotepath=false', *args], capture_output=True, text=True).stdout


def branch_name():
    return (os.environ.get('TRACK_BRANCH') or os.environ.get('GITHUB_HEAD_REF')
            or os.environ.get('GITHUB_REF_NAME') or git('rev-parse', '--abbrev-ref', 'HEAD').strip())


def check_tree():
    kind = 'vuln' if branch_name().startswith('vuln') else 'main'
    files = [f for f in git('ls-files').splitlines() if f]
    problems = []
    if kind == 'main':
        if 'docs/vuln-manifest.md' in files:
            problems.append('docs/vuln-manifest.md (취약점 삽입 목록)가 main 갈래에 있다')
        # docs/ 는 설명 글이 있을 수 있어 뺀다. 코드·템플릿·설정만 본다.
        for f in files:
            if f in SELF or f.startswith('docs/'):
                continue
            text = git('show', f':{f}')
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(MARKER, line) or BANNER in line:
                    problems.append(f'{f}:{i} 취약판 표시가 main 갈래에 있다')
        base = git('merge-base', 'HEAD', 'origin/main').strip()
        if base:
            for s in git('log', f'{base}..HEAD', '--format=%s').splitlines():
                if s.startswith('vuln('):
                    problems.append(f'취약판 커밋이 main 갈래에 섞였다: {s[:40]}')
    else:
        if 'SECURITY_REVIEW.md' in files:
            problems.append('SECURITY_REVIEW.md(답안지)가 vuln 갈래에 있다')
        if 'docs/vuln-manifest.md' not in files:
            problems.append('docs/vuln-manifest.md (취약점 삽입 목록)가 없다')
    return kind, problems


def check_pr(base, head):
    if base == 'main' and head.startswith('vuln'):
        return ['vuln 갈래에서 main 으로 가는 PR 입니다. 거꾸로 main 을 vuln 에 합치세요 (취약 코드가 main 에 들어가면 안 됩니다).']
    return []


def main():
    args = sys.argv[1:]
    if args[:1] == ['pr'] and len(args) == 3:
        problems, kind = check_pr(args[1], args[2]), 'pr'
    elif args[:1] == ['tree']:
        kind, problems = check_tree()
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(64)
    for p in problems:
        print(f'갈래 검사 [{kind}] {p}', file=sys.stderr)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
