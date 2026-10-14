# NewsFlow AI — Phase 4B-2B 완료 보고서

확인일: 2026-10-14. 범위는 운영 OAuth 기반 코드와 합성 검증입니다. 실제 Google/Instagram 로그인·서비스 토큰 교환·발급·저장·조회·Identity API·SNS 업로드/게시를 실행하지 않았습니다. 실제 서비스는 **OFFLINE/BLOCKED**이며 환경변수와 GUI 승인 값으로 활성화되지 않습니다.

## 결과와 승인 범위

| 항목 | 판정 | 근거 / 한계 |
| --- | --- | --- |
| Callback·YouTube channel Identity·별도 운영 Vault·회복 구조 | PASS | 합성 HTTP·암호화·DB 테스트; 실제 서비스 성공이 아님 |
| Cloud 전체 회귀 | PASS | **824 passed / 6 skipped / 1 warning / 0 failed**, 총 830개 |
| 기존 회귀 보존 | PASS | 기존 515개 + 신규 315개; 기존 단계/스키마 기대값만 갱신 |
| Cloud 실제 FastAPI·Chromium GUI | PASS | 실제 서버·Chromium POST·SQLite 재실행·영상 미리보기·차단 확인 |
| Windows Actions 전체 회귀 | PASS | **829 passed / 1 skipped / 0 failed**, 총 830개 |
| Windows native DPAPI·BAT·Chrome | PASS | 합성 DPAPI·다른 사용자 거부·실제 BAT·Chrome POST |
| 실제 OAuth·서비스 토큰·SNS 호출 | PASS | 해당 실행 **0건**; 차단 동작과 합성 경로의 증거를 아래 구분 |
| Instagram 최신 로그인별 정책 | NOT VERIFIED | 확인되지 않은 흐름은 BLOCKED |
| 사용자 Windows 11 PC 운영 | NOT VERIFIED | Actions runner와 사용자 PC는 별도 환경 |
| Phase 4B-2C 진입 | NOT VERIFIED | 추가 사용자 승인 및 아래 선행 조건 필요; 착수하지 않음 |

**개발 기준 승인 검토가 가능한 상태**입니다. 실계정 운영 승인은 포함하지 않습니다. 본 보고서의 PASS는 명시된 코드·합성 검증 범위에 한정됩니다. Cloud native Windows 검증을 PASS로 보고하지 않으며 Fake 인증 성공을 실제 OAuth 성공으로 기록하지 않습니다.

## 구현 범위와 아키텍처

### Loopback callback

GUI는 **127.0.0.1:8765**를 유지합니다. 새 OAuth listener는 **127.0.0.1:0**으로 먼저 bind하고 실제 배정된 포트를 authorization/callback/exchange의 정확한 URI에 고정합니다. 8765를 callback 포트로 사용하거나 점유된 명시적 포트를 자동 변경하지 않습니다. Windows `SO_EXCLUSIVEADDRUSE`와 주소 재사용 금지를 적용했습니다.

state·S256·URI·Host·peer·Origin·만료·일회성 소비·취소·timeout·포트 충돌·요청 크기 제한을 검사합니다. 틀린 state/Host/Origin이 정상 pending 세션을 소진하지 않게 했으며, 인증된 callback의 잘못된 code와 취소·오류는 일회성으로 처리합니다. callback receipt의 계정·URI·scope·code·verifier·만료를 HMAC으로 봉인해 필드 교체 공격을 거부합니다. 응답은 고정 문구이며 code/state/verifier를 HTML·DB·로그에 반사하지 않습니다.

실제 Google OAuth에는 연결하지 않습니다. production 시작은 소켓 bind 전에 차단됩니다. 숫자 IPv4 loopback의 합성 HTTP와 별도 프로세스의 포트 점유 시도를 테스트했습니다.

### YouTube Identity 권한·바인딩

