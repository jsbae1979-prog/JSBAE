# NewsFlow AI — Phase 1 완료 보고서

**결론:** Phase 1 로컬 구현과 오프라인 테스트를 완료했습니다. 실제 RSS 연동은 환경 접근 제한으로 완료하지 못했습니다. 이후 사용자 지시에 따라 기존 GitHub JSBAE 저장소로 프로젝트를 이전했습니다. 이 항목들을 PASS로 표시하지 않습니다. Phase 2는 시작하지 않았습니다.

## 1. 개발 범위

Python 3.12 기반 공개 RSS 뉴스 수집, 중복 제거, 키워드 카테고리 분류, 근거를 저장하는 내부 추천 점수, SQLite/SQLAlchemy 저장, FastAPI/Jinja2 한국어 GUI, 수동 수집과 설정 관리를 구현했습니다. 현재 프로젝트는 JSBAE 저장소의 `/workspace/JSBAE/newsflow-ai` 하위 폴더입니다. 작업 브랜치는 `feat/newsflow-phase1`, 기준 브랜치는 원격 `main`입니다. 최초 독립 저장소의 이력은 별도로 보존했습니다.

실제 검증 머신: **Codex Cloud / Debian GNU/Linux 13 / Python 3.12.14**. Windows 11과 Ubuntu 24.04에서의 실행은 **NOT VERIFIED**입니다. OS별 README 실행 절차는 제공했으나 해당 OS에서 실행했다는 뜻은 아닙니다.

## 2. 아키텍처

GUI와 서비스/DB/외부 어댑터를 분리했습니다. `main.create_app()`이 설정, 버전 마이그레이션, 세션 팩토리, 수집기를 조합합니다.

`FastAPI routes → CollectionCoordinator → NewsService → Collector → RSSAdapter → PublicTransport/FakeRSSAdapter`

데이터는 SQLAlchemy를 통해 SQLite에 저장하며 WAL, 외래 키, UTC 타입 어댑터를 사용합니다. 출처별 저장 트랜잭션, 별도의 오류 로그 트랜잭션, 백그라운드 수집 및 OS 파일 잠금을 적용했습니다.

요청 구조에 추가된 요소:

- `ArticleMention`: 중복 제거 후에도 다른 출처와 원본 링크를 보존하기 위해 추가.
- `AppSetting`: 수집 설정의 영속성을 위해 추가.
- `detail.html`: 기사 상세정보와 평가 근거 화면.
- `newsflow/db/migrations/`: 배포 wheel에서도 마이그레이션을 읽도록 패키지 내부에 위치.
- `requirements-dev.lock`, 보안 테스트, Atom/RSS fixtures, opt-in 실제 RSS 테스트, 검증 스크린샷.

상세: [architecture.md](../architecture.md).

## 3. 생성·수정 파일

최초 독립 프로젝트로 생성한 파일을 JSBAE의 `newsflow-ai/` 하위 폴더로 이전했습니다. 루트 README에는 프로젝트 안내를 추가했습니다. 아래 목록에 현재 보고서가 포함됩니다.

