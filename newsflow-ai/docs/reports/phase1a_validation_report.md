# NewsFlow AI — Phase 1A Windows 전용 검증·보완 보고서

**현재 판정: CONDITIONAL ACCEPTED 유지 / 최종 승인 조건 미충족.** Windows 실행 구조와 자동 검증은 완료했지만 실제 Windows 11의 BAT·브라우저 실행 및 실제 RSS 기사 저장은 **NOT VERIFIED**입니다. main 미병합, Phase 2 미착수 상태를 유지합니다.

검증 환경은 Python 3.12.14의 Linux Codex Cloud입니다. Linux는 개발·테스트 머신일 뿐 운영 배포 대상이 아닙니다. 네트워크 권한·허용 도메인·프록시 설정은 이번 단계에서 변경하지 않았습니다.

## 1. Windows 전용 변경 사항 — PASS (구현·자동 검증)

- 최종 운영 대상을 Windows 11로 문서화하고 README를 Windows 설치/재실행/종료/업데이트 중심으로 재작성했습니다.
- run.bat + stdlib bootstrap으로 Python 3.12 검사, 전용 venv, 필요한 런타임 의존성 설치, 서버 실행, 실패 코드 전달을 구현했습니다.
- Windows 기본 데이터 경로 `%LOCALAPPDATA%\NewsFlowAI`; 소스와 사용자 DB·설정·키·로그를 분리했습니다.
- 로그/향후 콘텐츠/영상 폴더만 준비하며 AI·영상·SNS 기능을 추가하지 않았습니다.
- 기본 주소 127.0.0.1:8765를 유지하고 포트 충돌 시 실패합니다. 자동 포트 탐색·변경을 구현하지 않았습니다.
- Docker, WSL, Linux/Ubuntu 운영 배포, Windows EXE Installer는 미구현입니다.

**Windows 실환경 결과는 이 PASS에 포함하지 않습니다.**

## 2. 생성·수정 파일 — PASS

수정 범위는 `newsflow-ai/` 내부로 제한했습니다. JSBAE의 다른 프로젝트와 저장소 루트 README는 수정하지 않았습니다.

- `newsflow-ai/.env.example`
- `newsflow-ai/.gitattributes`
- `newsflow-ai/.gitignore`
- `newsflow-ai/AGENTS.md`
- `newsflow-ai/README.md`
- `newsflow-ai/docs/reports/phase1a_browser_results.txt`
- `newsflow-ai/docs/reports/phase1a_desktop.png`
- `newsflow-ai/docs/reports/phase1a_mobile.png`
- `newsflow-ai/docs/reports/phase1a_pytest_results.txt`
- `newsflow-ai/docs/reports/phase1a_rss_bbc.json`
- `newsflow-ai/docs/reports/phase1a_rss_google.json`
- `newsflow-ai/docs/windows_validation.md`
- `newsflow-ai/run.bat`
- `newsflow-ai/src/newsflow/config.py`
- `newsflow-ai/src/newsflow/db/session.py`
- `newsflow-ai/src/newsflow/diagnostics.py`
- `newsflow-ai/src/newsflow/gui/routes.py`
- `newsflow-ai/src/newsflow/gui/templates/settings.html`
- `newsflow-ai/src/newsflow/main.py`
- `newsflow-ai/src/newsflow/migrate_data.py`
- `newsflow-ai/src/newsflow/news/collector.py`
- `newsflow-ai/src/newsflow/news/rss_adapter.py`
- `newsflow-ai/src/newsflow/news/service.py`
- `newsflow-ai/src/newsflow/paths.py`
- `newsflow-ai/src/newsflow/runtime.py`
- `newsflow-ai/tests/test_phase1a_security.py`
- `newsflow-ai/tests/test_windows.py`
- `newsflow-ai/tools/windows_launcher.py`
- `newsflow-ai/docs/reports/phase1a_validation_report.md`

## 3. run.bat 구현 결과