공식 계약은 `GET https://youtube.googleapis.com/youtube/v3/channels?part=id&mine=true`입니다. `youtube.upload`만으로 Identity 조회가 가능하다고 가정하지 않으며, 별도의 **youtube.readonly** 권한을 명시적으로 구분합니다. 합성 연결 계약에서 두 scope를 모두 검사하는 것은 실제 사용자 동의를 획득한 것이 아닙니다.

로컬 계정·OAuth client·채널 ID·scope·전체 grant fingerprint를 검증하고, DB의 고유 channel binding은 Adapter 재시작 후에도 다른 계정에 같은 채널이 잘못 연결되지 않게 합니다. 채널 변경·scope 축소·401/403·timeout·불명확한 다중 채널 응답은 준비 완료로 전환하지 않습니다. refresh 시작 때 이전 receipt를 무효화하며 진행 중 GET도 무효화된 receipt를 다시 발급할 수 없습니다.

검증하는 Identity는 **YouTube 채널**입니다. Google email/sub 또는 어떤 Google 로그인이 공유 Brand 채널에 접근했는지까지 증명하지 않습니다. 실제 Google 사용자 식별·채널 선택은 후속 정책 검토 및 별도 승인 후 검증해야 합니다.

### Production CredentialVault

기존 `oauth/vault.py`의 synthetic-only DPAPI를 그대로 보존했습니다. 새 `production_dpapi.py`는 별도의 current-user DPAPI 파일 커널과 운영 facade입니다. production facade는 생성 시 credential I/O를 하지 않고 모든 저장·조회·삭제 전에 불변 activation 및 별도 storage 차단을 검사합니다. 환경변수나 GUI 플래그, 공유 gate 하나의 교체만으로 실제 credential 경계에 접근할 수 없습니다.

실제 커널에는 현재 Windows SID, 계정, Identity digest, opaque reference, operation ID, payload schema와 무결성을 묶습니다. 평문 토큰을 DB에 저장하지 않습니다. atomic immutable ciphertext write와 fsync, 다시 읽기 검증, operation/file digest 기반 삭제를 적용합니다. symlink/junction·변조·권한 오류·다른 account/identity 파일은 fail-closed입니다. Windows가 아니면 실제 Vault를 Fake로 자동 대체하지 않습니다.

합성 facade는 NF 형태의 token만 받으며 Cloud에서는 명시적 Fake cipher, Windows에서는 native DPAPI를 사용합니다. 이는 **실제 서비스 토큰을 저장한 검증이 아닙니다**. 같은 Windows 사용자 프로세스의 접근은 DPAPI의 정상 경계이며 다른 프로세스 자체를 막는 저장소라고 주장하지 않습니다.

### CAS·회전·재시작·orphan

새 additive migration **0007**에 identity binding 및 lifecycle operation journal을 추가했습니다. 기존 0001~0006은 변경하지 않았습니다. 새 reference와 operation ownership을 파일 쓰기 전에 DB에 기록하여 write → read-verify → pointer revision CAS → 이전 ciphertext 정리를 분리했습니다.

SQLite와 filesystem은 단일 트랜잭션이 아닙니다. 각 crash 지점에서 journal·실제 file·현재 pointer·revision을 확인하고 미완료를 unknown으로 격리합니다. 현재 사용 중인 pointer나 다른 작업의 파일을 이전 writer가 삭제하지 못하도록 검사합니다. authenticated pending/hardlink와 작업 소유 orphan만 정리하며 변조·소유 불명 파일은 보존합니다. 재시작은 provider를 재호출하거나 결과 불명 상태를 성공으로 바꾸지 않습니다.

만료되거나 process-local receipt를 잃은 재시작에서는 `HistoricalCredential`을 사용할 수 있습니다. durable grant hash·Identity binding·reference·revision과 실제 복호화 결과가 일치할 때만 5분짜리 **REVALIDATION_ONLY** 후보를 반환합니다. 이 후보는 현재 Identity receipt나 연결 준비 승인이 아닙니다. 정확한 client/expected channel을 검사하고 revision을 예약한 명시적 refresh 후 새로운 Identity 검증을 통과해야 새 pointer를 커밋합니다. pending/unknown/error/revoked 상태에서는 이 경로로 재시도하지 않습니다.

