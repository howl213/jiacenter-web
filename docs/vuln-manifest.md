# 삽입 목록 (vuln/practice 전용)

이 파일은 **실습본에 일부러 심은 취약점 목록**이다. 이 파일이 있으면 그 브랜치는 vuln 갈래로
취급된다 (`scripts/check_track.py`, `center/tests.py` 의 배포 점검 건너뜀이 이 파일로 판단한다).

- 커밋 하나 = 취약점 하나 = 커밋 제목이 `vuln(A0N) ...`.
- 심은 자리는 코드에 `# [실습 A0N] ...` 주석 한 줄로만 표시한다.
- 팀에게 넘길 때 `scripts/export_for_team.py` 가 이 설명 주석을 지운다.
- **인터넷에 올리지 않는다. 로컬(내 컴퓨터·Docker)에서만 돈다.**

OWASP 번호는 Top 10:2025 기준이되, 정확한 분류는 팀이 진단하며 정한다 — 라벨은 커밋을 묶는 이름일 뿐이다.

## 심은 것

심을 때마다 커밋 이름(`vuln(A0N) ...`)과 함께 아래 표로 올린다.

| 항목 | 커밋 | 어디 | 무엇을 열었나 |
|---|---|---|---|
| A07 | `vuln(A07) 회원가입 — 가입 요청이 보낸 권한 값을 그대로 믿음` | `center/views.py` `signup()` | 가입 요청에 `is_staff` 를 넣어 보내면 직원 권한으로 가입된다. 직원 전용 화면(출결 관리·CSV 내려받기/올리기, 아동 실명)이 열린다 |

### 딸려온 약점 (일부러 심은 건 아니지만 알아둘 것)

최소 구현을 하다 자연히 생긴 약점이다. 목록의 "심은 것"처럼 의도한 건 아니지만, 내 머릿속에만 두지
않으려고 적어 둔다. 팀이 실습 중에 덤으로 찾을 수 있다.

- **회원가입 비밀번호 규칙 없음** — `center/views.py` `signup()`. `create_user` 로 계정을 바로 만들어
  `1234` 같은 약한 비밀번호도 가입된다. Django 의 비밀번호 검증(AUTH_PASSWORD_VALIDATORS)은 폼을
  거칠 때만 도는데 이 뷰는 폼을 쓰지 않는다. 실제로 막으려면 가입 시 `validate_password()` 를 부른다.

## 예정 (아직 안 심음 — 합의되면 하나씩 올린다)

아래는 계획이라 백틱 커밋 표기(`vuln(A0N)`)를 쓰지 않는다. 심은 뒤에 위 "심은 것" 표로 옮긴다.

- A01 (IDOR): `center/views.py` 의 `my()` 에서 `guardian=request.user` 범위 제한 제거 — 이미 있는 기능
- A03 (SQLi): `center/views.py` 의 `notice_list` 검색을 원시 SQL 로 교체 — 이미 있는 기능
- A03 (XSS): `center/templatetags/notice_format.py` 의 escape 제거 — 이미 있는 기능
- 게시판·댓글 (저장형 XSS·IDOR·CSRF): vuln 에 새 기능으로 구현
- A01 (SSRF): 외부 임베드 기능을 만든 뒤 URL 검증 생략
