# 작업 지침

지역아동센터 홈페이지. 프로젝트 개요와 실행 방법은 [README.md](README.md) 참고.

---

## 0. 목표 — 모든 작업 전에 이것과 맞는지 본다

이 저장소의 목적은 **둘**이다. 작업을 시작하거나 방향이 바뀔 때마다 "이 일이 어느 목표를 위한 것인가"를 먼저 말하고,
어느 쪽에도 안 맞으면 만들기 전에 사용자에게 묻는다.

| | 목표 ① 안전한 껍데기 (`main`) | 목표 ② 팀 실습용 취약 표면 (`vuln`) |
|---|---|---|
| 무엇 | 지역아동센터 홈페이지를 **실제로 구현**할 때 쓸, 보안상 탄탄한 웹사이트의 껍데기 | 팀 프로젝트(웹 해킹 실습). 사용자가 AI 와 함께 웹을 만들고, 팀원은 OWASP Top 10 에 맞춰 진단·실습한다. 그 실습을 위해 **취약점 표면을 만들어 둔** 사이트 |
| 데이터 | 완성될 때까지 **모의 값만**. 실제 정보로 바꾸는 것은 완성 후 사용자 허락을 받고 한다 | 모의 값만. 로컬 전용 |
| "됐다"의 기준 | 아는 약점은 막고, 모르는 것은 "모른다"고 쓴다. 안전하다고 단정하지 않는다 | 의도해서 심은 것과 심지 않은 것을 구분해 기록한다. 팀이 심지 않은 곳에서 찾으면 `main` 의 결함으로 되돌려 본다 |
| 절대 안 하는 것 | 취약 코드를 들이기, 실제 정보를 코드·문서에 적기 | 취약한 서버를 로컬(내 컴퓨터·Docker) 밖에서 돌리기, 실제 정보, 답안지(`SECURITY_REVIEW.md`) 포함 |

두 갈래는 섞지 않는다 (`scripts/check_track.py` 가 본다). `main` → `vuln` 으로만 합치고, 거꾸로는 안 된다.

**이 문서와 하네스가 있는 이유**: 사용자와 Claude 가 함께 일할 때 (1) 목표에서 벗어나고, (2) 근거 없이 답하고,
(3) 실제로 돌려 보지 않고 "괜찮다/안전하다"고 말하는 것을 막기 위해서다. 아래 4-1 절이 그 장치들이다.

**사람이 정하는 것** — Claude 가 혼자 정하지 않는다. 표의 "훅" 줄은 `scripts/claude_guard.py` 가 실행 전에 먼저 묻고,
`scripts/test_decision_table.py` 가 이 표의 예시 명령이 정말 걸리는지 확인한다(표와 훅이 어긋나면 시험이 실패한다).

| 결정 지점 | 사람이 끼는 방식 | 훅이 묻는 예 / 다른 장치 |
|---|---|---|
| 실제 정보로 전환 | 대화 + 체크리스트 | `docs/확인사항.md`의 "실제 데이터 투입 전 체크리스트". 명령 모양이 없어 훅으로는 못 막는다 |
| 팀에게 코드 넘기기 | 훅 | `python3 scripts/export_for_team.py ~/Desktop/team-export` (올리는 것은 아래 "다른 저장소로 쓰기") |
| 다른 저장소로 쓰기 | 훅 | `git push origin HEAD` · `gh pr create --repo SJH910/Web-Hacking` · `gh repo create howl213/x --private` |
| 로컬 DB 바꾸기 | 훅 | `.venv/bin/python manage.py migrate` · `.venv/bin/python manage.py seed_dummy` · `sqlite3 db.sqlite3` |
| 되돌리기 어려운 git | 훅 | `git push --force origin x` · `git reset --hard HEAD~1` · `git branch -D x` · `git filter-repo --path x` |
| 병합과 main 직접 수정 | 훅 | `gh pr merge 5 --squash` · `git commit -m x` (main 위에서) · `git push origin HEAD:main` |
| 목표·우선순위 바꾸기 | 대화 | 질문을 먼저 한다 (작업 끝 보고의 질문 상자). 훅 없음 |
| 취약판에 어떤 항목을 심을지 | 대화 | 삽입 목록(`docs/vuln-manifest.md`)에 먼저 적고 합의한다. 훅 없음 — 한계 |

"대화" 줄은 Claude 가 지키기로 한 약속일 뿐 기계가 막지 않는다. 그래서 어긋나면 사용자가 바로 말한다.

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
2. **취약한 실습본은 로컬(내 컴퓨터·Docker)에서만 돌린다. 진단·보고서 작업도 그 환경에서 한다.** 인터넷에 열지 않는다. 실제 정보가 들어가면 더 안 된다.
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
- 두 갈래가 섞이지 않게 `scripts/check_track.py` 가 본다 — main 에는 취약판 표시(`[실습 A0N]`, 배너, 삽입 목록)가 없어야 하고, vuln 에는 답안지(`SECURITY_REVIEW.md`)가 없어야 하며, vuln → main PR 은 막는다
- 삽입 목록(`docs/vuln-manifest.md`)의 항목마다 같은 이름의 커밋이 있는지는 `scripts/check_manifest.py` 가 본다
- 팀에게 vuln 코드를 넘길 때는 `scripts/export_for_team.py <새 폴더>` 로 폴더를 만든다(내부 문서·시험·답안지 제외, 심은 곳의 설명 주석 삭제, 검사 통과해야 끝남). 푸시는 사용자 확인 뒤에 직접. 심은 곳의 설명은 반드시 `# [실습 A0N] ...` 주석 줄로만 쓴다
- 팀이 찾은 취약점은 `docs/발견-순환.md` 절차로 처리한다 (의도/비의도 분류 → main 에서 재현 → 시험 먼저 → main 수정 → vuln 에 합치기)
- `/verify`(= `scripts/verify.sh`)가 테스트·마이그레이션·개인정보·갈래 검사를 한 번에 돌린다. 세션 시작 때는 상태를 요약해 주고, 코드를 바꾼 채 끝낼 때는 빠른 점검만 경고로 알린다
- 스크립트들의 테스트: `python -m unittest discover -s scripts`

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