### GUI·전체 합성 flow

Publishing Studio와 `/api/oauth/operations-readiness`는 callback/Identity/Vault의 준비 상태와 차단 상태만 표시합니다. 실제 연결 버튼은 비활성 상태이고 기존 CSRF·CSP·SSRF·TLS 정책을 유지합니다.

새 합성 flow는 실제 로컬 HTTP Fake Google authorize redirect → loopback callback → PKCE token exchange → channel Identity → encrypted journal store를 연결합니다. refresh·revoke·재시작·권한 오류·timeout·채널/client/계정 교차 바인딩을 검증합니다. 시스템 로그인 브라우저를 열지 않고 외부 주소로 redirect하지 않습니다. 운영 pipeline factory도 생성하지 않습니다.

## 공식 근거

근거와 확인 범위는 [OAuth 운영 설계](../oauth_operations.md), [공식 자료 목록](phase4b2b_evidence/oauth_official_sources.json), [Cloud 조회 기록](phase4b2b_evidence/cloud_official_docs.json)에 보존했습니다. 확인 날짜는 2026-10-14입니다.

- Google 설치형 OAuth: https://developers.google.com/identity/protocols/oauth2/native-app
- YouTube channels.list: https://developers.google.com/youtube/v3/docs/channels/list
- Microsoft current-user DPAPI: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- Microsoft exclusive socket bind: https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse
- Meta Instagram Login: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
- Meta Facebook Login: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login

최신 공식 GitHub 소스 5건의 commit/blob 일치를 검증했습니다. Google 공식 설치형 flow의 임시 loopback bind 순서와 Windows exclusive bind, YouTube discovery의 허용 scope/endpoint를 확인했습니다. Cloud의 공개 문서 12건은 기존 proxy CONNECT 제한으로 NOT VERIFIED였으며 TLS·proxy·권한을 변경하지 않았습니다. Windows의 새 조회에서 Google/YouTube 6건과 DPAPI 2건은 공식 본문을 확보했습니다. Meta 4건은 허용된 공개 문서 경로 밖 redirect로 NOT VERIFIED입니다. [조회 본문](phase4b2b_evidence/windows_official_docs.json)과 [본문 검토](phase4b2b_evidence/windows_official_review.json)를 별도로 보존하며 로그인/인증 페이지는 따라가지 않았습니다.

Instagram의 로그인별 scope·redirect·PKCE·계정 자격·앱 검수·code exchange·refresh/revoke 조건이 공식 근거로 확정되지 않은 상태에서는 계속 BLOCKED입니다. Google loopback 흐름을 복사하거나 endpoint를 추정하지 않았습니다.

## 테스트와 실제 실행

Cloud 명령:

```text
python -m pytest -q -rs --junitxml=docs/reports/phase4b2b_evidence/cloud_pytest.xml
python -m ruff check src tests tools
python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase4b2b-cloud
```

전체 pytest **824 passed / 6 skipped / 1 warning / 0 failed**, 119.48초입니다. [요약 JSON](phase4b2b_evidence/cloud_test_summary.json), [JUnit](phase4b2b_evidence/cloud_pytest.xml), [실행 출력](phase4b2b_evidence/cloud_pytest.txt)을 제공합니다. Ruff와 `git diff --check`는 PASS입니다. 기존 Starlette/httpx deprecation 경고 1건은 남아 있으며 기능 오류로 감추지 않았습니다.

Cloud skip은 live RSS opt-in 1건과 native Windows 전용 5건입니다. Windows 전용 검증을 생략해서 실패를 숨기는 용도로 사용하지 않았습니다. baseline 515개 케이스를 제거하거나 비활성화하지 않았고 current phase label/schema head 기대값만 4B-2B/0007로 갱신했습니다. [기준 파일 해시](phase4b2b_evidence/baseline.json)의 기존 migrations 및 synthetic-only Vault는 동일합니다.

