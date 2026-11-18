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
| 저장소 | `howl213/jiacenter-web` |
| Production Branch | `main` (Settings → Environments → Production → Branch Tracking, "Branch is `main`"). `main` 에 새 커밋이 들어오면 Production Deployment 가 생긴다 |
| Ignored Build Step | **Automatic** (Settings → Build and Deployment). 이미 배포한 적 있는 SHA 의 커밋만 건너뛴다. 직접 만든 skip 명령은 없다. 그래서 문서만 바뀐 PR 을 병합해도 새 SHA 라 빌드와 Production 배포가 돈다 |
| Root Directory | `src` |
| Framework | Django (자동 인식) |
| Build Command | 대시보드는 `None` 이고 `src/vercel.json` 의 `python build.py` 를 따른다 |
| Install Command | `pip install -r requirements.txt` (기본값) |
| 요금제 | Hobby |
| 시스템 환경변수 | "Enable access to System Environment Variables" 체크됨 (`VERCEL=1` 이 런타임에 들어옴, 공식 문서) |

빌드 때 `src/build.py` 가 `migrate` 와 `seed_dummy` 를 돌려 빈 SQLite 와 모의 값을 만든다. 정적 파일은 `STATIC_ROOT` 가 있어서 Vercel 이 `collectstatic` 을 자동으로 돌린다(공식 문서).

## 환경변수 (이름과 쓰임새만, 2026-11-18 대시보드 화면 기준)

| 이름 | 쓰임새 | 적용 환경 |
|---|---|---|
| `DJANGO_DEBUG` | `0` — 운영 모드 | Production · Preview |
| `DJANGO_SECRET_KEY` | 세션·서명용 비밀 값. **값은 대시보드에만** (저장 후 볼 수 없는 Secret 타입) | Production · Preview |
| `DJANGO_ALLOWED_HOSTS` | 접속 허용 주소. `.vercel.app` | Production · Preview |
| `DJANGO_BEHIND_PROXY` | `1` — 앞단이 HTTPS 를 처리한다고 알림 (필요 여부는 미확인) | Production · Preview |
| `DJANGO_LOG_TO_CONSOLE` | `1` — 로그를 콘솔로. `VERCEL=1` 로도 켜지므로 이 변수가 없는 Preview 도 코드상 콘솔 로그가 된다(Preview 로그를 직접 본 것은 아님) | **Production 만** |

- 위 네 개(`DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_BEHIND_PROXY`)는 Secret 표시다. 값은 이 문서에 적지 않는다.
- 확인한 Vercel 환경변수 화면에서는 Development 적용 여부를 확인하지 못했습니다. 실제 적용 여부는 별도 확인이 필요합니다.
- 프로젝트 변수 수가 "20" 으로 표시되는데 Neon 16개 + 위 네 개 = 20 이라, `DJANGO_LOG_TO_CONSOLE` 이 이 수에 안 들어간 이유는 **미확인**이다.

## Neon 연동 (2026-11-18)

| 항목 | 내용 |
|---|---|
| 연동 이름 | `neon-fuchsia-tree` (Neon) |
| 등록된 변수 | 16개, **Preview 전용**, 전부 Secret. 이름: `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `NEON_PROJECT_ID`, `PGDATABASE`, `PGHOST`, `PGHOST_UNPOOLED`, `PGPASSWORD`, `PGUSER`, `POSTGRES_DATABASE`, `POSTGRES_HOST`, `POSTGRES_PASSWORD`, `POSTGRES_PRISMA_URL`, `POSTGRES_URL`, `POSTGRES_URL_NO_SSL`, `POSTGRES_URL_NON_POOLING`, `POSTGRES_USER` |
| Production | Neon 변수가 **없다** |
| 앱에서의 사용 | **아직 안 쓴다.** `src/config/settings.py` 의 `DATABASES` 는 SQLite 로 고정이고 위 변수를 읽는 코드가 없다. PostgreSQL 로 바꾸는 코드는 추후 작업이다 |
| 미확인 | Neon 이 Preview 배포마다 별도 브랜치를 만드는 구성인지, 요금·한도 |

## 주의사항 (Neon 전환 때)

- Preview 와 Production 의 DB 는 분리하는 방향이다. 지금 Neon 변수가 Preview 에만 있는 것은 이 방향과 맞는다.
- Preview 에서 Neon 연결을 먼저 검증한다. Production 은 당분간 기존 SQLite 상태를 유지한다.
- `src/build.py` 가 빌드마다 `migrate` 와 `seed_dummy` 를 돌린다. DB 연결을 바꾸면 이 두 명령이 **빌드 때마다 연결된 DB 에 실행**되므로(PR 하나로 Preview 빌드가 돌아도), 전환할 때 빌드 단계의 DB 변경 동작을 먼저 검토한다.
- 연결 문자열 같은 값은 코드·문서에 적지 않고 Vercel 환경변수(Secret)에만 둔다.

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
