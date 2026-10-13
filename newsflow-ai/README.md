# NewsFlow AI — Windows 11 · Phase 1A

공개 RSS 수집·중복 제거·내부 추천 평가를 제공하는 한국어 로컬 웹 대시보드입니다. **운영 대상은 Windows 11 전용**, Python 3.12입니다. FastAPI + HTML/CSS/JavaScript GUI를 유지합니다. Codex Cloud는 개발·자동 테스트용이며 Linux/Ubuntu 배포, Docker, WSL 운영 기능은 제공하지 않습니다.

Phase 1A는 Windows 실행·저장 경로·검증 보완 단계입니다. AI/영상 제작·SNS 게시·스케줄러·Phase 2는 구현하지 않습니다.

## Windows 설치와 최초 실행

1. [Python 공식 사이트](https://www.python.org/downloads/windows/)에서 **Python 3.12의 Windows 설치본**을 설치하세요. Python launcher와 `Add python.exe to PATH`를 선택하세요. 3.11·3.13은 이 프로젝트의 지원 버전이 아닙니다.
2. GitHub PR #1의 `feat/newsflow-phase1` 브랜치를 받으세요. 아직 main에 병합되지 않았습니다. Git for Windows를 사용한다면:

```powershell
git clone -b feat/newsflow-phase1 https://github.com/jsbae1979-prog/JSBAE.git
cd JSBAE\newsflow-ai
.\run.bat
```

Git 없이 ZIP을 받았다면 해당 브랜치 ZIP을 풀고 `newsflow-ai` 폴더의 **run.bat를 더블클릭**하세요. 사용자에게 쓰기 권한이 있는 폴더를 사용하세요. 관리자 권한 실행은 필요하지 않습니다.

3. 첫 실행은 Python 3.12를 확인하고 프로젝트 `.venv`를 만든 뒤 필요한 런타임 패키지를 설치합니다. 설치 실패 시 서버를 실행하지 않으며 오류를 표시합니다. 처음에는 패키지 다운로드 인터넷 연결이 필요합니다. 로그에 pip 원문 출력이나 자격정보를 저장하지 않습니다.
4. 서버 실행 후 브라우저에서 **http://127.0.0.1:8765**를 직접 여세요. 기본 주소·바인딩·포트는 127.0.0.1:8765입니다. 자동 포트 변경이나 외부 공개 바인딩은 하지 않습니다.
5. 프로그램 종료: 실행 창에서 **Ctrl+C**. 종료가 끝날 때까지 기다린 후 창을 닫으세요. 강제 종료 시 다음 실행에서 수집 중단 상태를 복구합니다.

Windows EXE Installer는 제공하지 않습니다. `run.bat`의 실제 Windows 실행과 일반 Windows 브라우저 POST는 Cloud에서 **NOT VERIFIED**이며 아래 체크리스트를 사용해 확인해야 합니다.

## 재실행·업데이트

재실행은 같은 `run.bat`를 더블클릭하세요. 설치된 의존성 manifest가 같으면 설치를 반복하지 않으며 의존성 상태를 검사합니다. manifest가 바뀌면 설치 성공 후 갱신합니다. 동일 폴더의 BAT 중복 실행은 잠금으로 막고, 서버는 지정 포트의 소켓을 독점합니다. 다른 프로그램이 포트를 쓰면 오류를 표시하고 포트를 바꾸지 않습니다.

업데이트 전 서버를 종료하고 사용자 데이터 폴더를 백업하세요.

```powershell
# JSBAE 저장소 루트에서
git switch feat/newsflow-phase1
git pull --ff-only
cd newsflow-ai
.\run.bat
```

코드를 로컬 수정했다면 먼저 그 변경을 보존하세요. 작업 폴더를 옮겼거나 다른 Python 버전의 `.venv`가 남았다면 기존 `.venv`를 다른 이름으로 보관한 뒤 run.bat로 재생성하세요. 사용자 데이터 폴더는 지우지 마세요.

## 사용자 데이터와 설정

기본 저장 위치는 **`%LOCALAPPDATA%\NewsFlowAI`**입니다. 보통 `C:\Users\사용자\AppData\Local\NewsFlowAI`이며 프로젝트 소스 폴더와 분리됩니다. 탐색기 주소창에 `%LOCALAPPDATA%\NewsFlowAI`를 입력하면 열립니다. 한글·공백 경로는 pathlib와 인수 배열을 사용해 처리합니다.

| 위치 | 용도 |
|---|---|
| `newsflow.db` 및 SQLite WAL/SHM | 기사·출처·수집 설정·점수·수집 이력·오류 로그 |
| `session.key` | 로컬 CSRF 서명 키, 내용 공유 금지 |
| `logs\execution.log` | 시작·종료·설정/포트 오류 이벤트, UTC, 순환 로그 |
| `logs\launcher.log` | BAT bootstrap의 정제된 오류 안내 |
| `content\` | 향후 생성 콘텐츠 보관 공간만 준비; 생성 기능 없음 |
| `videos\` | 향후 영상 출력 공간만 준비; 제작 기능 없음 |

RSS 설정은 SQLite에 저장하고 환경변수는 실행 전에 설정합니다. `.env.example`는 참고용이며 자동으로 읽지 않습니다. API/OAuth 키는 이 단계에 필요하지 않습니다. GUI Settings에서 요청 타임아웃을 저장하고 데이터 폴더/로그 위치를 확인할 수 있습니다.

기본 포트 외 사용은 **명시적으로** 설정할 때만 허용합니다. 외부 바인딩은 거부합니다.

```powershell
$env:NEWSFLOW_PORT="8766"               # 생략하면 항상 8765
$env:NEWSFLOW_DATA_DIR="D:\내 자료\NewsFlowAI" # 생략하면 LOCALAPPDATA
.\run.bat
```

기본값으로 복귀: `Remove-Item Env:NEWSFLOW_PORT`, `Remove-Item Env:NEWSFLOW_DATA_DIR` 후 재실행. 비밀키를 환경변수로 지정하려면 `NEWSFLOW_SECRET_KEY` 32자 이상을 안전하게 관리하세요. 값을 채팅·Git·로그에 넣지 마세요.

## 기존 Phase 1 데이터 이전

기존 `newsflow-ai\data\newsflow.db`가 있는데 새 사용자 DB가 없으면 BAT는 초기 빈 DB를 자동 실행하지 않고 이전을 안내합니다. 새 폴더가 생겼더라도 로그/빈 보관 폴더만 생성됩니다.

1. 모든 기존 서버를 종료합니다. **이전 전 기존 data 전체를 별도 백업**하세요. WAL 사용 중인 DB 파일 하나만 복사하지 마세요.
2. run.bat가 의존성을 설치한 뒤 이전 안내로 종료했다면, 프로젝트 폴더에서:

```powershell
.\.venv\Scripts\python.exe -m newsflow.migrate_data --source ".\data"
# 별도 목표 경로를 지정할 경우:
.\.venv\Scripts\python.exe -m newsflow.migrate_data --source ".\data" --target "D:\내 자료\NewsFlowAI"
```

3. 이전 명령은 SQLite backup API로 WAL을 포함한 일관된 DB snapshot을 만들고 무결성·스키마 버전을 확인합니다. DB 안의 설정과 session.key를 복사하며 원본을 삭제하지 않습니다. 대상에 기존 DB나 키가 있으면 덮어쓰지 않습니다. 파일/서버/수집 잠금도 확인합니다.
4. run.bat를 다시 실행해 기사·출처·설정 보존을 확인한 뒤 원본을 계속 백업으로 보관하세요. 이전 도구는 현재 revision 0001만 지원합니다. 임의 추가 파일·향후 콘텐츠·영상은 별도 백업해야 합니다.
5. 이미 새 DB를 만들었다면 자동 병합하지 않습니다. 두 데이터 폴더를 백업한 뒤 보존할 DB를 선택하세요. 기존 경로를 계속 쓰려면 `NEWSFLOW_DATA_DIR`를 명시할 수 있습니다.

## 사용 흐름

1. Settings에서 공개 RSS의 약관·저작권을 확인하고 출처를 등록/활성화하세요. Google News 한국 RSS는 기본 비활성 상태입니다.
2. Dashboard의 지금 수집하기를 실행하세요. 진행 상태, 전체 성공·부분 실패·전체 실패·빈 출처를 구분합니다. 실패해도 기존 기사는 유지됩니다.
3. News Explorer에서 검색, UTC 발행일·카테고리·출처 필터, 점수/발행시각 정렬을 사용하세요.
4. News Detail에서 RSS 요약·원문 링크·provenance·평가 근거와 미평가 상태를 확인하세요.

본문 스크래핑은 하지 않습니다. RSS 링크는 그대로 보존하며 Google News는 중계 링크일 수 있습니다. robots 확인 실패·허용하지 않는 경로·지원하지 않는 요청 간격 정책은 오류로 처리합니다.

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

## 오류 해결과 로그 확인

| 문제 | 확인할 내용 |
|---|---|
| Python 3.12 오류 | `py -3.12 --version`; Python launcher/PATH와 3.12 설치 확인 |
| 패키지 설치 실패 | 인터넷·회사 프록시·패키지 저장소·설치 폴더 권한 확인; 성공 전 서버 실행 없음 |
| 가상환경 버전 오류 | 서버 종료 후 `.venv`를 보관용 이름으로 바꾸고 run.bat 재실행 |
| 중복 실행/포트 사용 중 | 기존 실행 창 종료; `netstat -ano | findstr :8765`로 확인. 모르는 프로세스를 임의 종료하지 말 것 |
| 저장 경로 오류 | LOCALAPPDATA 및 사용자 폴더 권한 확인. 로그 폴더도 기록 불가능하면 콘솔 안내 확인 |
| GUI 접속 실패 | 실행 창 오류, 127.0.0.1:8765, 명시적 포트 설정, 로컬 방화벽 확인. 브라우저 주소 직접 입력 |
| RSS 실패 | Settings의 수집 오류 로그와 아래 diagnostics 결과 확인. DNS/TLS/robots/파싱을 구분 |
| CSRF 403 | 주소를 직접 열고 새로고침. iframe/외부 페이지에서 제출하지 말 것. Origin:null은 허용하지 않음 |

로그 파일은 탐색기로 `%LOCALAPPDATA%\NewsFlowAI\logs`에서 확인하세요. 오류 상세가 정제되어 원문 예외·환경변수·인증정보는 기록하지 않습니다. 공유 전 로그에 사용자 정보가 없는지 확인하세요. 수집 오류는 GUI Settings 및 DB AuditLog에 기록합니다. 실행 로그는 UTC 시각을 사용합니다.

## 실제 RSS 재검증 — Windows Opt-in

사용자 DB를 변경하지 않는 임시 DB에 실제 수집 payload를 저장하여 확인합니다. 연결·DNS·TLS·robots·파싱 실패 시 종료 코드 1과 NOT VERIFIED를 출력합니다. TLS/DNS/SSRF/robots 검사를 우회하지 않습니다. 기존 HTTPS_PROXY가 있을 때 진단용 robots HEAD는 고정된 Google/BBC 호스트만 대상으로 하며 RSS 수집 우회에 사용하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m newsflow.diagnostics --url "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
.\.venv\Scripts\python.exe -m newsflow.diagnostics --url "https://feeds.bbci.co.uk/news/rss.xml"
```

진단이 `rss_store: PASS`, `article_count > 0`, `collection_status: success`인 경우에만 실제 기사 저장을 검증한 것입니다. 운영 GUI에서도 활성 RSS의 수집을 재검증하세요. 피드의 이용 조건은 운영자가 확인해야 합니다.

Cloud 재시도 결과: Google DNS 실패/기존 프록시 robots HEAD 200; BBC DNS 실패/프록시 연결 차단. 실제 RSS 저장은 두 출처 모두 **NOT VERIFIED**입니다. 직접 IP 고정 전송은 공개 DNS가 필요한데 이 Cloud에서 제한됩니다. 프록시만으로 검사를 생략해 수집하지 않습니다. 네트워크 설정 변경 없이 진단했으며 필요 변경은 별도 승인 사항입니다.

## 자동 테스트 — 개발 환경

Windows에서 전체 테스트를 실행하려면 개발 의존성을 먼저 설치하세요. run.bat의 런타임 설치는 pytest/ruff를 설치하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m ruff check src tests tools
```

실제 RSS pytest는 별도 Opt-in:

```powershell
$env:NEWSFLOW_LIVE_TEST="1"
.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_live_rss.py
Remove-Item Env:NEWSFLOW_LIVE_TEST
```

기본 suite는 Fixture/Fake Adapter를 사용해 외부 RSS에 의존하지 않으며 테스트 DB는 임시 폴더입니다. Linux Codex에서 개발 검증 시 `python -m venv .venv`, `.venv/bin/python -m pip install -r requirements-dev.lock`, `.venv/bin/python -m pip install --no-deps -e .`, `.venv/bin/python -m pytest -q -rs`를 사용합니다. 이는 운영 Linux 지원을 뜻하지 않습니다.

Windows 실환경 승인 체크리스트: [windows_validation.md](docs/windows_validation.md). Phase 1A 결과: [phase1a_validation_report.md](docs/reports/phase1a_validation_report.md). 역사적 Phase 1 결과: [phase1_report.md](docs/reports/phase1_report.md).

## 보안·범위

SQLAlchemy 바인딩, Jinja escaping, CSP, signed double-submit CSRF/Origin/Host 확인을 유지합니다. 사설·예약·멀티캐스트 IP, URL 인증정보를 차단하며 DNS 결과 전체 검사 및 고정 IP 연결·TLS 호스트명 검증·리디렉션 재검증을 유지합니다. 로그에 비밀값을 출력하지 않고 DB/키/.env/venv는 Git에서 제외합니다. 공개 RSS 자체에 개인정보가 포함될 수 있어 데이터 폴더를 Git에 추가하지 마세요.

단일 사용자 로컬 도구이며 다중 사용자 인증·실제 조회수/검색량·AI/영상/게시 기능은 없습니다. Windows ACL, BAT 실행, 실제 브라우저 POST, 실제 RSS 저장은 별도 실환경 검증 전 PASS로 판단하지 않습니다.

## PR 브랜치 Windows 자동 검증

`.github/workflows/newsflow-windows.yml`은 `feat/newsflow-phase1`의 실행 코드/테스트/CI 도구 변경에만 반응합니다. main에서는 실행하지 않으며 보고서만 변경할 때 다시 실행하지 않습니다. Windows Runner에서 Python 3.12 및 전체 pytest, 실제 run.bat, 기본 데이터 경로, 포트 충돌/중복 실행, 합성 데이터 저장·재시작·조회와 Chromium GUI POST를 검사합니다. 실제 RSS나 실제 API 키는 사용하지 않습니다.

합성 RSS는 기존 앱 팩토리에 Fake Adapter를 주입한 별도 검증 서버에서 사용합니다. 운영 run.bat에 보안 우회·Fake 모드·테스트 HTTP endpoint를 추가하지 않습니다. CI의 Windows 종료는 `taskkill /T /F`를 이용한 프로세스 트리 종료이며 수동 Ctrl+C 검증을 대신하지 않습니다.

Cloud 재현 (CI 브라우저 의존성은 별도):

```bash
.venv/bin/python -m pip install -r tools/requirements-ci.txt
.venv/bin/python tools/ci_validation.py --mode cloud --output validation-output --browser-executable /usr/bin/chromium
```

Windows 재현은 개발·브라우저 의존성과 Playwright Chromium을 설치한 격리된 테스트 PC에서 `python tools/ci_validation.py --mode windows --output validation-output`으로 수행합니다. `%LOCALAPPDATA%\NewsFlowAI`에 기존 DB가 있으면 기존 사용자 데이터 보호를 위해 거부합니다. 일반 PC에서는 README의 수동 Windows 체크리스트를 먼저 사용하세요. 결과: [Cloud/Windows 추가 검증 보고서](docs/reports/phase1a_cloud_windows_validation.md).
