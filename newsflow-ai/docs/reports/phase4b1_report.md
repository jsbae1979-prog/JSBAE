# NewsFlow AI — Phase 4B-1 OAuth 및 계정 연결 기반

확인 기준일: **2026-10-14 Asia/Seoul (UTC+09:00)**. DB·테스트 근거의 timestamp는 UTC이며 공식 조사 JSON은 서울 시각도 함께 기록합니다.

## 범위와 실행 경계

승인 Phase4A HEAD `e3b9c71927218864afec00434460d7d9cb8b8046`에서 `feat/newsflow-phase4b1`을 분기했습니다. Windows11/Python3.12/기존FastAPI GUI/127.0.0.1:8765/LOCALAPPDATA를 유지합니다. 이번 단계는 OFFLINE/BLOCKED이며 실제 로그인·OAuth code/token exchange·실제 서비스 토큰 발급/저장·계정 연결·SNS 업로드·공개 MP4 URL·자동 게시를 실행하지 않습니다. feature_enabled/user_approved를 true로 만든 테스트에서도 이번 단계의 allows_real은 항상 false입니다.

| 항목 | 판정 | 근거/범위 |
|---|---|---|
| OAuth/session/계정 준비/Fake 수명주기 | PASS | 아래 구현 및 경계 테스트 |
| Cloud 전체 회귀 | PASS | 356 passed /2 skipped /1 warning /0 failed; 기존218개유지 |
| Cloud 실제 서버·Chromium POST/보존 | PASS | 준비/해제303, 위조시작423, 비활성버튼, 재시작 유지 |
| Windows 현재 사용자 DPAPI 실제 실행 | PASS | 합성 토큰 암호화·새 프로세스 복호화·격리·교체/삭제·변조/만료 차단 |
| Windows 전체 회귀·BAT·Chrome POST | PASS | 357 passed/1 skipped/0 failed/0 errors 및실제BAT/브라우저/보존 |
| Google/Microsoft 공식 소스 조사 | PASS | endpoint/S256/YouTube scope/DPAPI API·flag 문자열/본문 읽기 |
| 최신 Instagram 로그인별 요건 | NOT VERIFIED | 실제 endpoint·scope 설정 없음 |
| 실제 OAuth 인증·게시 호출 | PASS | 금지 경계 검사: 모두0; 실제 인증 성공 판정이 아님 |
| 실제 SNS 토큰·계정 인증 및 Windows11 사용자 PC | NOT VERIFIED | 이번 단계 금지/미실행 |
| 실제 RSS·AI API·전체 영상 품질 | NOT VERIFIED | 기존 미검증 상태 유지 |

## 구현 기능 및 OAuth 아키텍처

OAuthProvider Protocol, YouTubeOAuthAdapter, InstagramOAuthAdapter, FakeOAuthProvider, OAuthSession/OAuthSessionStore, OAuthCallbackValidator, TokenLifecycleManager, CredentialVault Protocol, WindowsCredentialVault, FakeCredentialVault를 구현했습니다. 기존 Phase4A publishing.auth 계약은 변경하지 않고 TokenBundle의 SecretStr·검증 오류 입력 마스킹을 재사용합니다.

실제 provider의 begin/exchange/refresh/revoke는 HTTP transport 없이 항상 OAuthBlocked입니다. YouTube의 공식 endpoint는 metadata 문자열이며 실행 요청이나 링크를 생성하지 않습니다. Instagram endpoint/scopes는 미설정입니다. Fake Instagram의 일반적인 S256 경계 테스트는 실제 Instagram PKCE 지원을 확인한 결과가 아닙니다.

Session은 난수 state32bytes/PKCE verifier64bytes, S256, 정확한 `http://127.0.0.1:8765/oauth/callback` URI와 플랫폼/로컬계정 binding, 최대300초 만료를 사용합니다. 이 URI는 검증 메타데이터이며 실제 callback HTTP 라우트는 없습니다. state hash와 verifier는 메모리에만 보관하며 state/code/verifier를 DB나 화면에 저장하지 않습니다. callback은 Lock으로 첫 처리 시 원자적으로 소비합니다. 불일치·중복 인수·error/code 동시값·제어문자·만료·취소·재사용은 차단하고 잘못된 응답도 재사용하지 않습니다. 재시작은 메모리 세션을 무효화합니다.

