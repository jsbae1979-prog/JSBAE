# NewsFlow AI — Phase 1A Cloud / Windows 자동 검증 보고서

**자동 검증 결과: PASS.** Codex Cloud와 실제 Windows GitHub Actions Runner에서 회귀·실행·저장·GUI POST를 검증했습니다. 실제 RSS 저장과 사용자 Windows 11 PC의 수동 운영 검증은 **NOT VERIFIED**입니다. 기존 PR #1 / feat/newsflow-phase1을 유지하고 main은 병합하지 않았습니다. Phase 2도 시작하지 않았습니다.

## 1. 실행 환경과 범위

- 저장소: jsbae1979-prog/JSBAE; 프로젝트: newsflow-ai/.
- Cloud: Linux / Python 3.12; 개발 및 자동 테스트용입니다.
- Windows CI: windows-latest / Python 3.12, 검증 프로세스의 sys.platform=win32 확인.
- CI 검증 코드 SHA: `ee3e8391e81e75aaa5ee87a940ccb1e97821d530`.
- 보고서/README/증거의 후속 커밋은 실행 코드 변경을 포함하지 않습니다. 문서만 변경할 때 새 Windows 실행을 발생시키지 않도록 workflow paths를 제한했습니다.
- 실제 API 키/개인정보/원본 뉴스는 CI에 등록하지 않았습니다. XML Fixture와 합성 데이터만 사용했습니다. 실제 RSS는 Opt-in으로 유지합니다.

## 2. Cloud 테스트 결과

프로젝트 디렉터리에서 실제 실행:

```bash
python -m pytest -q -rs
python tools/ci_validation.py --mode cloud --output /tmp/newsflow-cloud-validation --browser-executable /usr/bin/chromium
```

**73 passed / 1 skipped / 1 warning / 0 failed**, pytest 종료 코드 0. 기존 72개 통과 테스트를 유지하고 Referrer-Policy/CSP 유지 검사 1개를 추가했습니다. 이전 데이터 호환성 테스트도 출처·설정·키뿐 아니라 기사·점수·provenance 3건 이전을 실제 확인하도록 강화했습니다. 1개 skip은 기존 Opt-in 실제 RSS 테스트, warning 1개는 기존 Starlette/httpx deprecation입니다.

| Cloud 검증 | 결과 | 근거 |
|---|---|---|
| FastAPI 실제 서버/health | PASS | 127.0.0.1:8765 실제 HTTP |
| Dashboard/Explorer/Detail/Settings | PASS | 실제 Chromium + 기존 회귀 |
| 실제 HTTP 출처 등록·토글·설정·수집 POST | PASS | CSRF cookie/token와 정상 Origin; 운영 어댑터에서는 활성 출처를 비워 외부 호출 방지 |
| 합성 기사 SQLite 저장·조회 | PASS | 기사/점수/provenance 각 3건 |
| 실제 CLI 종료·재기동/데이터·키 유지 | PASS | 종료 후 같은 DB로 재시작·조회·키 byte 비교 |
| 중복 실행·포트 충돌 | PASS | 실패 코드·기존 서버 유지·포트 자동 변경 없음 |
| Chromium 실제 등록·비활성/활성·수동 수집 POST | PASS | 브라우저 생성 Origin=http://127.0.0.1:8765, 각 POST 303 |
| 검색·상세·데스크톱/모바일 | PASS | 우주 검색 1건, 상세 근거, 1440px/390px 4화면 넘침 없음 |
| 합성 RSS 테스트 서버 재기동 | PASS | 3건 데이터 유지 및 기사 HTML 조회 |
| Cloud에서 Windows BAT 실행 | NOT VERIFIED | 실제 BAT 검증은 아래 Windows CI에서 별도 완료 |

Cloud 종료 직후 TIME_WAIT로 재시작하지 못하는 문제를 발견하여 Windows 독점 소켓은 유지하고 Cloud용 소켓에 SO_REUSEADDR를 적용했습니다. SO_REUSEPORT 또는 활성 서버와 포트를 공유하는 옵션은 사용하지 않았습니다. 실제 재기동·충돌 검증이 통과했습니다.