새 315개 케이스: callback 87, Identity 68, lifecycle 59, 전체 flow 32, GUI 23, production DPAPI 46입니다. 실제 서비스 성공·품질 검증과 합성 프로토콜 성공을 구분합니다.

[Cloud 실제 실행 JSON](phase4b2b_evidence/cloud_runtime_gui.json): 서버 시작·종료, health, 등록/수집 POST, SQLite 3개 기사 저장·재실행, 중복/포트 충돌 거부가 PASS입니다. Chromium에서 Dashboard/검색/상세/모바일 및 AI/Video/Publishing POST를 실행했습니다. 실제 30초 MP4 frame decode도 확인했지만 silent audio 합성 콘텐츠로 사람의 품질 검증은 NOT VERIFIED입니다. OAuth 시작 승인 위조는 **423**, 실제 browser 외부 origin은 **빈 목록**, publishing jobs/attempts는 **0**입니다.

Windows Actions 전용 workflow는 `windows-latest`/Python 3.12로 이 브랜치에서만 실행합니다. 전체 pytest, 기존 DPAPI와 별도 운영 DPAPI 커널, 실제 BAT·서버·health·LOCALAPPDATA·재실행·포트 충돌·Chrome POST, 기존 짧은 FFmpeg/SAPI 회귀를 수행합니다. 실제 서비스 key/secret은 등록하지 않습니다. 실제 RSS는 opt-in을 유지합니다.

최종 [Windows 실행 38545651234](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38545651234)는 전체 job/필수 step **SUCCESS**입니다. [pytest 요약](phase4b2b_evidence/windows_test_summary.json)은 **830 tests / 829 passed / 1 live-RSS skipped / 0 failures / 0 errors**입니다. Windows 경고 수는 이 요약에 포함되지 않아 **NOT VERIFIED**로 구분하며 0이라고 추정하지 않습니다. [실행·step·annotations](phase4b2b_evidence/windows_final_run.json)에 결과를 보존했습니다.

[Windows 실제 실행](phase4b2b_evidence/windows_runtime_gui.json): `run.bat` 시작, health, 서버 종료(taskkill process tree), 기본 LOCALAPPDATA, HTTP/POST, DB 3개 기사 저장·재실행·조회, 중복 및 포트 충돌 거부가 PASS입니다. Chrome의 등록/활성화/수집·AI/Video/Publishing POST·모바일 레이아웃·30초 MP4 frame decode·초안 재시작 보존이 PASS입니다. 위조 OAuth 시작은 **423**, browser 외부 origin은 **[]**, publish jobs/attempts는 **0**입니다. 실제 사용자 PC의 Ctrl+C 수동 종료는 NOT VERIFIED입니다.

[Windows 운영 Vault 검증](phase4b2b_evidence/windows_production_vault.json): 합성 토큰의 current-user DPAPI, 별도 process read, 한글/공백 경로, 계정/Identity 격리, rotation provenance·삭제, 변조 quarantine과 cleanup이 PASS입니다. 별도 disposable Windows 사용자의 **자기 DPAPI encrypt/decrypt 성공 후 부모 사용자 ciphertext 복호화 거부**를 확인했고 user/profile/privilege cleanup이 PASS입니다. 이는 underlying DPAPI 사용자 경계 검증이며 같은 사용자 process 격리 또는 실제 서비스 token 저장 성공을 뜻하지 않습니다. 사용자 Windows 11 PC와 그 계정/roaming 환경은 NOT VERIFIED입니다.

### 첫 Windows 실행 실패와 수정 이력

[실행 38544669027](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38544669027)의 전체 회귀는 **812 passed / 1 skipped / 17 failed**로 **FAIL**입니다. [첫 실행 annotations](phase4b2b_evidence/windows_initial_run.json)을 보존했습니다. GUI step은 이 실패 때문에 실행되지 않았으므로 이 실행에서 PASS로 보고하지 않습니다. Native DPAPI·다른 사용자 own roundtrip/외부 ciphertext 거부·cleanup step은 독립적으로 통과했습니다.