Fake는 nf-synthetic-code/access/refresh만 사용하고 요청 scope와 최소 후보/응답 scope를 검사합니다. 위조 scope는 exchange 전에 차단합니다. token rotation은 새 reference 저장→revision CAS로 DBpointer 교체→이전 reference 삭제 순서이며 CAS 실패의 새 reference는 정리합니다. 바인딩 불일치·재사용은 고정된 감사 기록만 남겨 정상 계정이나 다른 계정의 상태를 변경하지 않습니다. 만료/취소/인증 오류는 fail-closed이며 refresh/revoke는 명시적 Fake 호출만 지원합니다. 해제는 대기 세션도 무효화하며 자동재시도하지 않습니다. Fake 성공도 PlatformAccount는 not_connected/api_ready=false이고 실제 게시로 승격할 수 없습니다.

## 데이터·GUI·게시 차단

additive migration0005는 OAuthConnection에 account_id/status/mode/revision/expires_at/error_code/updated_at만 추가합니다. 기존0001~0004는 변경하지 않고 기사·대본·영상·게시초안/검증/근거를 보존합니다. 토큰값 컬럼은 없고 기존 PlatformAccount.credential_ref는 불투명 reference만 저장합니다. error code는 고정 enum이며 외부 메시지·callback 인수·비밀 원문을 AuditLog에 기록하지 않습니다.

Publishing Studio는 플랫폼 상태, 로컬 연결 준비·해제 준비, 권한 후보/미확인 안내, 오류 상태, 토큰 비노출, 비활성 실제 연결 버튼을 제공합니다. 준비와 해제 준비는 로컬 intent 기록이며 vault 접근·토큰 삭제·서비스 동의 회수가 아닙니다. 실제 start POST는 body/query/env의 승인 위조와 무관하게423이며 callback/authorize/token 입력 라우트가 없습니다. 기존 CSRF/Origin/CSP/SSRF/TLS/robots/HTML escape를 유지합니다. Phase4A 실제 Publisher의 media/media_publish/videos.insert 실행 차단은 그대로입니다.

## Windows CredentialVault

WindowsCredentialVault는 명시적으로 전달받은 절대 데이터 경로(예정 `%LOCALAPPDATA%\NewsFlowAI\credentials`)에서 현재 사용자 DPAPI CryptProtectData/UnprotectData, CRYPTPROTECT_UI_FORBIDDEN만 사용합니다. LOCAL_MACHINE flag는 사용하지 않습니다. 계정별 entropy 및 protected payload의 version/계정/checksum을 검사합니다. 디스크에는 ciphertext .bin만 저장하며 UUID reference·한글/공백 경로·크기 제한·symlink/junction 거부·exclusive temporary write/fsync/atomic no-overwrite publication을 적용합니다. native buffer와 mutable plaintext buffer를 지우고 LocalFree합니다. Python immutable str/모든 interpreter 복사본의 완전 삭제를 보장하지 않습니다.

이 단계는 synthetic-only guard가 있어 실제 서비스 토큰은 store/load가 항상 거부됩니다. unsupported OS/native failure에서 Fake로 자동 대체하지 않습니다. GUI는 저장소를 자동 생성하거나 실행하지 않습니다. 실제 Windows 검증은 합성 토큰만 사용해 암호화 파일·새 Python프로세스 복호화·계정 격리·교체/삭제·만료·변조 차단·본인 테스트 파일 정리를 확인합니다. 다른 Windows 사용자 계정·프로필 복구/roaming·사용자 PC운영은 별도 미검증입니다.

## 공식 조사

