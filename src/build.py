"""Vercel 빌드 때 빈 SQLite 를 만들고 모의 값을 채운다. 모의 값만 쓴다 — 실제 정보를 넣지 않는다.

shortcut: 빌드 때 만든 DB 파일이 실행 환경에 읽기 전용으로 실릴 수 있다(공식 문서에 없음). 로그인·출결 저장이
안 되면 외부 Postgres 로 바꾼다(99.result/docs/확인사항.md 의 Vercel 줄).
"""
import subprocess
import sys

for cmd in (['migrate', '--noinput'], ['seed_dummy']):
    subprocess.run([sys.executable, 'manage.py', *cmd], check=True)