| 항목 | 판정 | 근거 |
|---|---|---|
| Python 설치/3.12 지원 확인 | PASS (정적·계약 검사) | py -3.12 우선, python fallback에도 버전 확인 |
| 한글·공백 프로젝트 경로 인수 | PASS (정적/인수 배열) | cd /d "%~dp0", 스크립트 따옴표, Python subprocess list |
| 전용 가상환경·설치 갱신 | PASS (mock 계약 검사) | .venv/Scripts/python.exe, manifest fingerprint, 설치 성공 이후 marker |
| 설치 실패 시 중단 | PASS (mock) | 실패 종료 코드, server 미실행, 성공 marker 미생성 |
| 필요 런타임 패키지 | PASS (구현) | pip -c requirements-dev.lock -e 프로젝트; pytest/ruff는 개발 설치 시 별도 |
| 민감정보 출력 방지 | PASS (자동 테스트) | pip raw stdout/stderr 미기록; 정제된 오류 문구만 로그 |
| 중복 BAT 잠금 | PASS (구현·정적), 실제 동작 NOT VERIFIED | msvcrt byte lock; 실제 Windows 미실행 |
| 서버 기동/종료와 포트 충돌 | PASS (Cloud subprocess/HTTP) | 독점 소켓, 인스턴스/이전 잠금, 실패 코드, 종료 후 포트 해제 |
| Windows SO_EXCLUSIVEADDRUSE | NOT VERIFIED | 코드 구현, 해당 Windows API는 Linux에서 실행 불가 |
| BAT 더블클릭·Ctrl+C·Python launcher | NOT VERIFIED | Windows 11 머신 없음 |

BAT는 CRLF/ASCII로 제공하고 `.gitattributes`에 CRLF를 지정했습니다. 실행 실패 시 안내·pause 후 실패 코드를 반환합니다. 설치 실패를 정상 서버 실행으로 표시하지 않습니다.

## 4. Windows 데이터 저장 경로

**PASS (구현 및 portable 테스트), Windows ACL/실제 드라이브 경로는 NOT VERIFIED.**

기본 `%LOCALAPPDATA%\NewsFlowAI` 하위:

- `newsflow.db`: 기사·provenance·점수·수집 이력·설정(AppSetting)·AuditLog. 기존 DB 설정 모델을 유지해 호환성을 보존했습니다.
- `session.key`: 별도 비밀키 파일; Git 제외.
- `logs/execution.log`: UTC 시작/종료/오류 이벤트, 1 MB 회전 및 3개 백업.
- `logs/launcher.log`: bootstrap의 정제된 실패 안내.
- `content/`, `videos/`: 향후 출력 공간만 생성. Phase 2 기능 없음.

`NEWSFLOW_DATA_DIR`는 명시적 override이며 기본값에서는 소스 폴더에 사용자 데이터를 쓰지 않습니다. 설정과 DB를 새로운 JSON 구조로 이중 저장하지 않고 기존 AppSetting을 유지했습니다. 테스트는 소스·사용자 데이터·실행 로그의 위치 분리와 설정 영속성을 확인합니다.

pathlib를 사용하고 SQLAlchemy URL.create로 특수문자를 URL query로 오인하지 않도록 보완했습니다. 한글/공백/100%/# 경로의 DB 생성, 설정 저장, 재기동을 Cloud 파일시스템에서 테스트했습니다. Alembic 경로의 %는 ConfigParser interpolation 충돌을 피하도록 escape합니다.

### 기존 데이터 이전 — PASS (Cloud 자동 검증)

`python -m newsflow.migrate_data --source .\data`:

- 명시적 실행만 허용. 원본 삭제/대상 덮어쓰기 금지.
- SQLite backup API, integrity_check, revision 0001 확인.
- 기존 기사 3건·점수·provenance·출처·수집 설정·동일 키를 이전한 뒤 새 앱에서 확인.
- SQLite connection을 명시적으로 close하여 Windows에서 임시 DB 파일 핸들이 남지 않도록 보완. close 여부 자동 검사.
- 서버/수집/이전 잠금 확인. 임의 사용자 파일/후속 생성 콘텐츠의 자동 병합은 제공하지 않음.
- BAT는 이전 DB를 발견하면 새 빈 DB를 자동 실행하지 않고 이전 절차를 안내함.