[OAuth/DPAPI 공식 URL·근거·확인 날짜](../oauth_platforms.md), [초기 공식 소스/Cloud 접근 근거](phase4b1_evidence/oauth_official_sources.json). Google 공식 Auth Library에서 authorization/token/revoke URL 및 S256을 확인하고 실제 해당 endpoint는 호출하지 않았습니다. YouTube 공식 discovery의 youtube.upload는 최소 업로드 권한 후보이며 실제 대상 identity·grant/앱 검증은 미확인입니다. Microsoft 공식 API 문서/WinSDK에서 current-user, UI_FORBIDDEN, LOCAL_MACHINE 제외, LocalFree 및 메모리 정리 범위를 확인했습니다.

Cloud 공개 문서9개는 기존 프록시 CONNECT 거절로 NOT VERIFIED입니다. 기존 Windows Runner의 문서 조회는 credentials/cookies/login/계정/게시 없이 공개 HTTPS만 재시도하며 TLS/호스트·경로 제한을 완화하지 않습니다. Windows에서 Google문서3개/Microsoft DPAPI2개의 본문 발췌를 확보했고4개Instagram문서는허용범위밖redirect를거부하여NOT VERIFIED입니다. [Windows문서발췌](phase4b1_evidence/windows_official_docs.json)는압축chunk를SHA256확인후복원한것이며자동요약/최대6,000자발췌범위와실계정적용을구분합니다. 현재public-client의세부loopback등록/desktop-client자격은추가확인이필요합니다. Instagram 최신 자격·scope·app review·native PKCE·redirect 지원을 확정할 수 없으면 실제 Adapter는 계속 차단 상태입니다.

## 테스트 및 실제 호출0건 근거

`python -m pytest -q -rs`: **356 passed /2 skipped /1 warning /0 failed**. [pytest 원문](phase4b1_evidence/cloud_pytest.txt). Windows 최종 결과는357 passed/1 skipped/0 failures/0 errors입니다. NativeDPAPI case가실행되어Cloud보다PASS1개더많습니다. 기존218개를 유지하며 새 테스트는 state/PKCE·callback mismatch/replay/expiry/concurrency, Fake 성공/실패/취소·scope, 계정 격리·회전·해제·실패 복구, vault 보호·미노출, GUI POST/CSRF/CSP, 0004→0005 보존을 검사합니다. 기존 live RSS skip은 opt-in이며 네이티브 DPAPI skip은 Linux Cloud에만 적용됩니다. Windows에서는 네이티브 vault 테스트 실패를 skip으로 바꾸지 않습니다. 기존 Starlette/httpx warning을 숨기지 않습니다.

Cloud 실제 실행 명령: `python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase4b1-cloud`. PASS: Uvicorn health/POST/포트중복/DB재시작, 실제 Chromium의 준비·해제303/진짜Origin·위조start423·disabledbutton·mobile overflow 없음, SQLite disconnect_prepared/offline/revision3/credential 없음/api_ready=false/scopes[] 유지. 기존30초 MP4 디코드·미리보기·다운로드 회귀도PASS이며 품질검수는 아닙니다. [결과](phase4b1_evidence/cloud_result.json), [화면](phase4b1_evidence/oauth_studio.png), [모바일](phase4b1_evidence/mobile.png). 초기 Cloud 화면 캡처 후 공통 phase표시 문구만 갱신했으며 최종 Windows에서 현재 화면을 검사합니다.

0건 근거는 (1) 실제OAuth/Publisher transport·실행 callback 없음과 항상차단 adapter, (2) 승인/flag/위조 요청을 해제하지 못하는 테스트, (3) 실제 GUIDB계정 not_connected/credential 없음·publish job/attempt0, (4) 구조적 safety값 authorization/token exchange/refresh/revoke/publish 모두0, (5) 브라우저 외부 origins[]를 결합합니다. safety값은 앱 전체 네트워크의 계측기로 주장하지 않습니다. 공개 문서/GitHub 읽기·의존성 설치는 OAuth/SNS실행과 구분합니다. 실제 서비스 키/토큰을 Actions에 등록하거나 실제 계정 로그인하지 않았습니다.

## 변경 파일

