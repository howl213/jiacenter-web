#!/usr/bin/env python3
"""vuln 갈래를 팀 실습용 폴더로 내보낸다. 푸시는 하지 않는다 — 폴더만 만든다.

  export_for_team.py <새 폴더>

하는 일
  1) git 이 추적하는 파일만 가져온다 (db.sqlite3, .env, logs 는 애초에 없다)
  2) 내부 문서·시험·하네스·답안지를 뺀다 (docs/, CLAUDE.md, SECURITY_REVIEW.md, .claude/, .github/, scripts/, 시험 파일, 흐름도)
  3) 심은 곳 옆의 `# [실습 A0N]` 설명 주석 블록을 지운다. 공격을 알려 주는 설명이라서다
  4) 팀용 README 를 새로 쓴다 (실행 방법과 로컬 전용 규칙뿐)
  5) 새 임시 저장소로 보고 `check_leaks.sh --external` 와 남은 표시 검사를 돌린 뒤 `manage.py check` 를 돌린다
하나라도 실패하면 폴더를 지우고 실패로 끝낸다.

주의: 코드 안의 설명 글(예: 방어를 설명하는 독스트링)까지 모두 걸러 주지는 못한다. 표시 주석만 지운다.
이 폴더는 W8 공개(팀 3단계) 전에는 소스가 아니라 실행 환경(compose)으로만 쓰는 편이 안전하다.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = re.compile(r'\[실습')
EXCLUDE_DIRS = ('docs/', '.claude/', '.githooks/', '.github/', 'scripts/')
EXCLUDE_FILES = {'CLAUDE.md', 'SECURITY_REVIEW.md', 'README.md'}
EXCLUDE_SUFFIX = ('.svg',)
TEXT_SUFFIX = ('.py', '.html', '.css', '.txt', '.yml', '.yaml', '.md', '.example')
FORBIDDEN_WORDS = ['[실습', 'vuln(', '답안', 'SECURITY_REVIEW', '삽입 목록']

TEAM_README = """# 지역아동센터 웹 (실습 대상)

팀 웹 해킹 실습용 대상 앱입니다. **로컬 전용**이며 모의 데이터만 들어 있습니다.

## 실행

```bash
docker compose up --build
```

- 주소: <http://127.0.0.1:8000> (이 기기에서만 열립니다. 포트 설정을 바꾸지 마세요)
- 같은 compose 네트워크의 스캐너는 `http://web:8000` 으로 접근합니다
- 종료: `docker compose down`

## 규칙

- 인터넷에 공개하지 않습니다. 실제 아동·보호자 정보를 넣지 않습니다
- 공격은 이 로컬 환경에서만 합니다
"""


def run(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def excluded(path):
    name = Path(path).name
    return (path in EXCLUDE_FILES or path.startswith(EXCLUDE_DIRS) or path.endswith(EXCLUDE_SUFFIX)
            or name == 'tests.py' or name.startswith('test_'))


def strip_markers(text, path):
    """`# [실습 ...]` 로 시작하는 주석 줄과 그 뒤에 이어지는 주석 줄을 지운다. 그 밖의 표시는 오류다."""
    out, skipping = [], False
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        stripped = line.lstrip()
        if MARKER.search(line):
            if not stripped.startswith('#'):
                raise ValueError(f'{path}:{n} 표시가 주석 줄이 아닙니다(독스트링·줄 끝 주석). 주석 줄로 옮기세요')
            skipping = True
            continue
        if skipping and stripped.startswith('#'):
            continue
        skipping = False
        out.append(line)
    return ''.join(out)


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 64
    dest = Path(sys.argv[1]).resolve()
    if dest.exists() and any(dest.iterdir()):
        print(f'이미 있는 폴더입니다: {dest}', file=sys.stderr)
        return 64
    root = Path(run('git', 'rev-parse', '--show-toplevel').stdout.strip())
    files = run('git', '-c', 'core.quotepath=false', 'ls-files', cwd=root).stdout.splitlines()
    dest.mkdir(parents=True, exist_ok=True)
    kept, dropped = 0, []
    try:
        for f in files:
            if excluded(f):
                dropped.append(f)
                continue
            target = dest / f
            target.parent.mkdir(parents=True, exist_ok=True)
            src = root / f
            if f.endswith(TEXT_SUFFIX):
                target.write_text(strip_markers(src.read_text(encoding='utf-8'), f), encoding='utf-8')
            else:
                shutil.copy2(src, target)
            kept += 1
        (dest / 'README.md').write_text(TEAM_README, encoding='utf-8')

        for p in dest.rglob('*'):
            if p.is_file() and p.suffix in TEXT_SUFFIX + ('.md',):
                text = p.read_text(encoding='utf-8')
                for w in FORBIDDEN_WORDS:
                    if w in text:
                        raise ValueError(f'{p.relative_to(dest)} 에 내보내면 안 되는 말이 남았습니다: {w}')

        git = lambda *a: subprocess.run(['git', *a], cwd=dest, check=True, capture_output=True)
        git('init', '-q')
        git('config', 'user.email', '0+export@users.noreply.github.com')
        git('config', 'user.name', 'export')
        git('add', '-A')
        leak = run('bash', str(HERE / 'check_leaks.sh'), '--external', cwd=dest)
        if leak.returncode:
            raise ValueError('개인정보·금지 파일 검사 실패:\n' + leak.stderr)
        shutil.rmtree(dest / '.git')

        if os.environ.get('EXPORT_SKIP_CHECK') != '1':     # 시험에서만 끈다
            py = root / '.venv' / 'bin' / 'python'
            py = str(py) if py.exists() else sys.executable
            chk = run(py, 'manage.py', 'check', cwd=dest)
            if chk.returncode:
                raise ValueError('내보낸 앱이 manage.py check 를 통과하지 못했습니다:\n' + (chk.stdout + chk.stderr)[-400:])
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        print(f'내보내기 실패: {e}', file=sys.stderr)
        return 1

    # manage.py check 가 만든 부산물(로그, DB, 캐시)은 내보내는 폴더에 남기지 않는다
    for junk in [dest / 'logs', *dest.rglob('__pycache__'), *dest.rglob('*.sqlite3')]:
        shutil.rmtree(junk, ignore_errors=True) if junk.is_dir() else junk.unlink(missing_ok=True)
    print(f'내보냄: {dest}  (파일 {kept}개 포함, {len(dropped)}개 제외)')
    top = sorted({d.split('/')[0] if d.startswith(EXCLUDE_DIRS) else d for d in dropped})
    print('제외한 것: ' + ', '.join(top))
    print('푸시는 하지 않았습니다. 올리기 전에 폴더 내용을 직접 한 번 더 보세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