증거: [pytest](cloud_windows_evidence/cloud_pytest.txt), [JSON](cloud_windows_evidence/cloud_result.json), [desktop](cloud_windows_evidence/cloud_dashboard.png), [mobile](cloud_windows_evidence/cloud_mobile.png).

## 3. GitHub Actions Windows 테스트 결과

워크플로: `.github/workflows/newsflow-windows.yml`.

- push 대상은 **feat/newsflow-phase1**만 허용하고 job에도 정확한 ref 조건을 적용했습니다.
- windows-latest, Python 3.12, contents:read, checkout credential 미보존.
- 전체 pytest, Playwright Chromium 설치, 실제 run.bat/Windows 기본 경로/서버/DB/브라우저 테스트.
- 실제 RSS는 NEWSFLOW_LIVE_TEST=0; API 키 등록 없음.
- 합성 결과 JSON/JUnit/스크린샷만 artifact로 업로드하며 DB/session.key는 업로드하지 않습니다.
- 실패 테스트에 continue-on-error를 적용하거나 assertion을 건너뛰지 않았습니다.
- main 실행/병합, 비용·Actions 허용 설정 변경 없음.

### 최종 실행 — PASS

[Windows Actions run 38391824959](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38391824959)

- 상태 completed, **conclusion=success**.
- 모든 실행 단계 success: 설치, 회귀, BAT/데이터/브라우저, artifact 업로드.
- JUnit 집계 **74 tests / 73 passed / 1 skipped / 0 failures / 0 errors**.
- Windows pytest의 정확한 warning 수는 전체 로그 다운로드 제한 때문에 **NOT VERIFIED**입니다. 이를 Cloud의 1 warning과 동일하다고 추정하지 않았습니다.
- 구조화된 GitHub check annotation에서 실제 검증 결과를 읽어 [windows_result.json](cloud_windows_evidence/windows_result.json)에 보존했습니다.

### 앞선 실패 이력 — FAIL을 보존

| 실행 | 코드 | 결과 | 진단 |
|---|---|---|---|
| [38387985355](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38387985355) | 130ef63 | FAIL | pytest 단계 통과, GUI 포함 통합 단계 실패 |
| [38389150581](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38389150581) | 090321c | FAIL | BAT·경로·DB·재시작 통과, GUI 실패로 범위 축소 |
| [38389987176](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38389987176) | 1cd745c | FAIL | 브라우저 POST 403, Origin:null 재현 |
| [38391824959](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38391824959) | ee3e839 | PASS | 폼 제출 수정 후 동일 검증 전체 통과 |

실패를 skip/PASS로 바꾸지 않았습니다. 진단 checkpoint 추가와 원인에 대한 실제 수정 이후 재실행했습니다. Windows 실행 자체는 권한/비용으로 막히지 않았습니다. Actions 관리자 설정 조회는 403이었으므로 설정은 읽거나 변경하지 않았습니다. 로그/Artifact의 외부 저장소 다운로드는 Cloud 네트워크 정책에 차단되어, 허용된 GitHub check API의 정제된 annotation과 run/job 결론으로 결과를 확인했습니다. 네트워크 허용 목록을 변경하지 않았습니다.

## 4. run.bat 실제 실행 여부 — PASS (Windows CI)

실제 cmd.exe에서 프로젝트 run.bat를 실행했습니다. mock이나 Linux에서 BAT를 실행한 것으로 대체하지 않았습니다.