- oauth/{contracts,session,providers,service,vault,__init__}.py: 보안 계약/메모리 요청/차단·Fake/수명주기/DPAPI.
- db/models.py, migration0005_oauth.py, migrate_data.py: 계정별 메타데이터와 새 revision지원.
- gui/publishing_routes.py, templates/{publishing,base}.html, static/css/app.css: 계정 준비·오류·권한/차단 UI 및 POST.
- tests/{test_oauth,test_oauth_gui,test_oauth_vault}.py; 기존3개 테스트는 최신 revision 기대값만 갱신, 제거/완화 없음.
- tools/ci_vault_validation.py, ci_validation.py, ci_official_research.py, 새 .github/workflows/newsflow-phase4b1-windows.yml: 합성 nativeDPAPI·브라우저·공식문서·전체회귀. 이전 workflow 변경 없음.
- AGENTS/README/pyproject(0.4.1b1, 추가 dependency 없음)/architecture/oauth_platforms/보고서/evidence: 실행 경계·설계/출처·근거.

## 미구현·미검증 및 Phase4B-2 선행 조건

실제 OAuth client등록·Authorization URL/시스템브라우저 실행·HTTP callbacklistener/transport·실제 code exchange·grant/identity 확인·실제 token 발급/DPAPI저장·실제 refresh/revoke는 미구현/NOT VERIFIED입니다. 실제Instagram로그인경로·자격·scope·app검수/native지원은 미확인이며 대체 endpoint를 추정하지 않습니다. 계정별 remoteID/안전한 사용자승인 기록·WindowsuserPC·다른Windows사용자·OS비밀저장소운영복구도 미검증입니다. 실제RSS/AI와 전체영상 품질 미검증을 유지합니다.

Phase4B-2 전 사용자 별도승인, 플랫폼/계정·앱등록/검수·최소scope·desktopredirect지원 확정, 실제 요청 flag+승인 policy와 loopback callback 보안/실제identity격리, synthetic-only 저장소를 실제토큰에 활성화하기 위한 별도 코드/보안검토, 계정선택·토큰회수/실패·복구절차 및 WindowsPC 검증이 필요합니다. OAuth승인을 영상 업로드/게시 승인으로 간주하지 않으며 실제 게시에는 별도의 명시적 승인이 필요합니다.

## Git/Draft PR 및 중단