- `.env.example`
- `.gitignore`
- `AGENTS.md`
- `README.md`
- `docs/architecture.md`
- `docs/reports/dashboard.png`
- `docs/reports/mobile.png`
- `docs/reports/phase1_report.md`
- `docs/reports/pytest_results.txt`
- `pyproject.toml`
- `requirements-dev.lock`
- `src/newsflow/__init__.py`
- `src/newsflow/config.py`
- `src/newsflow/db/__init__.py`
- `src/newsflow/db/migrations/env.py`
- `src/newsflow/db/migrations/versions/0001_initial.py`
- `src/newsflow/db/models.py`
- `src/newsflow/db/session.py`
- `src/newsflow/gui/__init__.py`
- `src/newsflow/gui/routes.py`
- `src/newsflow/gui/templates/base.html`
- `src/newsflow/gui/templates/dashboard.html`
- `src/newsflow/gui/templates/detail.html`
- `src/newsflow/gui/templates/news.html`
- `src/newsflow/gui/templates/settings.html`
- `src/newsflow/main.py`
- `src/newsflow/news/__init__.py`
- `src/newsflow/news/collector.py`
- `src/newsflow/news/dedup.py`
- `src/newsflow/news/ranking.py`
- `src/newsflow/news/rss_adapter.py`
- `src/newsflow/news/service.py`
- `src/newsflow/static/css/app.css`
- `src/newsflow/static/js/app.js`
- `tests/conftest.py`
- `tests/fixtures/atom.xml`
- `tests/fixtures/normal.xml`
- `tests/test_collector.py`
- `tests/test_database.py`
- `tests/test_dedup.py`
- `tests/test_gui.py`
- `tests/test_live_rss.py`
- `tests/test_ranking.py`
- `tests/test_security.py`

## 4. 구현 기능

| 기능 | 구현/검증 결과 |
|---|---|
| RSS/Atom 제목·원문 URL·출처·요약·발행/수집시각 | Fixture 파싱 PASS; 날짜 미확인/타임존 없음은 NULL |
| Google News 및 공개 RSS 어댑터 | 구현; 실제 Google News 연결 실패, 아래 별도 기록 |
| 출처 등록·활성화·비활성화 | TestClient와 실제 HTTP PASS; 공개 RSS 권한 확인 필요 |
| URL 중복/유사 제목 처리 | PASS; DB unique 및 출처 provenance 보존 |
| 자동 카테고리 | 키워드 휴리스틱 PASS; AI 분류 아님 |
| 내부 추천 점수·미평가·근거 | PASS; 0~100점, 미평가 null, assessed_max 별도 |
| 트랜잭션·UTC·마이그레이션 | PASS; 롤백, timezone 검증, 0001 반복 적용 및 wheel 포함 |
| Dashboard | 기사 수·최근 수집·카테고리·최신 기사·TOP 10·실행 이력 구현 |
| News Explorer | 검색·UTC 날짜·카테고리·출처·정렬·페이지 이동·상세·원문 링크 구현 |
| Settings | 출처·요청 타임아웃·로컬 실행 정보·수집 오류 로그 구현 |
| 수동 수집 | PASS; 백그라운드 실행, 상태 polling, 중복 실행 409 |
| 부분 실패·전체 실패·빈 출처·중단 복구 | PASS; 기존 기사 유지 |
| 미래 개발 메뉴 | 개발 예정 문구로 표시, 가짜 실행 버튼 없음 |

## 5. 미구현 기능

AI 기사 분석/대본 생성, 영상 생성·편집, SNS OAuth와 실제 게시, 실제 성과 분석, 자동 스케줄러, 다중 사용자 로그인·권한관리는 Phase 1 밖이며 구현하지 않았습니다.

프록시 전용 환경에서 DNS/IP 검증을 우회하는 RSS 전송, 압축 RSS 응답, robots crawl-delay/request-rate 대기 처리는 제공하지 않습니다. 해당 조건은 실패로 기록합니다. 임의 기사 본문 스크래핑, 로그인·유료 접근 우회는 없습니다.

## 6. 테스트 명령 및 결과

### 필수 오프라인 명령

가상환경을 활성화한 프로젝트 디렉터리에서 실제 실행:

```bash
python -m pytest -q -rs
```

**54 passed, 1 skipped, 1 warning — 실패 0건, 종료 코드 0.**

건너뛴 1건은 `NEWSFLOW_LIVE_TEST=1`일 때만 실행되는 실제 Google News RSS 테스트입니다. 기본 테스트는 외부 RSS 서버를 호출하지 않습니다. 테스트 DB는 pytest 임시 폴더에 생성됩니다. warning 1건은 현재 Starlette의 httpx TestClient 호환성 deprecation이며 숨기지 않았습니다. 원본 출력: [pytest_results.txt](pytest_results.txt).

