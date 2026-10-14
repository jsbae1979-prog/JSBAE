# NewsFlow AI — Phase 4B-2A 완료 보고서

확인일: **2026-10-14 (Asia/Seoul)**. 원문 evidence에는 UTC 시각을 보존합니다.

**개발 검토 제출: PASS. 실제 계정 연결·운영 승인: NOT VERIFIED/미승인.** YouTube OAuth 코드를 구현하고 production activation을 차단한 상태에서 검증했습니다. Instagram 공식 로그인 요건은 미확인으로 BLOCKED입니다. 실제 로그인·서비스 token 발급/저장·SNS 업로드/게시를 실행하지 않았습니다.

## 1. 기준 및 Provider별 구현 범위

- Repository: `jsbae1979-prog/JSBAE`, project: `newsflow-ai/`.
- 승인 기준: Phase 4B-1 `4bce0c70af7f17af4904120866c4b46eae8c4ca2`, PR #5.
- Feature branch: `feat/newsflow-phase4b2a`; base: `feat/newsflow-phase4b1`.
- Windows 11 전용 운영, Python 3.12, 기본 `127.0.0.1:8765`, `%LOCALAPPDATA%\NewsFlowAI` 유지.

| 항목 | 판정 | 구현 및 검증 범위 |
|---|---|---|
| YouTube Desktop 설정 | PASS | `installed` JSON, client ID, SecretStr, 공식 endpoint, loopback 설정 검증. 실제 앱 등록 검증은 아님 |
| YouTube OAuth 프로토콜 코드 | PASS | Authorization Code/S256/state/정확한 URI/일회성 callback, code POST, 초기 refresh 필수, 응답·scope·expiry 검증, 명시적 refresh/revoke |
| 시스템 브라우저·공식 HTTPS transport | PASS | 비활성 코드 및 실행 전 차단. 실제 Google 실행은 NOT VERIFIED |
| identity·계정 격리 | PASS | 합성 identity와 grant 전체 결합·변조 거부 검증. 실제 identity adapter는 미구현/차단 |
| Instagram | NOT VERIFIED | 로그인 방식별 공식 요건을 확정하지 못해 endpoint/scope 미설정, Fake/interface만 유지 |
| production credential boundary | PASS | 별도 계약·계정 바인딩 설계와 실제 backend 생성 전 차단 |
| 실제 production backend·서비스 token 저장 | NOT VERIFIED | 구현·실행하지 않음. 기존 합성 전용 DPAPI를 운영 저장소로 전환하지 않음 |

## 2. OAuth 아키텍처와 인증 차단

`YouTubeOAuthAdapter.configured_protocol()` → `GoogleOAuthProtocol` → `GoogleHTTPSOAuthTransport`/`GoogleSystemBrowser`로 분리합니다. `require_production_activation()`은 항상 차단 예외를 발생시키며 환경변수·GUI 승인·테스트 플래그를 인자로 받지 않습니다. 실제 credential boundary도 backend factory 생성 전부터 차단합니다. 활성화에는 후속 사용자 승인과 검토 가능한 코드 변경이 필요합니다.

테스트는 별도의 `SyntheticLoopbackTransport`와 실제 `127.0.0.1` Fake HTTP 서버를 사용합니다. 합성 client/code/token 형식을 강제하고 official host·임의 transport·redirect·시스템 브라우저를 허용하지 않습니다. 결과는 SYNTHETIC_PROTOCOL이며 실제 OAuth 성공이 아닙니다.

state hash·PKCE verifier·code는 요청 메모리에만 보관합니다. callback의 account/state/URI/만료/중복 필드를 확인하고 잘못된 응답도 일회성으로 소비합니다. authorization와 token POST의 callback URI는 정확히 `http://127.0.0.1:8765/oauth/callback`입니다. 실제 callback HTTP 경로나 listener는 등록하지 않았습니다.

access/refresh/expiry/scope를 발급 grant와 함께 결합해 다른 계정 token 조합, 만료 연장 및 scope 변조를 전송 전에 거부합니다. initial installed-app 응답의 refresh token은 필수이며 갱신 응답의 생략은 기존 값·남은 refresh 유효기간을 유지합니다. 갱신 실패·타임아웃·불완전 응답은 identity 사용과 재시도를 차단합니다. 시작 횟수는 계정별 15분당 3회로 제한하고 자동 재시도하지 않습니다. 실제 identity 조회, 운영 callback dispatch 및 재시작 가능한 production token lifecycle 통합은 후속 조건입니다.

## 3. 공식 OAuth 문서 확인 근거