- Python 3.12 확인, 새 `.venv/Scripts/python.exe` 생성과 실제 설치 성공 marker 확인.
- 기본 포트에서 `/health` 응답 `{status:ok, phase:1}` 확인.
- NEWSFLOW_DATA_DIR/PORT/HOST override 없이 **%LOCALAPPDATA%\NewsFlowAI** 실제 DB 경로 확인.
- 등록/설정 변경/수동 수집 POST, 합성 기사 3건의 저장과 재시작 후 조회 확인.
- 동일 BAT 중복 실행과 별도 점유 소켓의 8765 충돌 실패 확인. 기존 서버 유지/자동 포트 변경 없음.
- Windows 종료는 CI 프로세스 트리 `taskkill /T /F`로 수행하고 포트 해제를 확인했습니다.

**사용자 Windows 11의 수동 Ctrl+C 종료는 NOT VERIFIED**이며 CI의 강제 트리 종료를 같은 검증으로 설명하지 않습니다.

운영 run.bat는 PublicRSSAdapter를 그대로 사용합니다. 이 서버에서 외부 호출 없는 POST를 검증하고, 서버가 종료된 뒤 기존 앱 팩토리/Fake Adapter로 합성 데이터를 넣어 재기동을 검증했습니다. GUI 합성 RSS 수집은 별도 Fixture 서버에서 같은 앱·라우트·보안 코드를 사용했습니다. 운영 CLI에 Fake 모드나 테스트 HTTP endpoint를 추가하지 않았습니다.

## 5. GUI 브라우저 POST — PASS (Cloud 및 Windows CI)

Chromium에서 실제 마우스 클릭과 폼 입력으로 등록, 권한 확인 후 활성화/비활성화, 수동 수집을 실행했습니다. 최종 Windows annotation:

- registration/disable/enable/collection HTTP status 모두 303.
- **브라우저가 자동 생성한 Origin = http://127.0.0.1:8765**.
- 합성 기사 SQLite 3건 저장, 검색 1건, 상세 근거, 모바일 4화면 넘침 없음.
- 브라우저 오류 0건, Fixture 서버 재기동 후 데이터 유지.

### Origin:null 원인 정정 및 수정

이전 Phase 1/1A 보고서에서 Cloud 관리 브라우저/전송 경계의 영향으로 추정했던 설명은 정확하지 않았습니다. 이번 Windows 재현과 문서 확인으로 **앱의 Referrer-Policy:no-referrer와 일반 HTML navigation POST의 상호작용**이 원인임을 확인했습니다.

MDN은 no-referrer가 일반 폼 POST에서 Origin:null을 유발할 수 있지만, cors 모드 fetch POST는 실제 Origin을 전송한다고 설명합니다.

- [MDN Origin](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin)
- [MDN Referrer-Policy: Origin에 미치는 영향](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header)

수정은 POST 폼의 정상 제출을 `fetch(mode:cors, credentials:same-origin)`로 처리하고 서버 redirect 후 같은 Origin으로 이동하도록 한 것입니다. URLSearchParams로 기존 form token을 전달하며 실제 Origin 헤더는 브라우저가 생성합니다. Origin을 직접 설정/덮어쓰거나 테스트 인터셉터로 위조하지 않았습니다.

**Referrer-Policy:no-referrer, CSP, CSRF 서명/쿠키 일치, Origin/Host 검사, SameSite/HttpOnly는 모두 유지했습니다.** 여전히 null/위조 Origin과 잘못된 CSRF는 거부됩니다. 오류는 안전한 고정 문구/role=alert로 표시합니다. JavaScript가 꺼진 경우에는 폼 제출/진행 확인에 JS가 필요하다는 안내를 표시합니다.

과거의 미검증 결과는 당시 실행 사실로 남겨두고 이번 결과로 보완합니다. Root cause를 Cloud 제한으로 계속 분류하지 않습니다.

## 6. 실제 RSS 수집 여부 — NOT VERIFIED

실제 Cloud Opt-in 재시도:

```text
python -m newsflow.diagnostics --url "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko" --timeout 5
python -m newsflow.diagnostics --url "https://feeds.bbci.co.uk/news/rss.xml" --timeout 5
```

