#!/bin/sh
# 템플릿에 쓰인 Tailwind 모양 이름으로 CSS 파일을 뽑는다. 템플릿의 class 를 바꾸면 다시 돌리고 결과물도 같이 커밋한다.
# 도구: https://github.com/tailwindlabs/tailwindcss/releases 의 v4.3.5 단독 실행 파일(받은 뒤 sha256sums.txt 로 확인).
# 저장소에는 넣지 않는다(84MB). 다른 곳에 두었으면 TAILWINDCSS=경로 로 알려 준다.
set -e
cd "$(dirname "$0")/.."
"${TAILWINDCSS:-$HOME/.local/share/jiacenter-web/tailwindcss}" \
  -i center/tailwind.css -o center/static/center/tailwind.css --minify