원인은 합성 cipher 경로가 Windows에서도 CRT로 파일을 열린 채 `unlink`하려던 점입니다. 파일 처리 방식이 cipher 종류 대신 OS를 따르게 하여 합성 경로도 Windows 독점 핸들에서 무결성/provenance를 검사하고 handle disposition으로 삭제합니다. 실패 케이스를 건너뛰거나 검사를 완화하지 않았습니다. 수정 후 Cloud 전체 회귀는 다시 824 passed / 6 skipped / 1 warning / 0 failed로 통과했습니다. Windows 최종 결과도 이 첫 실패와 구분합니다.

## 실제 호출 0건의 증거와 범위

[보안 실행 기록](phase4b2b_evidence/security_validation.json)을 제공합니다. 차단 테스트는 production callback 시작·provider/Identity transport·Vault·pipeline factory가 환경변수·GUI 승인 위조 후에도 실행되지 않음을 확인합니다. 실제 서비스 endpoint 대신 숫자 loopback Fake만 사용하는 end-to-end HTTP 테스트와 GUI 브라우저의 외부 origin 목록을 별도로 기록합니다.

DB/GUI는 synthetic 결과를 `fake_connected`로 구분하고 실제 account `api_ready=False`, `status=not_connected`를 유지합니다. Publishing job/attempt의 실제 성공을 기록하지 않으며 실제 MP4를 외부로 전송하지 않습니다. production facade를 호출하여 실제 token을 테스트하지 않았습니다. 공식 정책 페이지 GET은 OAuth·SNS API 호출로 계산하지 않습니다.

0건 표시는 코드 차단·Adapter/fixture/GUI 관측 및 수행 작업의 증거이며 호스트 전체 packet capture를 실시했다는 뜻은 아닙니다. 실제 OAuth 로그인, code exchange, token issuance/storage/read, service Identity, SNS upload/publish **각 0건**입니다.

## 변경 파일

- `oauth/callback.py`, `identity.py`, `production_dpapi.py`, `lifecycle.py`, `fake_flow.py`: 새 기반과 합성 검증 flow.
- `db/models.py`, 새 migration `0007_operational_oauth.py`, `main.py`, `migrate_data.py`: additive DB·startup metadata 복구·이전 지원.
- `gui/publishing_routes.py`, `templates/base.html`, `templates/publishing.html`, `oauth/activation.py`: 읽기 전용 준비 상태와 현재 단계 표기.
- 신규 테스트 6개 모듈과 Fake HTTP fixture; 기존 5개 테스트 파일의 단계/스키마 기대값 갱신.
- `tools/ci_production_vault_validation.py`, `tools/ci_validation.py`, 새 Windows workflow.
- `README.md`, `AGENTS.md`, `pyproject.toml`, `docs/architecture.md`, `docs/oauth_operations.md`, 본 보고서·증거·다운로드 ZIP.

전체 경로 목록은 [Git 검증 JSON](phase4b2b_evidence/git_validation.json)에 기록했습니다. JSBAE의 다른 프로젝트와 기존 workflow/PR은 변경하지 않습니다.

## 미구현·미검증·남은 위험