브랜치 `feat/newsflow-phase4b1`, base `feat/newsflow-phase4a`/e3b9c71. [Draft PR #5](https://github.com/jsbae1979-prog/JSBAE/pull/5)는 OPEN/DRAFT입니다. 구현 커밋 `f33af2c5c7e55c29b06f86afdbe5441552984df6`, 안전한 오류 진단 커밋 `650ad1844e4f8d38ca730632435a5da2afc7e067`입니다. Windows 테스트 ID 보완 커밋 `1cf3d1c3c6aff1123987b911e75998c49b86d55d`입니다. 최종 Windows검증은이HEAD에실행했고이후변경은보고서·근거·README문서뿐입니다. 최종문서commit은PR Commits에서확인할수있습니다. 기존PR#1~#4와main은 수정·병합하지 않습니다. 변경 범위는 newsflow-ai와 신규branch전용workflow하나이며 다른프로젝트/기존migration/기존workflow변경은없습니다. 완료후개발을중단하고Phase4B-2/실계정/게시/main병합을진행하지않습니다.

## 초기 Windows 오류와 해결 경과

초기 run38506864855 및 진단 run38507587926은 **FAIL**: 358 tests/355 passed/1 skipped/0 failures/2 ERROR였습니다. 실제 native DPAPI검증은 별도로PASS였지만 전체회귀나 후속브라우저를PASS로기록하지 않았습니다. [초기 pytest](phase4b1_evidence/windows_pytest_initial.json), [초기 실제 vault](phase4b1_evidence/windows_vault_initial.json). 원본 로그 다운로드가 Cloud에서 차단되어 CI helper는 오류case명·고정exception종류·코드위치만 출력하도록 추가했고 원문메시지/parameter값/토큰은 출력하지 않았습니다.

두오류는 b'x'*131073 ciphertext와 b'x'*32769 plaintext test의 자동 parameter ID가 각각131,153/32,850자로 Windows PYTEST_CURRENT_TEST 환경변수32767 제한을 초과해setup이ValueError로실패한 것입니다. explicit짧은ID만지정하여nodeid를100자이하로줄였고, 대용량입력/모든assert/전체case수는 유지했습니다. 보안검사/제품코드/테스트skip변경은없습니다. 최종run38508328854에서358개중357 passed/1 skipped/0 failures/0 errors로해결을확인했습니다. 동일대용량경계검사가실제로실행된결과입니다.

## 최종 Windows Actions 및 완료 판정

[Windows 실행38508328854](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38508328854), 검증HEAD `1cf3d1c3c6aff1123987b911e75998c49b86d55d`: workflow/job **SUCCESS**, **357 passed /1 skipped /0 failures /0 errors**. [pytest](phase4b1_evidence/windows_pytest.json), [run/step](phase4b1_evidence/windows_run.json). Windows warning수는JUnit요약에없어NOT VERIFIED이며0으로주장하지않습니다. 유일한skip은기존opt-in liveRSS입니다.

PASS: 현재사용자네이티브DPAPI(ciphertext디스크저장·새Python프로세스복호화·한글/공백경로·다중local계정격리·wrong계정조회/삭제차단·token교체/삭제·만료/변조차단·실제형식token저장거부·임시파일/본인테스트데이터정리). [실제Vault근거](phase4b1_evidence/windows_vault.json). 합성토큰만사용했고서비스토큰/실제OAuth/SNS호출0입니다. 실제다른Windows사용자계정/프로필roaming/사용자Windows11PC는NOT VERIFIED입니다.

PASS: 실제run.bat/LOCALAPPDATA/health/서버기동·종료/중복·포트충돌/SQLite재시작조회, GoogleChrome기반브라우저의계정metadata·prepare/disconnect303·위조start423·disabled실제버튼·모바일·재시작보존. GUIDB는disconnect_prepared/offline/revision3/credential없음/api_readyfalse/scopes[] 및게시job/attempt0입니다. 브라우저외부origins[]이고OAuth·게시counter모두0입니다. [브라우저/실행결과](phase4b1_evidence/windows_result.json). 수동Ctrl+C는NOT VERIFIED이며CI종료는taskkill process tree입니다.

PASS: 기존합성FFmpegMP4·ffprobe·한글자막/SAPI·30초브라우저프레임디코드/미리보기/다운로드회귀. [영상요약](phase4b1_evidence/windows_video.json). 음성발음·최종30/45/60초품질검수는NOT VERIFIED입니다. 실제RSS/AIAPI 미검증도유지합니다.

최종공식문서5개(Google3/MS2)는HTTPS200본문확보,Instagram4개는off-hostredirect차단입니다. [최종공식문서](phase4b1_evidence/windows_official_docs_final.json)의6,000자/page발췌를gzip/base64chunk에서SHA256확인후복원했고축소는없습니다. 문서본문획득과실제OAuth자격/전체문서검증은구분합니다. Source/flags/S256및문서본문에서직접확인한조건만PASS이며실제identity/grant/등록redirect/앱검수는NOT VERIFIED입니다.

Phase4B-1의OFFLINE/BLOCKED구현과개발/자동화검증은완료했습니다. ACCEPTED 판정및Phase4B-2승인은사용자에게남깁니다. 실제OAuth/계정연결/서비스토큰/SNS업로드및main병합은수행하지않았으며보고서제출후개발을중단합니다.

## 다운로드

[Phase4B-1 보고서 및 검증 근거 ZIP](https://github.com/jsbae1979-prog/JSBAE/raw/refs/heads/feat/newsflow-phase4b1/newsflow-ai/docs/reports/phase4b1_report.zip). GitHub로그인이필요한저장소에서는로그인한브라우저로내려받으세요. ZIP의 docs/reports/phase4b1_report.md를열면됩니다.
