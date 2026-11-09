#!/usr/bin/env bash
# 개인정보·시크릿·금지 파일 검사. 판정은 이 한 곳에서만 한다.
# git pre-commit(.githooks), CI(.github/workflows), Claude 훅이 모두 이 스크립트를 부른다.
#
#   check_leaks.sh --staged    커밋 직전, 스테이징된 파일 (기본값)
#   check_leaks.sh --all       git 이 추적하는 모든 파일 (CI)
#   check_leaks.sh --external  다른 저장소·공개 저장소로 보낼 파일 — 위 검사 + 답안지·내부 문서 금지
#
# 일치가 하나라도 있으면 종료 코드 1. 이메일·전화번호 모양을 찾는 것이지 안전을 증명하지는 않는다.
set -u
mode="${1:---staged}"
cd "$(git rev-parse --show-toplevel)" || exit 64

# 한글 파일 이름은 기본 설정에서 "\355\225..." 처럼 따옴표와 8진수로 바뀌어 나와
# 뒤에서 파일을 못 찾고 건너뛰게 된다. 그래서 quotepath 를 끈다.
case "$mode" in
  --staged) files=$(git -c core.quotepath=false diff --cached --name-only --diff-filter=ACMR) ;;
  --all|--external) files=$(git -c core.quotepath=false ls-files) ;;
  *) echo "사용법: $0 [--staged|--all|--external]" >&2; exit 64 ;;
esac

fail=0
bad() { echo "누출 검사 [$1] $2" >&2; fail=1; }

# 이 스크립트와 그 테스트는 검사 대상 패턴을 담고 있으므로 내용 검사에서 뺀다.
skip_content='^scripts/(check_leaks\.sh|test_check_leaks\.py)$'

forbidden_name='(^|/)(db\.sqlite3|\.env|id_rsa|[^/]*\.(pem|key|sqlite3))$|^logs/'
external_name='^(SECURITY_REVIEW\.md|CLAUDE\.md)$|^docs/|^\.claude/'

email='[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'
email_ok='@users\.noreply\.github\.com|noreply@anthropic\.com|@example\.(com|org)'
phone='01[016789][-. ]?[0-9]{3,4}[-. ]?[0-9]{4}'
phone_dummy='01[016789][-. ]?0000'
path='/Users/[A-Za-z0-9._-]+|C:\\Users\\'
key="(SECRET_KEY|PASSWORD|TOKEN|API_KEY)[[:space:]]*=[[:space:]]*['\"][^'\"]{8,}['\"]"
key_ok='dev-only|example|changeme'
marker='\[(H|M|L)-[0-9]{2}\]'

scan() {  # 이름, 패턴, 허용 패턴(없으면 빈 문자열), 파일
  local label="$1" pat="$2" ok="$3" f="$4" hits
  hits=$(git show ":$f" 2>/dev/null | grep -nIE "$pat" || true)
  [ -n "$ok" ] && hits=$(printf '%s\n' "$hits" | grep -vE "$ok" || true)
  if [ -n "$hits" ]; then
    fail=1   # 파이프 안(하위 셸)에서 바꾸면 사라지므로 밖에서 표시한다
    # 일치한 내용은 출력하지 않는다 — 로그에 개인정보가 다시 남지 않게 줄 번호만 알린다
    printf '%s\n' "$hits" | while IFS= read -r line; do
      echo "누출 검사 [$label] $f:${line%%:*}" >&2
    done
  fi
}

while IFS= read -r f; do
  [ -z "$f" ] && continue
  if printf '%s' "$f" | grep -qE "$forbidden_name" && ! printf '%s' "$f" | grep -qE '\.env\.example$'; then
    bad "금지 파일" "$f"
  fi
  if [ "$mode" = "--external" ] && printf '%s' "$f" | grep -qE "$external_name"; then
    bad "외부 반출 금지" "$f"
  fi
  printf '%s' "$f" | grep -qE "$skip_content" && continue
  scan "이메일" "$email" "$email_ok" "$f"
  scan "전화번호" "$phone" "$phone_dummy" "$f"
  scan "사용자 경로" "$path" "" "$f"
  scan "키 값" "$key" "$key_ok" "$f"
  [ "$mode" = "--external" ] && scan "점검 번호" "$marker" "" "$f"
done <<< "$files"

# 커밋 작성자 이메일이 개인 주소면 새 커밋마다 그대로 박힌다. 막지는 않고 알린다.
if [ "$mode" = "--staged" ]; then
  author=$(git config user.email || true)
  case "$author" in
    *@users.noreply.github.com|"") ;;
    *) echo "경고: git 작성자 이메일이 개인 주소입니다 ($author). 공개·공유 가능성이 있으면 GitHub noreply 주소로 바꾸세요." >&2 ;;
  esac
fi

[ "$fail" -eq 0 ] || echo "누출 검사 실패. 위 항목을 고친 뒤 다시 시도하세요." >&2
exit "$fail"