실제 Windows에서 WAL·잠금/권한/파일 삭제 동작은 별도 검증이 필요합니다. 안전한 절차는 README와 [Windows checklist](../windows_validation.md)에 있습니다.

## 5. RSS 실제 연동 결과

실제 수행 명령:

```text
python -m newsflow.diagnostics --url "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko" --timeout 5
python -m newsflow.diagnostics --url "https://feeds.bbci.co.uk/news/rss.xml" --timeout 5
```

| 대상 | DNS | 기존 프록시 robots HEAD 진단 | 실제 RSS/저장 |
|---|---|---|---|
| Google News | FAIL | HTTP 200 (진단 경로만) | NOT VERIFIED, failure_stage=dns |
| BBC 공개 RSS | FAIL | FAIL: CONNECT/HTTPS blocked | NOT VERIFIED, failure_stage=dns |

실제 수집 경로가 실패해 두 진단 명령 모두 종료 코드 1입니다. Google robots HEAD의 200을 실제 RSS 수집·기사 저장 PASS로 간주하지 않았습니다. 각 원본 결과: [Google](phase1a_rss_google.json), [BBC](phase1a_rss_bbc.json).

RSS 전송은 DNS 결과 검증·검증 IP 직접 연결·TLS·robots 검사를 유지합니다. Cloud가 프록시를 제공하더라도 DNS 보호를 생략한 fallback 수집을 구현하지 않았습니다. 고정 Google/BBC 호스트의 기존 프록시 HEAD는 egress 원인 구분에만 사용하며 리디렉션을 거부하고 응답을 RSS 저장에 사용하지 않습니다. 프록시 주소·자격정보를 출력하지 않습니다.

DNS/timeout/HTTPS/HTTP/robots/parse/policy/network ErrorKind를 추가했고 자동 테스트로 DNS·TLS·timeout·parse·robots 구분을 확인했습니다. 실제 TLS/robots 허용/파싱은 DNS 단계 실패로 **NOT VERIFIED**입니다. 네트워크 설정은 승인 없이 변경하지 않았습니다.

실제 통신이 성공한 경우 단일 검증 payload를 재사용해 임시 SQLite DB에 기사·provenance·점수·CollectionRun을 저장하고 기사 수와 성공 상태를 확인하도록 구현했습니다. Fixture로 이 저장 경로가 실행되는 테스트는 PASS이지만 실제 기사 저장 PASS를 대신하지 않습니다.

Windows 재검증 명령은 README에 동일한 `.venv\Scripts\python.exe -m newsflow.diagnostics ...` 형태로 제공합니다. 실제 피드의 이용 조건 확인이 필요합니다.

## 6. GUI 검증 결과

| 항목 | 결과 |
|---|---|
| Dashboard/Explorer/Detail/Settings 렌더링 | PASS (TestClient 및 실제 Cloud Chromium) |
| 검색, 날짜·카테고리·출처·정렬 | PASS (기존 회귀 및 브라우저 GET 검색) |
| 기사 상세/미평가 근거/provenance | PASS (회귀 및 브라우저) |
| RSS 등록, 활성/비활성, 설정 변경 | PASS (TestClient + 실제 HTTP POST) |
| 수동 수집/진행 polling/완료/오류 | PASS (Fake RSS, 실제 HTTP 및 회귀) |
| 데스크톱 1440px/모바일 390px | PASS (실제 Chromium, 4개 화면 가로 넘침 없음) |
| JS pageerror | PASS (0건) |
| CSRF/Origin/입력·HTML escaping | PASS (회귀 및 추가 보안 테스트) |
| 실제 Windows 브라우저 폼 POST | NOT VERIFIED |

### Origin:null 재조사

동일 로컬 서버에서 실제 Cloud Chromium 관찰:

```text
location.origin = http://127.0.0.1:8766
window.origin = http://127.0.0.1:8766
isSecureContext = true
실제 POST 헤더 Origin = null
응답 = 외부 사이트에서 요청할 수 없습니다. (403)
```

