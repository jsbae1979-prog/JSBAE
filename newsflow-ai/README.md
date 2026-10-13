# NewsFlow AI — Phase 1

공개 RSS 뉴스 수집·중복 제거·근거 기반 내부 추천 평가를 제공하는 **로컬 한국어 웹 대시보드**입니다. Python 3.12, FastAPI, Jinja2, SQLite/SQLAlchemy를 사용합니다.

Phase 1에 포함된 화면: **Dashboard / News Explorer / Settings**. AI 분석·대본·영상 제작·SNS 게시·성과 분석·스케줄러는 구현하지 않았으며 Phase 2 승인 전 진행하지 않습니다.

## 시작하기

### Ubuntu 24.04 / Codex Cloud

Python 3.12가 설치되어 있어야 합니다. `JSBAE` 저장소를 clone한 뒤 `newsflow-ai` 하위 폴더에서 실행하세요.

```bash
cd /workspace/JSBAE/newsflow-ai   # 일반 Linux에서는 실제 checkout 경로 사용
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m newsflow.main
```

### Windows 11 · PowerShell

```powershell
cd JSBAE\newsflow-ai
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m newsflow.main
```

GUI: **http://127.0.0.1:8765**. 기본 포트는 8765입니다. 외부에 GUI를 공개하는 바인딩은 Phase 1에서 금지합니다. 기본 설치에 관리자 권한이나 Node.js는 필요하지 않습니다. 첫 실행 시 DB와 세션 키가 `data/`에 생성됩니다.

설정 예시 (`.env.example`는 참고 파일이며 자동으로 로드하지 않습니다):

```bash
export NEWSFLOW_PORT=8766                  # 다른 포트는 명시적 설정이 있을 때만
export NEWSFLOW_DATA_DIR="$PWD/data"       # 비밀키/DB를 담은 로컬 폴더
export NEWSFLOW_REQUEST_TIMEOUT=10         # 첫 DB 초기화 기본값; 이후 GUI 설정 사용
```

PowerShell: `$env:NEWSFLOW_PORT="8766"`. 허용 호스트는 `127.0.0.1`, `localhost`, `::1`입니다. 설정 변경 후 서버를 재시작하세요. 로컬 실행 주소·포트·DB 경로는 Settings에서 확인할 수 있습니다. 타임아웃만 GUI에서 저장할 수 있습니다.

## 사용 흐름

1. Settings에서 출처의 공개 RSS 이용 약관·저작권을 확인합니다. Google News 한국 RSS는 **비활성** 상태로 기본 등록됩니다.
2. RSS를 등록하거나 권한 확인 후 활성화합니다. URL 중복 등록은 차단됩니다.
3. Dashboard에서 **지금 수집하기**를 실행합니다. 부분 실패와 전체 실패를 구분하며 기존 기사를 삭제하지 않습니다.
4. News Explorer에서 검색·카테고리·출처·UTC 발행일 필터를 적용합니다. 추천 점수순/발행시각순 정렬과 페이지 이동을 지원합니다.
5. 기사 상세에서 RSS 요약, 원문 링크, 중복 묶음의 출처, 평가 근거와 미평가 상태를 확인합니다.

RSS 제목·요약만 수집하고 본문은 다운로드하지 않습니다. Google News RSS 링크는 원문으로 연결되는 중계 링크일 수 있으며 그대로 보존합니다. 사용 권한 확인은 운영자의 책임이고 robots.txt는 코드에서 확인합니다. robots 확인 실패, 비허용 경로, 지원하지 않는 요청 간격 정책은 실패로 기록합니다.

## 추천 점수

0~100점 **내부 휴리스틱**입니다. 실제 조회수·검색량·검증된 트렌드 지수가 아닙니다.

| 항목 | 최대 | 평가 근거 |
|---|---:|---|
| 최신성 | 30 | 확인 가능한 타임존 포함 RSS 발행시각; 6/24/48/72시간 이내 30/24/15/6점, 이후 0점 |
| 복수 출처 | 25 | 중복 묶음의 서로 다른 출처명 2개 15점, 3개 이상 25점; 1개는 미평가 |
| 주제 중요도 | 20 | 제목·요약의 재난/지진/전쟁/선거/금리/의료/정책 키워드 |
| 영상 제작 적합성 | 15 | 영상/현장/발사/시연/공연/경기 키워드; 저작권 사용 허가 의미 아님 |
| 국내 관심도 추정 | 10 | 한국/대한민국/서울/부산/국내/국회 키워드 |

근거가 없으면 `value=null`과 이유를 저장합니다. 확인된 항목의 합계만 최종 점수에 반영하고, **평가 가능한 항목의 최대 합계**도 표시합니다. 0점 평가와 미평가는 다릅니다. 발행시각 미확인·미래 시각은 최신성 미평가이며 시각을 추정하지 않습니다. 점수는 마지막 수집 시점 기준입니다.

## 테스트

```bash
python -m pytest -q -rs
python -m ruff check src tests
```

