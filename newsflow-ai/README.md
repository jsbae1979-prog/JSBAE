# NewsFlow AI — Windows 11 · Phase 3

공개 RSS 수집·중복 제거·내부 추천 평가를 제공하는 한국어 로컬 웹 대시보드입니다. **운영 대상은 Windows 11 전용**, Python 3.12입니다. FastAPI + HTML/CSS/JavaScript GUI를 유지합니다. Codex Cloud는 개발·자동 테스트용이며 Linux/Ubuntu 배포, Docker, WSL 운영 기능은 제공하지 않습니다.

현재 Phase 3는 RSS 수집, AI 뉴스 분석·대본 초안과 FFmpeg 영상 제작을 제공합니다. 실제 SNS 게시·계정 연결·주기 스케줄러는 제공하지 않습니다.

## Windows 설치와 최초 실행

1. [Python 공식 사이트](https://www.python.org/downloads/windows/)에서 **Python 3.12의 Windows 설치본**을 설치하세요. Python launcher와 `Add python.exe to PATH`를 선택하세요. 3.11·3.13은 이 프로젝트의 지원 버전이 아닙니다.
2. Phase 3 검토 브랜치 `feat/newsflow-phase3`를 받으세요. 아직 main에 병합되지 않았습니다. Git for Windows를 사용한다면:

```powershell
git clone -b feat/newsflow-phase3 https://github.com/jsbae1979-prog/JSBAE.git
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
git switch feat/newsflow-phase3
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
| `videos\` | 이전 단계의 예약 폴더; Phase 3 출력은 outputs/videos 사용 |
| `outputs\videos\` | 완성 MP4 |
| `assets\` | 사용자가 허가한 로컬 이미지 |
| `render-tmp\` | 작업별 임시 이미지·WAV·장면 MP4 |

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

단일 사용자 로컬 도구이며 다중 사용자 인증·실제 조회수/검색량 측정·SNS 게시 기능은 없습니다. Phase 2 AI Studio는 검토용 분석과 대본 초안을 제공합니다. Windows ACL, BAT 실행, 실제 브라우저 POST, 실제 RSS 저장은 별도 실환경 검증 전 PASS로 판단하지 않습니다.

## PR 브랜치 Windows 자동 검증

`.github/workflows/newsflow-windows.yml`은 `feat/newsflow-phase1`의 실행 코드/테스트/CI 도구 변경에만 반응합니다. main에서는 실행하지 않으며 보고서만 변경할 때 다시 실행하지 않습니다. Windows Runner에서 Python 3.12 및 전체 pytest, 실제 run.bat, 기본 데이터 경로, 포트 충돌/중복 실행, 합성 데이터 저장·재시작·조회와 Chromium GUI POST를 검사합니다. 실제 RSS나 실제 API 키는 사용하지 않습니다.

합성 RSS는 기존 앱 팩토리에 Fake Adapter를 주입한 별도 검증 서버에서 사용합니다. 운영 run.bat에 보안 우회·Fake 모드·테스트 HTTP endpoint를 추가하지 않습니다. CI의 Windows 종료는 `taskkill /T /F`를 이용한 프로세스 트리 종료이며 수동 Ctrl+C 검증을 대신하지 않습니다.

Cloud 재현 (CI 브라우저 의존성은 별도):

```bash
.venv/bin/python -m pip install -r tools/requirements-ci.txt
.venv/bin/python tools/ci_validation.py --mode cloud --output validation-output --browser-executable /usr/bin/chromium
```

Windows 재현은 개발·브라우저 의존성과 Playwright Chromium을 설치한 격리된 테스트 PC에서 `python tools/ci_validation.py --mode windows --output validation-output`으로 수행합니다. `%LOCALAPPDATA%\NewsFlowAI`에 기존 DB가 있으면 기존 사용자 데이터 보호를 위해 거부합니다. 일반 PC에서는 README의 수동 Windows 체크리스트를 먼저 사용하세요. 결과: [Cloud/Windows 추가 검증 보고서](docs/reports/phase1a_cloud_windows_validation.md).


## Phase 2 · AI Studio

왼쪽 AI Studio에서 뉴스 1~10개 선택 → 분석 → 30/45/60초 선택 → 대본 생성 → 제목·후킹·요약·장면별 내레이션/자막/소재 수정 → 초안 저장 순서로 사용합니다. 출처 링크와 분석 시점 RSS 근거는 고정 보존되고, 수정 충돌 시 새로고침을 요구합니다. 모든 초안은 **게시 전 사람의 검토·승인 필요** 상태이며 게시 버튼이나 SNS 연동은 없습니다.

기본 Offline 모드는 인터넷·API 키 없이 RSS 내부 점수와 제목 유사도 후보 그룹을 설명하고, 사람이 작성할 편집용 기본 대본을 만듭니다. 실제 AI 작성 결과가 아닙니다. 신뢰도는 미평가, 사실 확인은 미확인이며, 복수 출처는 독립 검증을 의미하지 않습니다. 장면 길이는 계획값으로 실제 음성 길이를 측정한 결과가 아닙니다.

OpenAI는 분석과 대본 생성 각각의 Provider에서 선택할 수 있습니다. 매 실행마다 외부 전송·비용 체크박스 동의가 필요합니다. 선택 기사 제목·RSS 요약(최대 800자/기사)·원문 출처·점수 근거가 고정 HTTPS API에 전송됩니다. 모델·호출 옵션은 대본 생성 폼에서 지정할 수 있습니다. 지원하지 않는 모델/옵션 조합은 오류로 기록되며 자동 재시도하지 않습니다. API 미설정은 Offline 사용을 막지 않습니다.

Windows PowerShell에서 값을 화면에 표시하지 않고 현재 세션에만 키를 설정한 뒤 실행할 수 있습니다:

```powershell
$newsflowKey = Read-Host 'OpenAI API 키' -AsSecureString
$env:NEWSFLOW_AI_API_KEY = [System.Net.NetworkCredential]::new('', $newsflowKey).Password
.
un.bat
Remove-Item Env:NEWSFLOW_AI_API_KEY
```

키를 저장소·.env.example·로그·HTML에 넣지 마세요. .env는 자동 로드되지 않습니다. API 키는 현재 실행 프로세스가 읽는 환경변수만 사용합니다. 외부 응답은 길이/JSON 스키마/출처 ID/비밀값/일부 선정적 문구/긴 요약 복제 여부를 검사하지만, 사실 검증이나 저작권 판정을 자동 보장하지 않습니다. 사람이 원문과 소재 이용 권한을 검토해야 합니다. 실제 AI API 연결은 NOT VERIFIED입니다.

DB revision 0002는 기존 0001에 분석 이력과 초안 테이블만 추가합니다. 기존 기사·출처·점수·세션 키는 유지됩니다. 업데이트 전 서버를 종료하고 데이터 폴더를 백업하세요. 0002로 업데이트한 DB는 Phase 1 코드로 되돌려 운영하지 마세요. 기존 데이터 이전 도구는 0001/0002를 지원합니다.

Phase 2 전용 `.github/workflows/newsflow-phase2-windows.yml`은 `feat/newsflow-phase2` 코드 변경에만 실행됩니다. 기존 Phase 1 PR/워크플로는 보존합니다. Windows BAT/기존 기능에 더해 Chromium에서 AI 분석·대본 생성·수정 POST, 모바일 화면과 재실행 후 초안 보존을 검증합니다. CI는 합성 RSS와 Offline만 사용하며 실제 API 키를 등록하지 않습니다.

[Phase 2 완료 보고서](docs/reports/phase2_report.md). 실제 RSS, 실제 AI API, 사용자 Windows 11 PC 운영 검증은 별도이며 Phase 3 영상 기능은 아래에 설명합니다. Phase 4는 추가 승인 후 시작합니다.

## Phase 3 · Video Studio (Windows 11)

AI Studio의 저장된 초안에서 **이 대본으로 영상 구성**을 선택하거나 Video Studio에서 대본을 선택합니다. 30/45/60초, 음성, 자막 크기(36/48/64px)와 위치를 정하고 장면을 확인한 뒤 검토 체크박스와 **영상 제작 실행**으로 시작합니다. 길이를 바꾸면 장면 비율에 따라 타이밍을 재배정합니다. 음성이 배정 시간보다 길면 실패하며 음성 내용을 잘라내지 않습니다.

FFmpeg/ffprobe를 Windows에 설치해야 합니다. 공식 FFmpeg 다운로드 안내에서 Windows 빌드를 선택하거나 Windows 패키지 관리자를 이용하세요. 예: `winget install --id Gyan.FFmpeg -e`. 설치 도구의 TLS/체크섬 검사를 우회하지 마세요. 설치 후 새 터미널에서 `ffmpeg -version`과 `ffprobe -version`을 확인합니다. libx264와 AAC 인코더가 있는 빌드가 필요합니다. PATH에 없다면 현재 PowerShell 세션에서 절대 경로를 지정할 수 있습니다:

```powershell
$env:NEWSFLOW_FFMPEG = 'C:\Tools\ffmpeg\bin\ffmpeg.exe'
$env:NEWSFLOW_FFPROBE = 'C:\Tools\ffmpeg\bin\ffprobe.exe'
.\run.bat
```

버전·실행 파일 확인은 제작 실행 시 수행합니다. FFmpeg가 없어도 기존 RSS/AI Studio는 사용할 수 있습니다. 실행은 인수 배열과 `shell=False`만 사용하며 사용자 텍스트를 명령이나 FFmpeg 필터로 넣지 않습니다. 한국어 텍스트는 Pillow로 카드에 그려 자막을 영상에 포함합니다. 제목·대표 출처(화면 공간상 최대 3개 후보/2줄)와 미확인 표시를 넣고, 전체 원문 출처는 프로젝트와 GUI에 보존합니다. 장면은 컷으로 전환하며 카메라 애니메이션/클립 영상 합성은 이번 범위에 없습니다.

Windows 기본 한국어 글꼴은 `C:\Windows\Fonts\malgun.ttf`입니다. 없다면 사용이 허용된 한국어 글꼴을 설치하고 `NEWSFLOW_FONT_PATH`로 TTF/TTC/OTF 절대 경로를 지정하세요. 글꼴을 찾지 못하면 오류로 기록하고 완료로 표시하지 않습니다. Windows CI는 Google Fonts의 Noto Sans KR(SIL Open Font License)을 고정 URL·SHA256 검증으로 별도 준비합니다. 폰트 자동 다운로드는 운영 앱에 없습니다. CI 폰트 출처/라이선스: https://github.com/google/fonts/tree/b38c5c93af322c45f633e17ac440ec1e6c94d489/ofl/notosanskr

기본 **Offline · 무음**은 PCM 무음 오디오를 만들고 MP4에 AAC 스트림으로 포함합니다. 실제 발화가 아닙니다. Windows 옵션은 설치된 SAPI/System.Speech 음성을 조회하고 로컬 WAV로 합성합니다. Windows OneCore 음성 전부가 SAPI에서 보이는 것은 아니며 한국어 발음 품질은 실제 PC에서 확인해야 합니다. PowerShell 실행 정책을 앱이 완화하지 않습니다. 오류가 나면 설치된 음성/조직 정책/권한을 확인하고 Offline 모드로 기존 화면을 사용할 수 있습니다. 외부·유료 TTS 호출 구현은 없습니다.

사용이 허용된 로컬 PNG/JPEG를 `%LOCALAPPDATA%\NewsFlowAI\assets`에 직접 복사하면 장면별 목록에서 선택할 수 있습니다. 20MB 및 1600만 픽셀 이하이며 symlink/경로 이동/다른 파일 형식은 거부합니다. 이미지 크기에 맞춰 중앙 자르기를 적용합니다. 소재 이용 권한 체크가 필요합니다. 뉴스 이미지/영상은 다운로드하지 않습니다. 소재 없이 텍스트·배경·도형으로 제작할 수 있습니다.

완성 파일은 `%LOCALAPPDATA%\NewsFlowAI\outputs\videos\video-<고유번호>.mp4`에 저장합니다. 한 번에 한 렌더를 실행하고 임시 파일은 `render-tmp`에 분리합니다. 기존 파일은 덮어쓰지 않습니다. 제작 중 디스크 여유를 확보하세요(최소 약 500MB, 긴 작업/대형 소재는 추가 여유 필요). 작업 이력에서 진행률과 실패 단계/종료 코드를 확인할 수 있습니다. 성공한 실제 MP4만 GUI에서 미리보기·열기·다운로드가 가능합니다. Fake 결과는 시뮬레이션으로 구분하여 미리보기를 막습니다.

프로그램 종료는 진행 중 FFmpeg를 중단하고 미완료 작업을 interrupted로 기록합니다. Windows TTS 호출 중이면 최대 60초 제한시간 내 정리를 기다릴 수 있습니다. 강제 종료 후 재실행해도 미완료 작업을 성공으로 바꾸거나 자동 재실행하지 않습니다. 다음 기동 시 앱 소유 임시 작업 폴더를 정리합니다. 성공 표시 이전에 강제 종료되면 출력 폴더에 불완전/고아 고유 파일이 남을 수 있으며 GUI는 이를 완성 영상으로 제공하지 않습니다. 확인 후 수동 정리할 수 있습니다.

업데이트 전 서버를 종료하고 데이터 폴더를 백업합니다. DB 0003은 기존 기사/대본을 유지하며 영상 프로젝트·장면·트랙·작업 테이블만 추가합니다. 0003 DB를 이전 버전 코드로 운영하지 마세요. 기존 이전 도구는 0001/0002/0003을 지원합니다. 사용자 데이터/영상/소재/임시 파일은 Git에서 제외합니다.

Phase 3 검증:

```powershell
python -m pytest -q -rs
python tools/ci_video_validation.py --output validation-output
```

별도 `newsflow-phase3-windows.yml`은 `feat/newsflow-phase3`에만 실행하며 실제 FFmpeg 짧은 샘플 및 ffprobe, Windows TTS(설치된 음성 있을 때), 전체 회귀, 실제 BAT와 Chromium에서 30초 영상 제작/미리보기/다운로드를 검증합니다. 샘플 생성·코덱 검증은 30/45/60초 콘텐츠의 음성·내용·영상 품질 검수를 대신하지 않습니다. 실제 RSS/AI API, 사용자 Windows 11 PC, 한국어 TTS 발음과 전체 길이 최종 품질은 별도 검증 사항입니다. [Phase 3 보고서](docs/reports/phase3_report.md). Phase 4/SNS 계정 연결·게시·main 병합은 수행하지 않습니다.