브라우저 화면의 origin과 서버로 전달되는 헤더가 다릅니다. Cloud 관리 브라우저/전송 경계의 영향으로 보이나 정확한 내부 원인은 **NOT VERIFIED**입니다. 헤더를 임의 수정하거나 CSRF를 끄거나 null origin 예외를 추가하지 않았습니다. 별도 정상 Origin + 유효 CSRF 요청은 TestClient/실제 HTTP에서 성공하며 null origin은 유효 CSRF와 함께 보내도 거부됩니다.

증거: [browser log](phase1a_browser_results.txt), [desktop](phase1a_desktop.png), [mobile](phase1a_mobile.png). 합성 RSS 데이터 화면입니다. Windows 일반 Chrome/Edge에서 주소를 직접 열어 실제 POST 흐름을 재검증해야 합니다.

## 7. 전체 pytest 결과 — PASS

실제 프로젝트 가상환경에서 실행:

```bash
python -m pytest -q -rs
```

**72 passed / 1 skipped / 1 warning / 0 failed**, 종료 코드 0.

기존 **54개 통과 테스트를 유지**하고 **18개 추가 테스트**를 더했습니다. 원본 [phase1a_pytest_results.txt](phase1a_pytest_results.txt).

- 건너뜀 1: 기존 Opt-in Google RSS 테스트. 실제 재시도는 위 diagnostics로 별도 수행.
- warning 1: 기존 Starlette/httpx TestClient deprecation. 숨기거나 제거해서 결과를 바꾸지 않음.
- 추가: Windows 경로 선택/명시 override, 한글·공백·%/# 데이터 폴더, 소스/DB/로그 분리·설정 재기동, BAT 정적 검사, 설치 실패/성공 marker 갱신, 서버 기동/종료/포트 충돌, 실제 HTTP POST, 기존 데이터/키/기사 이전·덮어쓰기 거부·핸들 close, 로그·비밀값 미노출, null Origin 거부, 오류 단계 구분, 진행/완료 상태, 진단 저장 pipeline.

추가 품질 검사:

- `python -m ruff check src tests tools`: PASS.
- `python -m ruff format --check src tests tools`: PASS.
- `python -m pip check`: PASS.
- `python -m pip wheel --no-deps .`: PASS (Cloud wheel 빌드; Windows wheel 설치는 NOT VERIFIED).
- Git whitespace 검사 및 개인 데이터/키/로그 제외 확인: PASS.

## 8. Windows 실제 실행 검증 여부 — NOT VERIFIED

이 머신은 Windows가 아닙니다. BAT, Python launcher, msvcrt, SO_EXCLUSIVEADDRUSE, Windows 사용자 디렉터리/ACL, 백신·방화벽·프록시 환경, 일반 Windows 브라우저의 POST 및 실제 RSS 성공을 실행했다고 주장하지 않습니다.

[windows_validation.md](../windows_validation.md)에 설치/실패/중복/종료/데이터 이전/GUI/실제 RSS/승인 절차를 작성했습니다. Windows 11 머신에서 체크리스트 결과를 기록해야 합니다.

## 9. 보안 점검 결과

**PASS (자동 검증·코드 확인), Windows 환경 특성은 NOT VERIFIED.**

- SSRF 공인 IP 검사·DNS pinning·모든 리디렉션 재검증 유지.
- TLS 인증서 검증 유지; HTTPS 오류를 별도 분류.
- robots 검사 유지; 공개 RSS 이용 약관 확인 UI 유지.
- 서명 CSRF 토큰·쿠키 일치·Origin/Host 검사·CSP·HTML escaping 유지. null Origin을 허용하지 않음.
- SQLAlchemy 파라미터 바인딩, transaction 및 unique 제약 유지.
- pip 실패/서버 설정 오류에 원문 환경/비밀값/traceback을 출력하지 않고 정제한 안내만 기록. secret sentinel 자동 검증.
- 사용자 데이터 기본 경로를 source 밖으로 분리. 명시적 경로 override에서도 DB/키/프로젝트 루트 로그·content·videos가 Git 추적되지 않게 ignore 보완.
- Windows 개인정보·키 파일 ACL의 실제 검증은 NOT VERIFIED. 데이터 디렉터리를 Git에 추가하거나 공유하면 안 됨.
- 네트워크 설정/권한 변경 없음. 본문 스크래핑·로그인 우회·유료 우회·SNS 게시 없음.
- 외부 침투 테스트/취약점 DB 감사는 수행하지 않았으므로 NOT VERIFIED.