검증 대상: 정상 RSS/Atom, 비정상 XML/XXE, 날짜 파싱 및 미확인 날짜, 타임아웃, URL·제목 중복, provenance, 점수·미평가, DB 롤백/unique/UTC, GUI 렌더링, 검색·필터, 중복 실행·잠금·중단 복구, 오류 로그, SSRF/리디렉션/DNS 혼합 결과/고정 IP/TLS 호스트명, CSRF/Host/Origin, 입력 검증과 HTML escaping.

추가 실제 실행:

| 명령/작업 | 결과 |
|---|---|
| `python -m ruff check src tests` | PASS |
| `python -m ruff format --check src tests` | PASS |
| `python -m pip check` | PASS |
| `python -m pip wheel --no-deps . -w dist` | PASS; 격리 빌드 사용 |
| 새 venv에서 `pip install -r requirements-dev.lock` + wheel 설치 | PASS |
| 새 venv의 설치된 wheel로 전체 pytest 재실행 | 54 passed, 1 skipped, 1 warning |
| wheel 내 migration/template/CSS 포함 확인 및 새 DB 초기화 | PASS |
| `python -m newsflow.main` 실제 서버 기동 | PASS; 기본 127.0.0.1:8765 |
| 실제 HTTP `/health`, `/`, `/news`, `/settings` | PASS; HTTP 200 |
| 실제 HTTP 등록·수동 수집, Fake RSS | PASS; 3개 신규·1개 출처 성공·실패 0 |
| 최종 코드 CLI 재기동과 기존 DB 마이그레이션 재적용 | PASS; HTTP health 확인 후 정상 종료 |
| `git diff --check`, 로컬 DB/키/venv ignore 확인 | PASS |

최초 wheel 진단에서 `--no-build-isolation`은 venv에 setuptools가 없어 실패했습니다. 표준 격리 빌드로 바꾸어 해결했으며 최종 wheel과 새 venv의 설치/실행을 검증했습니다. 보호나 서명/TLS 검증을 해제하지 않았습니다.

## 7. 실제 RSS 네트워크 테스트

실제로 명시적 opt-in 실행:

```bash
NEWSFLOW_LIVE_TEST=1 python -m pytest -q -rs tests/test_live_rss.py
```

**0 passed, 1 failed, 종료 코드 1.** Google News의 robots.txt 요청 전에 `news.google.com` DNS 조회가 실패했습니다. 별도 진단에서 공개 example.com도 DNS 실패, 플랫폼 프록시를 통한 Google News 요청은 `Tunnel connection failed: 403 Forbidden`을 확인했습니다.

따라서 **실제 RSS 수집 성공: NOT VERIFIED (실행 시도는 FAIL)**입니다. Fixture 기반 결과를 실제 뉴스 수집 성공으로 보고하지 않습니다.

환경 설정 초안에 `news.google.com`과 `api.github.com`을 기존 custom 도메인을 보존하여 추가했고 저장 성공을 확인했습니다. 초안 저장은 런타임 반영·게시가 아닙니다. 환경 설정에서 검토·저장 후 게시가 필요합니다. 공개 DNS/직접 HTTPS 연결 제한은 도메인 허용만으로 해결된다고 보장하지 않습니다. 현재 어댑터는 SSRF 검증을 위해 공인 DNS를 확인하고 IP를 고정해 직접 연결하므로, 프록시만 허용하는 환경은 추가 플랫폼 기능이나 별도 설계 검토가 필요합니다.

## 8. GUI 실제 브라우저 검증

Chromium + Playwright가 실제 실행 중인 로컬 서버에 접속했습니다. Fake Adapter로 수집한 합성 XML 데이터를 이용했습니다.

