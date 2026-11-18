# Vercel 설정 기록 (2026-11-18)

Vercel 대시보드 설정은 git 밖에 있어서 태그나 커밋으로 복구되지 않는다. 그래서 **무엇을 어떻게 설정했는지**를 여기에 남긴다.
**값(비밀 키 등)은 적지 않는다.** 변수 이름과 쓰임새만 적는다. 값은 Vercel 대시보드에만 있다.

## 되돌아가는 길

| 무엇을 | 어떻게 |
|---|---|
| 코드를 Vercel 파일이 생기기 전으로 | 태그 `pre-vercel`(커밋 `3c82f5a`). 로컬에만 있다(GitHub 로는 안 올림). 이 시점에도 4MB 업로드 한도는 이미 들어 있다 |
| Vercel 프로젝트 | 대시보드 설정이므로 이 문서를 보고 다시 만든다. 지우면 환경변수·배포 기록이 같이 사라진다 |
| `db.sqlite3`, `media/` | git 에 없다. 따로 복사해 둔다 |

## 프로젝트 설정 (화면에서 본 것)

| 항목 | 값 |
|---|---|
| 프로젝트 이름 | `jiacenter-web` (주소 `jiacenter-web.vercel.app`) |
| 저장소·브랜치 | `howl213/jiacenter-web`, `main` (병합되면 자동 배포) |
| Root Directory | `src` |
| Framework | Django (자동 인식) |
| Build Command | 대시보드는 `None` 이고 `src/vercel.json` 의 `python build.py` 를 따른다 |
| Install Command | `pip install -r requirements.txt` (기본값) |
| 요금제 | Hobby |
| 시스템 환경변수 | "Enable access to System Environment Variables" 체크됨 (`VERCEL=1` 이 런타임에 들어옴, 공식 문서) |

빌드 때 `src/build.py` 가 `migrate` 와 `seed_dummy` 를 돌려 빈 SQLite 와 모의 값을 만든다. 정적 파일은 `STATIC_ROOT` 가 있어서 Vercel 이 `collectstatic` 을 자동으로 돌린다(공식 문서).

## 환경변수 (이름과 쓰임새만)

| 이름 | 쓰임새 |
|---|---|
| `DJANGO_DEBUG` | `0` — 운영 모드 |
| `DJANGO_SECRET_KEY` | 세션·서명용 비밀 값. **값은 대시보드에만** (저장 후 볼 수 없는 Secret 타입) |
| `DJANGO_ALLOWED_HOSTS` | 접속 허용 주소. `.vercel.app` |
| `DJANGO_BEHIND_PROXY` | `1` — 앞단이 HTTPS 를 처리한다고 알림 (필요 여부는 미확인) |
| `DJANGO_LOG_TO_CONSOLE` | `1` — 로그를 콘솔로. 대시보드에 추가했지만 `VERCEL=1` 로도 켜지므로 반영 여부는 미확인 |

Environments 는 Production 과 Preview 로 나뉜다. 위 변수들이 Production 에만 있는지 Preview 에도 있는지는 변수마다 다를 수 있다(미확인).

## 코드에서 Vercel 때문에 바뀐 곳

| 파일 | 바뀐 것 | Vercel 을 안 쓸 때 |
|---|---|---|
| `src/build.py`, `src/vercel.json` | 새 파일(빌드 때 DB 만들기) | 쓰이지 않음 |
| `src/config/settings.py` | `VERCEL=1` 또는 `DJANGO_LOG_TO_CONSOLE=1` 이면 로그를 콘솔로. `logs/` 폴더도 안 만듦 | 변수가 없으면 기존대로 파일 로그 |
| `src/center/models.py` | 업로드 한도 4MB (Vercel 요청 본문 4.5MB 한도 때문) | **로컬에도 적용된다.** Vercel 을 접으면 다시 올릴 수 있다 |
| `src/config/settings.py` | 센터 기본 이름 `지아지역아동센터` (DB 가 비었을 때) | 로컬에도 적용 |
| `src/deploy/` (Caddyfile, systemd) | 손대지 않음. Vercel 에서는 쓰지 않는다 | 서버를 직접 빌릴 때 쓰는 견본 |

## 알려진 한계 (2026-11-18 기준)

- 실행 환경의 파일 시스템은 읽기 전용이다(실행 로그 `OSError: [Errno 30] Read-only file system`). 로그인·출결 저장이 빈 SQLite 에서 되는지는 **미확인**이고 안 될 가능성이 크다. 실제 운영에는 외부 Postgres 같은 영구 DB 가 필요하다(`확인사항.md` 참고).
- 올린 사진(`media/`)은 남지 않을 수 있다. 모의 값이라 발표 전에 `seed_dummy` 로 다시 채운다.
- 무료 한도, `.vercel.app` 인증서 발급 방식, 직접 산 도메인 연결은 확인하지 않았다.
