#!/usr/bin/env bash
# 한 번에 돌리는 전체 점검. 결과를 "통과/실패"로 나눠 보여 주고, 하나라도 실패하면 종료 코드 1.
# 통과가 곧 안전하다는 뜻은 아니다 — 무엇을 확인했는지만 보여 준다.
cd "$(git rev-parse --show-toplevel)" || exit 64
py=python3; [ -x .venv/bin/python ] && py=$PWD/.venv/bin/python
# 앱 코드는 src/ 에 있다. Django 명령은 그 안에서 돌린다.
dj() { (cd src && "$py" "$@"); }
fail=0
step() {
  local name="$1"; shift
  if out=$("$@" 2>&1); then echo "통과  $name"; else echo "실패  $name"; echo "$out" | tail -5 | sed 's/^/        /'; fail=1; fi
}
step "Django 테스트" dj manage.py test
step "마이그레이션 누락 없음" dj manage.py makemigrations --check --dry-run
step "개인정보·금지 파일 검사" scripts/check_leaks.sh --all
step "하네스 스크립트 테스트" python3 -m unittest discover -s scripts
step "갈래 검사" python3 scripts/check_track.py tree
step "취약점 목록 ↔ 커밋" python3 scripts/check_manifest.py
echo "---"
[ "$fail" -eq 0 ] && echo "전부 통과. (실제 브라우저·HTTPS·동시 접속·팀 스캐너는 이 점검 밖이다)" || echo "실패한 항목이 있다."
exit "$fail"