- **PASS:** Dashboard, News Explorer, Settings, 기사 상세 화면 실제 렌더링.
- **PASS:** 브라우저에서 GET 검색 폼 제출, 1개 결과 및 상세 평가 근거 이동.
- **PASS:** 데스크톱 1440px 화면, 모바일 390px의 4개 화면 가로 넘침 없음, JS pageerror 0건.
- **NOT VERIFIED:** 출처 등록·수집·설정 변경 폼의 실제 브라우저 POST 정상 흐름. Cloud Chromium이 `Origin: null`을 전송해 CSRF 정책이 403으로 차단했습니다. 검사를 완화하거나 헤더를 바꿔 PASS로 처리하지 않았습니다.
- 해당 POST의 백엔드 기능은 TestClient와 실제 HTTP 요청으로 별도 PASS이며, 브라우저 PASS를 대신하지 않습니다.

합성 데이터 화면 증거: [dashboard.png](dashboard.png), [mobile.png](mobile.png). 실제 외부 RSS 데이터 화면이 아닙니다.

## 9. 보안 점검 결과

- URL 정책: HTTP(S)·기본 포트만 허용. 사설/loopback/예약/멀티캐스트 주소, URL 자격정보·특정 비밀 파라미터 차단. DNS 전체 결과에 비공개 IP가 포함되면 거부. TLS 인증서 검증 유지. 검증한 IP로 연결하고 원래 호스트명으로 TLS를 검증. 리디렉션도 재검사. 테스트 PASS.
- robots.txt 확인, RSS 이용 약관 확인 동의, 본문 미수집. 비허용/확인 실패/지원하지 않는 속도 정책이면 수집 중단. 테스트 PASS. 개별 실제 서비스의 이용 허가까지 자동 판정했다는 뜻은 아닙니다.
- CSRF: 서명 cookie + form token, HttpOnly/SameSite=Strict, Origin/Host 확인. 위조·누락·Unicode token 거부 및 크로스 사이트 요청 차단 테스트 PASS.
- GUI는 루프백만 허용. 외부 바인딩 값 거부 PASS. 단일 로컬 사용자 도구이며 로컬 악성 프로세스까지 차단하는 사용자 인증은 아닙니다.
- SQLAlchemy 파라미터 바인딩, 검색 wildcard escaping, Jinja HTML escaping, CSP/보안 헤더. SQL injection형 검색 및 XSS형 출처명 테스트 PASS.
- 오류 로그는 허용된 고정 문구 또는 일반화 메시지를 저장. adapter 예외의 가짜 secret sentinel 미노출 PASS. RSS 원본 데이터 자체에는 공개 개인정보가 포함될 수 있으므로 로컬 DB는 공유하지 않아야 합니다.
- 세션 비밀키는 환경변수 또는 Git 제외 파일에 보관. POSIX 0600 설정. Windows ACL의 실제 검증은 NOT VERIFIED.
- Git 추적 파일에 실제 API 키, OAuth 토큰, 로컬 DB, 세션 키, `.env`를 넣지 않았습니다. 테스트는 합성 데이터만 사용합니다.
- 독립 보안 감사/침투 테스트나 종속성 취약점 DB 검사까지 수행하지는 않았습니다: NOT VERIFIED.

## 10. 알려진 문제·제한

1. Cloud의 공개 DNS/외부 접근 제한으로 실제 RSS 연동이 실패했습니다.
2. Cloud 관리 Chromium의 opaque/null Origin으로 브라우저 POST 흐름은 검증하지 못했습니다. 정책상 거부되며 보안 문제로 예외 허용하지 않았습니다.
3. 새 newsflow-ai 저장소 생성은 앱 권한 부족으로 거절되어, 사용자 요청에 따라 기존 JSBAE 저장소를 사용합니다.
4. 키워드 카테고리·추천 점수·제목 중복은 휴리스틱입니다. 실제 독립 언론 판정, 검색량, 트렌드를 대체하지 않습니다. 오분류/중복 오탐과 미병합 가능.
5. 유사도 비교는 현재 전체 기사 목록을 메모리에 읽으므로 대규모 DB 최적화가 필요합니다.
6. 점수는 마지막 수집 시점 기준으로 저장됩니다. 실시간 노화 재평가 스케줄러는 없습니다.
7. 현재 라이브러리의 TestClient deprecation warning 1건이 있습니다. 테스트는 통과했고 warning은 결과 파일에 보존했습니다.
8. Windows 11/Ubuntu 24.04 전용 검증 및 공유 네트워크 파일시스템 잠금은 미검증입니다.

