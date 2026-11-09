# 취약점 삽입 목록 (비공개 — 팀 W8 공개 전까지 이 저장소 밖으로 내보내지 않는다)

`scripts/check_leaks.sh --external` 이 `docs/` 를 막는다. 팀 저장소에는 올리지 않는다.

규칙
- 취약점 하나 = 커밋 하나. 커밋 메시지는 `vuln(A0N): ...` 로 시작한다
- 심은 커밋은 그 항목을 지키던 테스트를 "취약함이 있다"는 테스트로 바꾼다
- `main` 에서 이 커밋을 되돌리면 조치 diff 가 된다 (팀 W9, S2 제안)
- OWASP 번호는 Top 10:2025

| 항목 | 내용 | 커밋 | 상태 |
|---|---|---|---|
| A07 | 로그인·키오스크 시도 제한 제거 (`config/urls.py`, `kiosk()`) | `vuln(A07)` | 심음, 시험 뒤집음 |
| A04 | 비밀번호 해시를 MD5 로 (`config/settings.py` PASSWORD_HASHERS). 솔트 없는 MD5 는 Django 6.1 에서 제거되어 솔트 있는 MD5 사용 | `vuln(A04)` | 심음, 시험 교체 |
| A02 | 기본 관리자 계정 `admin` (시드, 흔한 비밀번호), DEBUG 켜짐(코드 기본값 1, compose 에서도 1) | `vuln(A02)` | 심음, 시험 추가 |
| A01 | 월별 출결 CSV(`/attendance/export/`)의 직원 권한 검사 제거, 주소의 아동 번호를 믿는 `/my/<id>/` 추가(IDOR) | `vuln(A01)` | 심음, 시험 교체 |
| A05 | 공지 검색이 SQL 문장에 검색어를 이어 붙임 (`notice_list()`) | `vuln(A05)` SQL | 심음, 시험 교체 |
| A05 | 공지 본문 서식 필터가 이스케이프를 하지 않음 → 저장형 XSS (`templatetags/notice_format.py`) | `vuln(A05)` XSS | 심음, 시험 교체 |
| A10 | 현황판 POST 의 입력 검증 제거 → 예외가 그대로 터지고 DEBUG 화면에 내부 정보 (`board()`) | `vuln(A10)` | 심음, 시험 교체 |
| A09 | 보안 로그 없음 — main 에도 없어서 따로 심지 않음 | — | 해당 없음 |

> main 에서 합쳐 올 때 `SECURITY_REVIEW.md`(답안지)가 다시 들어오면 `scripts/check_track.py` 가 실패한다. 충돌이 나면 삭제를 유지한다.