- 실제 Google/Instagram 로그인, Desktop OAuth Client 등록·동의·앱 검수, 실제 token/Identity/권한·서비스 호환성: **NOT VERIFIED**. 완성된 production pipeline 활성화·실계정 연결은 이번 범위 밖입니다.
- Instagram 최신 로그인별 정책이 미확정이면 **BLOCKED** 유지.
- 다른 Windows 사용자 컨텍스트의 합성 DPAPI 접근 거부는 disposable Actions runner에서 **PASS**입니다. 사용자 PC의 별도 계정 파일 접근·도메인/roaming 정책은 **NOT VERIFIED**입니다.
- 사용자 Windows 11 PC 운영, roaming profile·사용자별 보안 설정·장기 운영: **NOT VERIFIED**.
- 기존 실제 RSS/AI API, 한국어 TTS 및 30/45/60초 완성 영상 품질: **NOT VERIFIED** 유지.
- DPAPI는 같은 사용자 악성 process/관리자/호스트 침해를 방어하는 완전한 격리가 아닙니다. immutable Python 문자열의 완전한 메모리 삭제를 보장하지 않습니다.
- 채널 ID만으로 여러 Google 로그인 또는 Brand Account 선택을 완전히 식별하지 않습니다.
- token 응답 strict allowlist의 실제 서비스 추가 필드 호환성은 별도 검토가 필요합니다.
- SQLite/file의 crash 복구는 격리와 provenance 기반 정리이며 분산 원자성 보장이 아닙니다. 변조·소유 불명 파일은 자동 삭제하지 않습니다.
- 일부 완료 전 credential 오류는 pending journal로 남아 explicit recovery/startup에서 unknown으로 격리됩니다. 성공으로 표시되지는 않습니다.

## 사용자 Windows 11 PC에서 남은 확인

사용자 PC에는 연결하거나 설치하지 않았습니다. 향후 로컬 합성 수동 확인은 Python 3.12 설치 후 `run.bat`, `http://127.0.0.1:8765/health`, GUI의 차단 상태·검색·저장, `%LOCALAPPDATA%\NewsFlowAI` 데이터/로그, Ctrl+C 종료·재실행·포트 점유 안내를 확인하는 절차입니다. `python tools/ci_production_vault_validation.py --output validation-output/production-credential-vault.json`은 실제 서비스 token 없이 합성 native DPAPI를 검사합니다. 별도 사용자 provisioning은 GitHub Actions disposable runner에서만 수행하며 사용자 PC에서는 실행하지 않습니다. 실제 OAuth login/token/API를 시험하려면 후속 승인이 필요합니다.

## Git·Draft PR·다음 단계

기준 HEAD: `4d7a024c37528d1265ad595d9402bf790eb18536`.
작업 브랜치: `feat/newsflow-phase4b2b`.
최종 검증 코드 SHA: `f94d9d7467f927135c9923699834e2d90be46539` (Windows 파일 핸들 수정 포함).
초기 코드: `f9c1641f467c3564b0d86c529fc3b8f66c517193` (첫 Windows 회귀 FAIL).
신규 [Draft PR #7](https://github.com/jsbae1979-prog/JSBAE/pull/7), base `feat/newsflow-phase4b2a`.
최종 Windows [실행 38545651234](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38545651234): **SUCCESS**, 동일 코드 SHA에서 전체 회귀와 필수 실제 실행 step이 통과했습니다.
최종 문서/증거/ZIP 커밋은 이 코드 SHA 이후에 추가하며 코드·테스트·workflow를 변경하지 않습니다.
기존 PR #1~#6과 main은 보존하고 병합하지 않습니다.

Phase 4B-2C의 선행 조건은 본 결과 사용자 승인, production activation 및 실제 grant trust 경계에 대한 별도 코드 검토, 공식 OAuth Client/최소 권한·동의 화면 준비, 실제 callback 호환성·채널/Google 사용자 식별·Windows 장기 복구 검증, Instagram 미확정 정책 해소입니다. 실제 인증이 필요하면 실행·token 저장·계정 조회 승인 범위를 별도로 정해야 합니다. OAuth 승인과 SNS 게시 승인은 분리합니다.

보고서·검증·Draft PR 제출 후 개발을 중단합니다. Phase 4B-2C·실계정 연결·실제 게시·main 병합을 수행하지 않습니다.

[완료 보고서 ZIP 다운로드](https://github.com/jsbae1979-prog/JSBAE/raw/refs/heads/feat/newsflow-phase4b2b/newsflow-ai/docs/reports/phase4b2b_report.zip)에는 보고서, 아키텍처, 공식 근거·검토, Cloud/Windows 테스트/실행 증거와 Cloud 화면을 포함합니다.