## 10. 기존 Phase 1 기능 회귀 여부 — PASS (오프라인)

54개 기존 통과 테스트를 삭제/건너뜀/완화하지 않고 모두 실행했습니다. RSS/Atom·unknown publication date·dedup·provenance·분류·추천 근거·SQLite transaction/UTC·revision 0001 반복 migration·GUI·수집 잠금·AuditLog·보안이 통과했습니다. DB schema revision 및 점수 로직은 바꾸지 않았습니다.

기존 수집 데이터/설정/키 이전도 테스트했습니다. 실제 외부 RSS·Windows 브라우저 동작은 회귀 PASS 범위 밖입니다.

## 11. 알려진 문제 및 미해결 사항

- **NOT VERIFIED:** Windows 11 실제 BAT/전체 흐름 및 사용자 ACL.
- **NOT VERIFIED:** 실제 RSS 저장 — Cloud 공개 DNS 실패; BBC proxy도 차단.
- **NOT VERIFIED:** Cloud null Origin의 정확한 내부 원인/일반 Windows POST 실증.
- 기존 TestClient warning 1건, heuristic 분류/중복 오탐, 수집 시점 기준 점수, 대규모 DB의 전체 기사 유사도 비교 비용은 유지됩니다.
- Python bootstrap의 pip 출력은 민감정보 보호를 위해 숨깁니다. 실패 시 stage/종료 코드를 확인하고 README에 따라 네트워크·패키지·설치 권한을 점검해야 합니다.
- 이전 도구는 현재 Phase 1 revision 0001과 DB·세션 키만 지원하며 임의 파일·콘텐츠 병합은 하지 않습니다. 원본은 항상 보존합니다.
- Windows Ctrl+C 시 진행 중인 수집 종료 대기와 현지 네트워크 타임아웃은 실환경에서 확인해야 합니다.

## 12. Phase 1 최종 승인 가능 여부

**최종 승인 가능: 아직 NOT VERIFIED. CONDITIONAL ACCEPTED 상태 유지가 적절합니다.**

Windows 실행 구조·문서·회귀 0 failed는 충족했습니다. 하지만 최종 운영 환경인 Windows 11의 run.bat/GUI POST/실제 RSS 저장/종료/데이터 이전 확인이 남았습니다. Windows 체크리스트 결과를 받은 후 사용자가 최종 승인해야 합니다. 승인 없이 main 병합 또는 Phase 2를 진행하지 않습니다.

## 13. Git 커밋 및 PR #1 업데이트

- 저장소 `jsbae1979-prog/JSBAE`, 프로젝트 `newsflow-ai/`, 브랜치 **feat/newsflow-phase1** 유지.
- Phase 1A 구현 커밋: **99673a3a6c6190eb24ed88e236580d10fc5f9863**.
- 이번 보고서/검증 증거는 별도 문서 커밋으로 기록합니다. 최종 문서 SHA는 Git 이력에서 확인합니다.
- 기존 PR: https://github.com/jsbae1979-prog/JSBAE/pull/1 (동일 Draft PR 유지).
- 현재 구현/문서 변경을 기존 브랜치로 업로드하고 PR 제목·설명을 Phase 1/1A Windows 운영 범위와 최종 미검증 사항에 맞게 갱신합니다. 실제 업로드/PR API 확인 결과를 후속 기록에 추가합니다.
- main 병합/Phase 2 작업 없음. 검증용 서버는 종료했습니다.