| 대상 | DNS | 기존 proxy robots HEAD | RSS 저장 |
|---|---|---|---|
| Google News | FAIL/제한시간 초과 | HTTP 200 (진단만) | NOT VERIFIED, failure_stage=timeout |
| BBC | FAIL/제한시간 초과 | CONNECT/HTTPS blocked | NOT VERIFIED, failure_stage=timeout |

원본 [Google](cloud_windows_evidence/rss_google.json), [BBC](cloud_windows_evidence/rss_bbc.json). 실제 기사 byte 저장 성공은 확인하지 못했습니다. 합성 데이터 3건 저장이나 robots HEAD 200은 실제 RSS 성공을 뜻하지 않습니다.

Windows CI에서도 실제 RSS는 Opt-in skip 상태로 유지했습니다. Windows의 실제 RSS 수집 역시 **NOT VERIFIED**입니다. 사용자 Windows에서 README의 diagnostics 명령으로 재검증해야 합니다. 공인 DNS 검증, IP 고정 연결, TLS 인증서, robots 검사를 생략하지 않았으며 네트워크 정책을 변경하지 않았습니다.

## 7. 보안과 남은 Windows 11 실환경 제약

**자동 보안 회귀 PASS:** CSRF/SSRF/TLS/robots/HTML escape/SQLAlchemy/트랜잭션/중복 실행/민감정보 Git 제외를 유지했습니다. Referrer/CSP 유지 검사까지 추가했습니다. CI에는 실제 API 키를 등록하지 않았고 최소 읽기 권한을 사용합니다. 오류 결과는 정제한 상태·숫자·Origin만 기록하며 토큰/환경변수·DB/키를 artifact/Git에 저장하지 않습니다.

남은 항목:

- 실제 Windows 11 PC의 Python 설치·사용자 폴더 권한/ACL·백신/방화벽·회사 프록시·현지 네트워크: **NOT VERIFIED**.
- 실제 사용자 데스크톱에서 BAT 더블클릭/일반 브라우저 이용/수동 Ctrl+C: **NOT VERIFIED**. CI의 Windows Runner/Headless Chromium 검증 범위와 구분합니다.
- 실제 RSS 기사 수집·저장: **NOT VERIFIED**.
- 기존 Starlette/httpx warning 및 Actions의 Node 20 deprecation warning은 테스트 실패 원인이 아니며 제거한 것처럼 보고하지 않았습니다.
- Cloud에서 외부 Actions 로그/Artifact를 직접 다운로드하는 경로는 제한됩니다. 기록한 결과는 GitHub API의 실제 run/job/annotation에서 확인했습니다. 사용자는 Actions 페이지에서 원본 artifact를 확인할 수 있습니다.

Windows 수동 검증 체크리스트: [windows_validation.md](../windows_validation.md).

## 8. 최종 Phase 1 승인 가능 여부와 Git 상태

**Cloud/Windows 자동 검증 요구사항은 충족했습니다.** 다만 실제 RSS 저장과 Windows 11 PC의 현지 환경 확인이 남아 최종 운영 승인을 대신하지 않습니다. 최종 승인 여부는 사용자가 판단해야 하며 기존 CONDITIONAL ACCEPTED 상태를 자동으로 변경하지 않습니다.

- 기존 브랜치 feat/newsflow-phase1, 기존 [PR #1](https://github.com/jsbae1979-prog/JSBAE/pull/1) 유지.
- 구현: 130ef63 (workflow/실행 검증), 090321c·1cd745c (진단), **ee3e839** (보안을 유지한 폼 수정 및 회귀).
- 이 보고서와 최종 증거/README 정정은 별도 문서 커밋으로 업로드합니다. 문서만 바뀐 commit은 workflow 대상에서 제외하며 검증한 코드 SHA를 위에 명시했습니다.
- 변경 범위는 newsflow-ai/ 및 요청한 단일 .github/workflows/newsflow-windows.yml. JSBAE의 다른 프로젝트는 변경하지 않았습니다.
- main 병합/Phase 2 개발 없음. 검증용 서버는 종료했습니다.