Windows CI에서 **12개 조회 기록 중 Google/Microsoft 8건 HTTPS 200**, Meta 4건 NOT VERIFIED였습니다. Google native 문서 1개를 PKCE/token/redirect의 3개 profile로 나눠 확인했으므로 고유 URL은 10개입니다. Cloud에서는 공개 문서 GET이 `proxy_connect_denied`로 실패했습니다. 네트워크 설정·TLS 검증·공개 문서 redirect 정책을 변경하지 않았습니다.

| 공식 근거 | 확인한 내용 | 판정 |
|---|---|---|
| [Google native-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) | verifier 43~128자, S256/Base64URL(SHA256), state, Windows desktop loopback, token/refresh/revoke, 초기 refresh 반환 | PASS: 본문의 특정 근거 검토 |
| [YouTube installed-apps](https://developers.google.com/youtube/v3/guides/auth/installed-apps) | 시스템 브라우저·local redirect, 최소 scope, 사용자 동의와 공개 앱 검수 선행 조건 | PASS: 문서 확인; 실제 앱은 NOT VERIFIED |
| [YouTube channels.list](https://developers.google.com/youtube/v3/docs/channels/list) 및 공식 discovery | `mine=true`는 인증 사용자 소유 channel. 메서드 허용 scope에 `youtube.upload` 없음 | PASS: 실제 identity API 호출 0건 |
| [YouTube videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert) | 공식 업로드 API 및 준비 요건. Shorts 임의 업로드 API를 추가하지 않음 | PASS: 문서만 조회 |
| [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata), [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata) | 현재 사용자 경계, LOCAL_MACHINE 위험, entropy·무결성·native buffer cleanup | PASS: 공개 문서 및 합성 native 테스트 |
| [Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login), [Business Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login), [Publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing), [Facebook Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login) | 계정 유형·scope·redirect·app review·교환/갱신/회수/identity | NOT VERIFIED: `redirect_not_allowed`, 로그인 페이지를 따라가지 않음 |

Google 공식 auth library와 YouTube 공식 discovery의 blob SHA·내용 hash도 보존했습니다. `youtube.upload`만으로 identity를 확인하지 않으며 `youtube.readonly` 후보 추가는 후속 최소 권한 검토·동의가 필요합니다. 공개 문서의 credential 예시는 export 전에 정제합니다. HTTP 200이나 자동 요약을 실제 앱 권한 검증으로 간주하지 않습니다.

근거: [공식 sources/검토 사실](phase4b2a_evidence/oauth_official_sources.json), [Windows 문서 본문](phase4b2a_evidence/windows_official_docs.json), [Cloud 조회 실패](phase4b2a_evidence/cloud_official_docs.json). Windows payload SHA256 `bca2169fda9a809d6467a67112797c3ba9479e83da71cdb0c93708896108fef3`를 확인해 annotations의 압축 조각을 복원했습니다.

## 4. Windows CredentialVault 보안 검토

**PASS: 합성 전용 current-user DPAPI와 계정 격리. NOT VERIFIED: 실제 production token 보관.** 기존 `oauth/vault.py`는 변경하지 않았으며 NF marker를 해제하지 않습니다. 머신 공용 DPAPI·평문 저장·Linux Fake fallback으로 전환하지 않았습니다.

별도 `ProductionCredentialBackend` 계약은 account key·검증된 identity digest·opaque reference를 요구합니다. 실제 backend는 제공하지 않으며 public store/load/replace/delete/recover는 모두 차단합니다. `SyntheticCredentialBoundaryKernel`에서 다음을 검증했습니다.

- additive migration 0006 journal에는 비밀값 없이 account/digest/reference/단계만 저장.
- 작업 예약, revision CAS, pending→writing의 일회성 완료, 저장 후 계정·값 재조회와 DB pointer 교체.
- 커밋 전 실패와 이전 파일 삭제 실패를 구분해 현재 credential을 잘못 삭제하지 않음.
- 복구 전 journal CAS 확보, late commit·현재 pointer·최신 revision 보호, load 후 revision 재확인.
- 재시작 시 원자적인 DB 격리만 수행; provider/vault 호출이나 refresh 자동 재시도 없음.
- 실제 Windows DPAPI의 암호화 파일, 새 프로세스 조회, 한글/공백 경로, 만료·변조·회전·삭제·복수 계정 격리.

SQLite와 filesystem 전체가 하나의 원자적 트랜잭션이라고 주장하지 않습니다. 암호문 작성 후 reference journal 저장 전 종료는 orphan ciphertext를 남길 수 있으나 계정 연결로 승격하지 않습니다. Python immutable 문자열 완전 삭제와 동일 사용자 악성 프로세스 격리는 보장하지 않습니다. [Windows vault evidence](phase4b2a_evidence/windows_vault.json).

## 5. Cloud 전체 회귀 및 GUI

**PASS: 512 passed / 3 skipped / 1 warning / 0 failed / 0 errors — 515 collected.** 기존 358개 case를 유지하고 157개를 추가했습니다. 실행 명령:

```text
python -m pytest -q -rs --junitxml=/tmp/newsflow-phase4b2a-cloud-pytest.xml
python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase4b2a-cloud-final
```

첫 명령은 프로젝트 Python 3.12 `.venv`에서 실행했습니다. RSS opt-in 1건과 Windows native DPAPI 2건이 skipped입니다. 기존 Starlette/httpx deprecation warning 1건은 남아 있습니다. `python -m pip install --no-deps -e .` 실제 설치와 Ruff도 PASS입니다.

실제 서버·Chromium에서 RSS 등록/활성화/수집 POST, 검색, AI·Video·Publishing POST, SQLite 재시작 유지, port collision/중복 실행, mobile overflow를 확인했습니다. OAuth 준비/해제는 로컬 기록이고 위조 시작은 423, 실제 버튼은 disabled, 모든 production-readiness flag는 false였습니다. 실제 30초 synthetic MP4 미리보기도 통과했으며 사람 품질 검증은 아닙니다.

초기 전체 검증의 **1 failed / 19 errors**는 fixture 전역 등록과 migration data allowlist를 수정했습니다. 문서 처리 추가 검증의 **1 failed**는 긴 context가 본문 근거를 잘라내는 버그를 수정했습니다. 테스트를 삭제·skip하거나 보안을 완화하지 않았습니다. [pytest 원문](phase4b2a_evidence/cloud_pytest.txt), [수치/수정 이력](phase4b2a_evidence/cloud_pytest.json), [최종 브라우저 evidence](phase4b2a_evidence/cloud_result.json), [화면](phase4b2a_evidence/oauth_studio.png).

## 6. Windows Actions 전체 회귀

**PASS: 514 passed / 1 skipped / 0 failed / 0 errors — 515 collected.** 최종 검증 [run 38514050334](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38514050334), tested HEAD `337242a598275bb20eb97d793bbf6d8e10934b67`입니다.

| 검증 | 판정 | 실제 수행 범위 |
|---|---|---|
| 전체 pytest/Fake HTTP OAuth | PASS | 회귀·PKCE/state/replay/token response/identity/binding/unknown/위조 승인/게시 차단 |
| current-user DPAPI | PASS | native API, 합성 값만 사용; 새 boundary rotation/reopen/isolation 포함 |
| run.bat/server/health/종료 | PASS | 실제 BAT, `127.0.0.1:8765/health`, process tree 종료 |
| LOCALAPPDATA/SQLite/재실행 | PASS | 기본 경로, 저장·조회·재시작 유지 |
| 포트 충돌/중복 실행 | PASS | 정상 실행으로 표시하지 않고 거부 |
| 실제 Chrome GUI POST | PASS | 등록/수집/Publishing/OAuth 준비 POST, 위조 start 423, CSRF·Origin·CSP 유지 |
| 실제 user Windows 11/Ctrl+C | NOT VERIFIED | Windows Actions VM 검증이며 사용자의 PC 운영 검증은 아님 |

JUnit summary는 pytest warning 수를 제공하지 않으므로 Windows warning 0건을 주장하지 않습니다. Actions의 기존 Node 런타임 deprecation annotation은 테스트 결과와 구분합니다.

초기 run `38512765212`는 설치 실패(FAIL)로 테스트를 실행하지 못했습니다. 잘못된 버전 `0.4.1b2a`를 로컬에서 확인하고 PEP 440 `0.4.2a1`로 수정했습니다. raw 설치 로그는 Cloud redirect 제한으로 확인하지 못했으며 수정 후 로컬·Windows 설치는 PASS입니다. 이전 코드 run `38513064214`는 511 passed/1 skipped로 PASS였고, 문서 보완 중 run `38513912215`는 최종 코드 실행으로 대체돼 CANCELLED입니다. 최종 run은 모든 필수 단계가 success입니다. [Windows pytest](phase4b2a_evidence/windows_pytest.json), [BAT/browser](phase4b2a_evidence/windows_result.json), [run metadata](phase4b2a_evidence/windows_run.json), [검증 manifest](phase4b2a_evidence/verification_manifest.json).

## 7. 실제 OAuth·SNS 호출 0건 증거

**PASS: 실제 인증 시작/시스템 브라우저 로그인, code exchange, service token 발급·저장, refresh/revoke/identity API 및 SNS 업로드·게시 0건.**

근거는 unconditional activation gate, official transport 직접 호출 전 DNS/TLS/browser 미호출 테스트, credential backend factory 미호출, loopback Fake HTTP 합성 request 검증, GUI start 423과 disabled 버튼, 브라우저 외부 request origin 빈 목록입니다. Cloud/Windows GUI 검증 DB의 계정은 `not_connected`, `api_ready=false`, credential 미생성이며 PublishJob/Attempt는 0건입니다. Fake unit test의 simulated 결과는 실제 성공이 아닙니다.

`/api/oauth/safety`와 `/api/publishing/safety`는 structural guard 상태이며 전체 기기의 독립 network meter가 아닙니다. 공식 문서 GET·package 설치·Fake loopback HTTP를 실제 OAuth/SNS 호출로 집계하지 않습니다. 외부 MP4 전송·임의 공개 URL·계정 로그인이나 실제 API 키 등록은 하지 않았습니다.

## 8. 미검증·보안상 남은 위험과 실계정 선행 조건

모두 **NOT VERIFIED**: 실제 Google/Instagram 로그인·token 발급/저장, 실제 앱 등록·동의·scope/계정 자격·검수, 실제 SNS 게시, 사용자 Windows 11 PC, 기존 실제 RSS/AI API, 한국어 TTS 및 30/45/60초 완성 영상의 사람 품질 검토. 샘플 MP4/SAPI/native DPAPI 성공은 이 항목의 대체 검증이 아닙니다.

운영 전 남은 조건:

1. 사용자 후속 승인과 별도 reviewed production activation 코드 변경. 환경/GUI flag만으로 활성화 불가.
2. Google Desktop 앱·동의 화면·scope 검수, 실제 채널 identity와 추가 최소 권한 검토.
3. 정확한 callback HTTP dispatch/listener 및 등록 URI 확인. 문서의 random available port 권고와 앱의 고정 8765 정책을 실환경에서 확인.
4. 별도 current-user production backend, DB lifecycle 통합·회전/회수 실패·orphan ciphertext·계정 전환 복구 검증.
5. Instagram Login/Facebook Login의 최신 계정/권한/redirect/앱 검수/교환/갱신/회수/identity 확정.
6. 현재 token response allowlist 밖의 유효 응답은 fail-closed될 수 있음. Google의 unknown field 무시 권고와의 운영 호환성 검토가 필요하며 optional DPoP는 미구현.

CSRF/SSRF/TLS/CSP, timeout, HTML escape, token redaction 및 실제 Publisher 차단을 유지했습니다. 환경 네트워크 권한·비용·계정 설정을 변경하지 않았습니다.

## 9. 변경 파일, Git SHA 및 Draft PR

- 최초 코드: `7b980eec457aaa4f2db2d2f7752a6a8952434e39`.
- package version 수정: `9818241638eae8e5decb231eb5e626e2094ebcb2`.
- 공식 문서 반영/예시 정제: `b4c8cd0592e81575ca864841dbf7009656575945`.
- **최종 tested code: `337242a598275bb20eb97d793bbf6d8e10934b67`.** 이후 커밋은 보고서/evidence/다운로드 ZIP 문서만 갱신합니다.
- **Draft PR [#6](https://github.com/jsbae1979-prog/JSBAE/pull/6)**, base `feat/newsflow-phase4b1`.

주요 변경은 `oauth/activation.py`·`production.py`·`production_vault.py`·provider integration, DB model/additive 0006, startup recovery/data migration allowlist, Publishing readiness API/template, Fake HTTP fixture와 protocol/binding/activation/vault/GUI/documentation tests, official collector, validation harness 및 새 branch 전용 Windows workflow입니다. README/AGENTS/architecture/설계·sources·보고서를 갱신했습니다. [전체 파일 목록](phase4b2a_evidence/changed_files.txt).

변경은 `newsflow-ai/`와 해당 새 workflow에 한정했습니다. migration 0001~0005와 기존 synthetic-only vault는 수정하지 않았습니다. 기존 PR #1~#5의 HEAD는 보존됐고 main은 `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`로 유지됩니다. 병합하지 않았습니다.

## 10. Phase 4B-2B 진입 여부와 중단

**개발 결과 검토 가능: PASS. 실계정 실행/Phase 4B-2B 승인: NOT VERIFIED/미승인.** 위 선행 조건 해소와 사용자의 다음 명시적 승인 전 실계정 연결·token 발급/저장·SNS 업로드·게시를 실행할 수 없습니다. OAuth 연결 승인은 게시 승인과 분리합니다.

보고서, 검증 evidence, 다운로드 ZIP 및 Draft PR 제출 후 개발을 중단합니다. Phase 4B-2B와 main 병합을 진행하지 않습니다.
