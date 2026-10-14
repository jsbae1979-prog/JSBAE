# Phase 4B-2A · OAuth 운영 준비와 활성화 경계

확인일: 2026-10-14 (Asia/Seoul). 이 문서는 코드 구현과 실제 서비스 검증을 구분합니다. 실제 로그인, OAuth 코드 교환, 토큰 발급·보관 및 SNS 게시를 실행하지 않습니다. 환경변수나 GUI 승인 값으로 운영 인증을 활성화할 수 없습니다.

## YouTube

공식 데스크톱 OAuth Authorization Code + PKCE S256 절차를 구현합니다. 운영 엔드포인트는 Google 공식 auth library에서 확인한 `https://accounts.google.com/o/oauth2/v2/auth`, `https://oauth2.googleapis.com/token`, `https://oauth2.googleapis.com/revoke`만 사용합니다. HTTPS 인증서 검증, 고정된 엔드포인트, POST timeout, redirect 거부와 오류 정제를 유지합니다. transport와 시스템 브라우저의 모든 실행 진입점은 production activation 경계에서 차단합니다.

- [Google 설치형 앱 OAuth](https://developers.google.com/identity/protocols/oauth2/native-app): 데스크톱 앱 등록, 시스템 브라우저, PKCE, loopback redirect, 코드 교환, refresh/revoke의 기준 문서입니다.
- [YouTube 설치형 앱 인증](https://developers.google.com/youtube/v3/guides/auth/installed-apps): YouTube API 프로젝트 및 사용자 동의 안내입니다.
- [YouTube videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert): 업로드 API의 권한 및 계정 적용 요건입니다. 이 단계에서는 호출하지 않습니다.
- [YouTube channels.list](https://developers.google.com/youtube/v3/docs/channels/list): `mine=true`와 identity 확인 후보를 검토합니다. 공식 API discovery의 이 메서드 허용 scope에 `youtube.upload`는 없습니다. `youtube.readonly` 추가는 후속 최소 권한 검토·사용자 동의가 필요하며 이번 단계에서 추가하거나 조회하지 않습니다.

로컬 설정 검증은 Google의 `installed` client JSON만 허용하며 web client, 임의 엔드포인트·redirect 및 중복 JSON 키를 거부합니다. 일반적인 export의 `http://localhost`는 loopback 설정 힌트로만 취급합니다. 애플리케이션이 실제 요청에 사용할 URI는 authorization과 token POST에서 모두 정확히 `http://127.0.0.1:8765/oauth/callback`입니다. 로컬 JSON 검증은 실제 앱 등록·Google 프로젝트 유형·동의 화면·앱 검수·계정 자격의 검증이 아닙니다.

callback은 state, 계정, 정확한 URI, 만료 및 일회성 처리를 검증합니다. code와 state/verifier 원문은 DB·로그·HTML에 보관하지 않습니다. 실제 callback HTTP route나 listener는 등록하지 않습니다. 후속 활성화 시 브라우저의 실제 응답 매개변수, 등록 설정 및 callback dispatch를 공식 문서와 실환경에서 추가 검증해야 합니다.

초기 scope는 `youtube.upload`만 사용합니다. 토큰 수신을 계정 신원 검증으로 간주하지 않습니다. protocol 테스트의 identity는 `nf-synthetic-identity-*`로 명확히 구분하며 실제 계정 연결이나 게시 권한을 부여하지 않습니다. 실제 identity adapter는 미구현·차단 상태입니다.

토큰 응답의 Bearer 형식, access token, 유효기간, scope, 선택적 refresh token과 refresh token 유효기간을 검증합니다. 갱신 응답에 refresh token이 생략되면 원래 값을 유지하며, 값이 교체되면 새 grant로 취급합니다. access·refresh token·만료·scope를 묶어 원래 발급 grant와 비교하여 계정 간 토큰 혼합을 차단합니다. 코드 교환은 일회성, 갱신·회수는 명시 실행만 허용하고 자동 재시도하지 않습니다. 타임아웃이나 불완전 응답은 결과 불명으로 처리합니다. 실운영 token metadata의 재시작 영속 복구는 활성화 전 추가 검증 대상입니다.

## Instagram

공식 로그인 방식별 문서를 따로 조사합니다. Cloud 공개 문서 조회는 프록시 제한으로 실패했습니다. 확인되지 않은 계정 자격·scope·코드 교환/갱신/회수 endpoint를 추정하지 않으며 실제 adapter는 BLOCKED, endpoint는 미설정 상태입니다. Google의 PKCE 및 데스크톱 loopback 흐름을 Instagram에 복사하지 않습니다.

- [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)
- [Instagram Business Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login)
- [Instagram Login Content Publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing)
- [Instagram API with Facebook Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login)

계정 유형, Facebook Page 연결 조건, 로그인 방식별 최소 scope, redirect 등록, token 수명·갱신·회수, identity 조회, 앱 검수 및 게시 권한은 확인 근거를 확보하기 전까지 NOT VERIFIED입니다. 공식 문서의 URL이 존재하는 것과 해당 정책을 확인한 것은 구분합니다. Windows CI의 공개 문서 조회 결과와 검토 내용은 완료 보고서에 기록합니다.

## Credential boundary

기존 `WindowsCredentialVault`는 합성 전용 계약을 유지합니다. NF prefix를 제거하거나 실제 서비스 토큰을 이 저장소에 넣지 않습니다. 별도의 `ProductionCredentialBackend` 계약은 현재 사용자 보안 경계, account key 및 검증된 identity digest, opaque reference를 요구합니다. 실제 backend 구현 및 활성화는 제공하지 않습니다. `ProductionCredentialBoundary`는 backend factory 생성 전부터 모든 저장·조회·교체·삭제·복구를 거부합니다.

합성 커널은 기존 Fake/DPAPI vault를 이용해 계정 바인딩, DB 예약과 revision CAS, 새 파일의 계정·값 재조회, credential pointer 교체, 이전 파일 정리 및 실행 중단 복구를 검증합니다. additive migration 0006의 이력에는 비밀 원문 없이 identity digest·opaque reference·단계만 저장합니다. 실패 전후 정리 단계와 commit 이후 정리를 구분하고 최신 계정 상태를 stale 작업으로 덮어쓰지 않습니다. 재시작 기본 복구는 DB metadata만 격리하고 token/provider 작업을 수행하지 않습니다.

SQLite와 filesystem은 하나의 분산 트랜잭션이 아닙니다. 암호화 파일 작성 후 reference 이력 저장 전 강제 종료는 orphan ciphertext를 남길 수 있습니다. pending/writing 결과는 unknown으로 격리하며 정상 연결로 표시하지 않습니다. 실제 운영 backend의 orphan 관리 및 계정 전환 절차는 후속 검토가 필요합니다.

- [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
- [Microsoft CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata)

현재 사용자 DPAPI의 `CRYPTPROTECT_UI_FORBIDDEN`, account별 entropy, 암호화 파일 검사 및 오류 정제는 기존 구현을 유지합니다. 머신 공용 보호로 바꾸거나 평문/Fake backend로 자동 대체하지 않습니다. 같은 Windows 사용자 권한의 악성 프로세스에 대한 격리나 Python immutable string의 완전 삭제를 보장하지 않습니다. 합성 DPAPI 검증은 실제 서비스 토큰 저장 검증이 아닙니다.

## 후속 승인 전 조건

실제 계정 연결에는 사용자 후속 승인, reviewed production activation 코드 변경, 공식 앱 유형·동의 화면·최소 scope·검수 확인, 계정 identity 검증, callback dispatch, 별도 current-user production vault 및 실패 복구 검증이 모두 필요합니다. OAuth 승인은 SNS 게시 승인과 분리합니다. Publisher의 업로드 차단은 계속 유지합니다.

공개 문서 조회의 raw 근거와 HTTP/프록시/redirect 오류는 [Phase 4B-2A evidence](reports/phase4b2a_evidence/oauth_official_sources.json) 및 완료 보고서에 보존합니다. 성공한 페이지 조회도 정책 내용의 수동 검토와 실제 앱 정책 적용을 자동으로 PASS로 만들지 않습니다.
