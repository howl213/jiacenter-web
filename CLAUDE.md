# 작업 지침

지역아동센터 홈페이지. 프로젝트 개요와 실행 방법은 [README.md](README.md) 참고.

---

## 1. 문서를 함께 갱신한다

작업을 끝낼 때마다 [docs/확인사항.md](docs/확인사항.md) 를 확인하고 필요하면 고친다.
갱신 규칙은 [docs/README.md](docs/README.md) 에 있다.

| 상황 | 할 일 |
|---|---|
| 확인 못 한 채 넘어간 것이 생겼다 | `docs/확인사항.md` A~E 중 맞는 칸에 추가 |
| 확인했다 | ☑ 로 바꾸고 **실제 결과**를 적는다 (명령 출력, 응답 코드) |
| 보안에 영향 있는 변경을 했다 | `SECURITY_REVIEW.md` 도 함께 |
| 외부 답변을 받았다 | `docs/외부문의/` 해당 문서에 날짜와 함께 |

---

## 2. 주장에는 근거를 붙인다

**기억에 의존해 단언하지 않는다.** 수치, 버전, 외부 서비스 정책은 확인한 것만 말한다.

| 근거로 쓸 수 있는 것 | 예 |
|---|---|
| 직접 실행한 명령의 출력 | `pip-audit` → `No known vulnerabilities found` |
| API 응답 | `403: Upgrade to GitHub Pro or make this repository public` |
| 설치된 라이브러리 소스 | `django/contrib/auth/views.py:139` → `http_method_names = ["post", "options"]` |
| 공식 문서 | 링크와 함께 |

확인하지 못했으면 **"미확인"이라고 명시한다.** 추측을 사실처럼 적지 않는다.

### 테스트에 대해

`manage.py test` 가 통과했다고 **"괜찮다 / 완벽하다 / 허점 없다"고 말하지 않는다.**
무엇을 검증했고 무엇을 검증하지 않았는지 구분해 보고한다.

나쁜 예: `테스트 통과. 문제없습니다.`
좋은 예: `테스트 11개 통과. 단위 동작만 확인했고, 실제 HTTPS 환경과 동시 접속은 미검증.`

---

## 3. 이 프로젝트에서 절대 하지 않는 것

1. **`db.sqlite3` 커밋** — 아동 실명과 보호자 연락처가 평문으로 들어 있다
2. **실습본을 인터넷에 배포** — 취약한 서버는 제3자 공격의 발판이 된다
3. **추정한 출결 시각을 자동으로 채우기** — 보조금 정산 근거다. 사람이 확인해 입력한다
4. **실습본 브랜치에 `SECURITY_REVIEW.md` 포함** — 답안지다
5. **비밀번호·키를 문서나 코드에 평문으로 적기**

---

## 4. 코드 작성 방침

- 가장 작은 변경으로 끝낸다. 요청하지 않은 기능·옵션·추상화를 넣지 않는다
- 앱을 쪼개지 않는다 (모델 5개 규모)
- 출결 판정은 `center/views.py` 의 `_toggle()` **한 곳에만** 둔다.
  키오스크·현황판 두 입구가 모두 이 함수를 부른다
- 한계가 있는 임시 구현에는 `shortcut: <한계>, <언제 올릴지>` 주석을 남긴다
- 주석은 코드가 말하지 못하는 **왜**만 적는다

---

## 4-1. 하네스 (자동 점검)

- 클론한 뒤 한 번 `git config core.hooksPath .githooks` — 커밋 직전에 `scripts/check_leaks.sh --staged` 가 돈다
- 개인정보·금지 파일 판정은 `scripts/check_leaks.sh` **한 곳에서만** 한다. git 훅, CI, 다른 저장소로 파일을 보낼 때(`--external`)가 모두 이 스크립트를 부른다
- Claude 의 위험 명령(타 저장소 쓰기, 강제 푸시, 실제 DB 마이그레이션, `--no-verify`)은 `scripts/claude_guard.py` 가 `.claude/settings.json` 훅으로 막거나 묻는다
- 두 스크립트의 테스트: `python -m unittest discover -s scripts`

---

## 5. 작업 흐름

```bash
git switch -c feat/기능-이름      # feat / fix / security / docs
# 작업
.venv/bin/python manage.py test
gh pr create                      # Squash merge
```

PR 본문의 **"확인하지 않은 것"** 칸을 비우지 않는다. 없으면 "없음"이라고 쓴다.
거기 적은 것 중 다음 작업까지 남는 것은 `docs/확인사항.md` 로 옮긴다.

> main 브랜치 보호 규칙은 없다. GitHub Free 플랜의 프라이빗 레포에서는 쓸 수 없다
> (실제 API 응답으로 확인). 규칙이 막아주지 않으므로 PR 은 스스로 거친다.