기본 테스트는 XML Fixture와 Fake Adapter만 사용합니다. 테스트 DB는 pytest 임시 디렉터리에 생성되어 개발 DB와 분리됩니다.

**실제 네트워크 테스트 (명시적 Opt-in)**:

```bash
NEWSFLOW_LIVE_TEST=1 python -m pytest -q -rs tests/test_live_rss.py
```

PowerShell: `$env:NEWSFLOW_LIVE_TEST="1"` 후 테스트 실행. 대상 RSS 이용 조건과 네트워크 정책을 확인하세요. 실수로 모든 테스트를 실행할 때 외부 서버에 연결되지 않도록 기본값은 0입니다.

**Cloud 제한:** 현재 검증 머신은 공개 DNS 조회가 실패하고 외부 프록시에서 Google News/API 요청에 403을 반환했습니다. 실제 RSS 수집은 이 환경에서 검증되지 않았습니다. `PublicTransport`는 SSRF 보호를 위해 DNS를 검증해 IP에 직접 연결하므로, 프록시 전용 환경에서는 도메인 허용만으로 문제가 해결된다고 보장하지 않습니다. 공인 DNS·HTTPS 연결을 지원하는 환경이 필요하며, 보호를 우회하는 프록시 fallback은 제공하지 않습니다.

Cloud의 관리 Chromium은 POST에 `Origin: null`을 보내어 CSRF 정책이 정상적으로 차단했습니다. 브라우저에서 화면·GET 검색·모바일 레이아웃은 검증했으나 폼 등록·수집의 실제 브라우저 흐름은 **NOT VERIFIED**입니다. 해당 동작은 TestClient와 실제 서버 HTTP 요청으로 별도 검증했습니다.

## DB와 마이그레이션

시작 시 Alembic의 `0001` 초기 마이그레이션을 실행하고 `alembic_version`에 버전을 저장합니다. 재실행은 기존 데이터를 유지합니다. 마이그레이션 파일은 배포 패키지 안의 `src/newsflow/db/migrations/`에 있습니다. 향후 스키마 변경 시 새 revision을 추가해야 하며 과거 revision을 수정하지 않습니다. 각 출처의 저장 작업은 하나의 트랜잭션이고 실패하면 해당 출처의 작업을 롤백합니다. 출처가 성공한 뒤 다른 출처가 실패해도 성공한 데이터는 남습니다.

백업은 서버를 종료한 뒤 `data/` 전체를 복사하세요. SQLite WAL 사용 중인 DB 파일 하나만 복사하면 데이터가 누락될 수 있습니다. DB를 공유한 여러 로컬 프로세스의 수집은 동일 디렉터리 OS 파일 잠금으로 보호합니다. 프로세스가 비정상 종료되면 잠금은 OS가 해제하며 다음 시작 시 중단 상태를 복구합니다.

## 보안과 한계

- 상태 변경: 서명된 double-submit CSRF 토큰, HttpOnly/SameSite=Strict 쿠키, Origin/Host 검증. 이는 단일 사용자 로컬 도구이며 사용자 로그인/다중 사용자 권한관리는 제공하지 않습니다.
- SSRF: 공개 HTTP(S), 기본 포트만 허용; 사설·예약·멀티캐스트 IP, URL 인증정보·일부 토큰 파라미터 차단. DNS 전체 결과 검사, 실제 연결 IP 고정, 모든 리디렉션 재검증. URL 쿼리에 어떤 비밀값도 넣지 마세요.
- TLS 인증서 검증 유지. RSS 요청에 타임아웃·응답 크기·항목 수·리디렉션 제한 적용. 압축 응답은 지원하지 않습니다.
- SQLAlchemy 바인딩, Jinja HTML escaping, CSP 적용. 오류 로그에는 허용된 메시지 또는 일반화된 메시지만 저장합니다.
- 로컬 DB에 수집 뉴스 제목·RSS 요약·URL이 저장됩니다. 공개 RSS가 개인정보를 포함할 수 있으므로 데이터 디렉터리를 공유하거나 Git에 추가하지 마세요.
- 세션 키는 환경변수 `NEWSFLOW_SECRET_KEY`(32자 이상) 또는 로컬 `data/session.key`에서 관리합니다. POSIX에서는 키 파일 권한 0600. Windows에서는 사용자 전용 디렉터리의 ACL을 유지하세요. 키·DB·`.env`는 Git 제외입니다.
- 카테고리와 중요도는 키워드 기반이며 오분류 가능. 출처 이름 신뢰성, 중복 오탐, 서로 다른 표현으로 쓴 동일 사건 미병합 가능. 대규모 데이터에서는 현재 전체 기사 대상 유사도 비교를 최적화해야 합니다.
- Windows 11 및 Ubuntu 24.04 전용 머신 실증은 NOT VERIFIED. Linux Codex Cloud의 Python 3.12에서 실행/테스트했습니다.

구조와 검증 결과: [architecture](docs/architecture.md), [Phase 1 report](docs/reports/phase1_report.md).