## 11. Phase 2 진입 전 선행 조건

- 사용자의 명시적 Phase 1 검토·승인. 승인 전 Phase 2를 시작하지 않습니다.
- JSBAE 저장소의 Phase 1 PR을 검토해야 합니다. 비밀 토큰을 채팅이나 Git에 저장하지 않습니다.
- 환경 설정에 저장한 네트워크 도메인 초안을 검토·저장·게시하고 DNS/HTTPS 지원을 확보하여 실제 RSS opt-in 테스트를 다시 수행해야 합니다.
- 목표 Windows 11/Ubuntu 24.04 및 일반 로컬 브라우저에서 실행과 수동 수집 폼을 검증해야 합니다.
- 서비스별 RSS 이용 조건과 향후 AI/영상/게시 서비스 정책·credential 관리 방식을 결정해야 합니다. 이후 단계의 설계 검토 사항이며 현재 코드를 확장하지 않았습니다.

## 12. Git 변경 사항 및 커밋 정보

- 현재 GitHub 저장소: `jsbae1979-prog/JSBAE`.
- 저장소 루트: `/workspace/JSBAE`; 프로젝트 경로: `/workspace/JSBAE/newsflow-ai`.
- 작업 브랜치: `feat/newsflow-phase1`; 기준: 원격 `main`에서 fetch한 HEAD.
- 독립 저장소에서 만든 구현 커밋 `0b0f1de3771047e0ff07bbf2e9a8b840248759ac`과 보고서 커밋 `417987a`의 이력을 `/workspace/shared/newsflow-ai-history.git`에 보존했습니다. 현재 JSBAE에는 일반 하위 프로젝트로 추가하며 중첩 Git 저장소를 두지 않습니다.
- 새 GitHub `newsflow-ai` 생성은 앱의 `createRepository` 권한 부족으로 실패했습니다. 기존 JSBAE를 사용하라는 후속 사용자 지시에 따라 해당 저장소로 이전했습니다.
- 이전 과정에서 기존 개발 DB와 세션 키는 이동·보존했으며 Git에 추가하지 않았습니다. 절대 경로가 들어 있는 venv는 새 경로에서 재생성하고 잠긴 의존성과 editable 패키지를 재설치했습니다.
- 이전 후 필수 테스트 54 passed, 1 skipped, 1 warning (실패 0), Ruff 및 pip check 통과. 새 경로에서 CLI를 실행해 /health, /, /news, /settings 실제 HTTP 200을 확인하고 서버를 종료했습니다. 현재 커밋 및 PR 정보는 이 섹션의 후속 기록과 Git 이력에서 확인합니다.
- Cloud 환경 게시 및 새 task에서의 복원까지 검증한 것은 아닙니다.

Phase 2는 시작하지 않았습니다. 이번 후속 작업 범위는 기존 Phase 1의 저장소 이전·검증·업로드입니다.

### JSBAE 이전 및 GitHub 업로드 결과

- 이전 구현 커밋: `cd4cb5c` (Phase 1 코드와 보고서·루트 안내 추가).
- GitHub `origin/feat/newsflow-phase1` 업로드 성공.
- 검토용 Draft PR: https://github.com/jsbae1979-prog/JSBAE/pull/1
- main 병합은 수행하지 않았습니다. Phase 2는 시작하지 않았습니다.
