# Phase 4B-1 공식 OAuth·Windows 비밀 저장소 조사

확인 기준일: **2026-10-14, Asia/Seoul (UTC+09:00)**.
실제 조회 시각은 근거 JSON에 UTC와 서울 시각으로 함께 저장한다.
초기 조회 시각은 `2026-10-14T03:14:52.291865+00:00` / `2026-10-14T12:14:52.291865+09:00`이다.

조사 근거는 [oauth_official_sources.json](reports/phase4b1_evidence/oauth_official_sources.json)이다.
공개 공식 문서와 공식 공급자 GitHub 파일만 읽었다. 인증 호스트를 열거나 OAuth 로그인·code 교환·refresh·revoke·게시를
실행하지 않았다. 프록시·DNS·TLS·네트워크 권한도 변경하지 않았다.

## 판정 범위

| 항목 | 판정 | 확인 범위 |
| --- | --- | --- |
| Google 공식 authorization/token/revoke URL | PASS | 공식 Google Auth Library의 기본값을 문자열로 확인; endpoint 접속 없음 |
| Google PKCE S256 지원·계산 방식 | PASS | 공식 라이브러리의 S256 및 SHA256/base64url 구현 확인 |
| YouTube 업로드 권한 후보 | PASS | 공식 YouTube discovery의 `videos.insert`에 `youtube.upload` 포함 |
| Google/Instagram/Microsoft 웹 문서 Cloud 재시도 | NOT VERIFIED | 공개 문서 9개 모두 기존 프록시 CONNECT 거절; Windows의 별도 공개 문서 재조회 가능 |
| Instagram 로그인 경로별 최신 자격·scope·검수·native PKCE | NOT VERIFIED | 최신 공식 본문 미확보; 추정한 실행 설정 없음 |
| Windows DPAPI 사용자 범위·flags·메모리 정리 | PASS | Microsoft 공식 API 문서 원문 및 공식 WinSDK 헤더 확인 |
| 실제 계정 identity·scope grant·인증 성공·만료·취소 | NOT VERIFIED | 실제 계정·provider 호출 없음 |
| 사용자 Windows 11 PC의 실제 DPAPI/OAuth 운영 | NOT VERIFIED | 문서 확인과 실제 운영 검증은 별개 |

PASS는 해당 공식 근거를 읽은 결과이며 실제 OAuth 또는 계정 연결 성공이 아니다.
공식 웹 페이지의 HTTP 200도 API 자격 검증을 의미하지 않는다. 문서 본문과 자동 요약이 충돌하면
자동 요약을 최신 정책으로 확정하지 않고 불일치를 보존한다.

## YouTube / Google 데스크톱 OAuth

공식 Google Auth Library 소스
[oauth2client.ts](https://github.com/googleapis/google-auth-library-nodejs/blob/6ac9ab4fd49d64d8315f16d7f2757da04fbeb579/src/auth/oauth2client.ts)의
읽은 blob은 `138e66c462b5466c4f6c5b2aae0c3d6c886e9c3a`다.
해당 파일의 최신 관련 변경 시각은 `2025-07-18T18:39:59Z`다.

| 용도 | 공식 소스에서 확인한 URL 문자열 | 이번 단계의 호출 |
| --- | --- | --- |
| Authorization | `https://accounts.google.com/o/oauth2/v2/auth` | 0건 |
| Token | `https://oauth2.googleapis.com/token` | 0건 |
| Revoke | `https://oauth2.googleapis.com/revoke` | 0건 |

공식 소스는 `code_challenge_method`에 `S256`과 `plain`을 지원한다고 설명하며,
code verifier의 SHA256을 padding 없는 base64url로 변환하는 코드를 제공한다.
NewsFlow의 public-client 준비 기준은 **S256만 사용**하는 것이다. 공식 라이브러리가 `plain`을
지원한다고 해서 앱이 이를 허용해야 한다는 의미는 아니다.

공식 YouTube discovery revision `20261001`에서
`https://www.googleapis.com/auth/youtube.upload`가 `videos.insert`의 허용 권한에 포함된 것을 확인했다.
이는 업로드의 최소 권한 후보다. 채널 identity 조회에 필요한 추가 권한이나 현재 대상 계정의 실제 grant는
**NOT VERIFIED**이며, identity 조회를 위해 임의로 read scope를 추가하지 않는다.

### 공식 웹 문서 재확인 목록

| 공식 문서 URL | 확인할 내용 |
| --- | --- |
| https://developers.google.com/youtube/v3/guides/auth/installed-apps | Authorization Code, 시스템 브라우저, local redirect, PKCE, offline grant·refresh·취소 |
| https://developers.google.com/identity/protocols/oauth2/native-app | 현재 native/public-client 권장 흐름, PKCE S256, loopback redirect와 OS별 지원 |
| https://developers.google.com/youtube/v3/docs/videos/insert | 최소 업로드 scope, 계정/앱 자격 및 현재 업로드 관련 정책 |

Cloud에서는 세 URL 모두 `proxy_connect_denied`로 본문을 읽지 못했다.
공식 저장소 근거와 이전 단계의 공식 문서 확인을 최신 실계정 연결 검증으로 확대하지 않는다.
Windows에서 공개 문서를 다시 읽더라도 실제 계정 로그인이나 endpoint 호출을 포함하지 않는다.

### Phase 4B-1의 실행 경계

실제 YouTube Adapter에는 endpoint 문자열만 있고 `begin`, `exchange`, `refresh`, `revoke`는 차단된다.
사용자 승인 인수를 설정했다고 이 경계가 해제되지 않는다. 기본 상태는 `OFFLINE/BLOCKED`다.
Fake Provider의 합성 code/token을 통한 검증과 실제 OAuth를 구분한다.

향후 별도 승인된 실제 연결에서 검증할 항목은 다음과 같다.

- 시스템 브라우저의 공식 Authorization Code flow와 PKCE S256.
- 암호학적 난수 `state`, 짧은 유효기간, 계정·provider·정확한 redirect URI 결합과 1회 사용 code.
- 기본 loopback GUI 주소 `127.0.0.1:8765` 및 명시적 설정에 맞는 callback 검증; 자동 포트 변경 없음.
- 실제 granted scope·대상 계정 identity·token 만료·refresh·동의 취소 처리.
- 공식 고정 endpoint, TLS 인증서 검증, off-host redirect 차단과 비밀정보를 제거한 오류 처리.
- 결과 불명인 게시 작업의 자동 재게시 금지. 토큰 refresh 성공을 게시 재시도의 근거로 삼지 않음.

위 목록은 인증 설계·검증 조건이다. 실제 외부 연결이 구현·검증되었다는 뜻이 아니다.

## Instagram 로그인 경로

Instagram Login과 Facebook Login을 다른 경로로 취급한다. 아래 공식 문서의 최신 본문이
미확인인 동안 계정 유형, 실제 OAuth scope, app review, native/public-client PKCE 또는 redirect 허용을
확정하지 않는다.

| 공식 문서 URL | 재확인할 내용 |
| --- | --- |
| https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login | professional 계정 자격, Facebook Page 필요 여부, 로그인별 지원 범위 |
| https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login | 공식 authorization flow, native/public-client PKCE와 등록 redirect 지원 여부 |
| https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing | 현재 필요한 최소 scope, app review·권한 레벨·게시 자격 |
| https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login | Facebook Login의 계정/Page 자격과 해당 로그인 경로의 권한 |

Cloud에서는 네 URL 모두 기존 프록시에서 차단되었다. 이전 단계에서 Instagram 개발 문서의
허용 범위를 벗어난 리다이렉트가 발생한 사실도 계정 자격이나 PKCE 지원의 근거가 아니다.
Instagram 실제 Adapter는 **모든 실제 메서드가 차단**되며 endpoint와 scope는 미설정이다.
기존 권한명이나 다른 플랫폼의 PKCE 지원을 Instagram에 그대로 복사하지 않는다.

## Windows DPAPI 공식 근거

공식 Microsoft 웹 문서는 다음 두 API 문서로 한정해 공개 조회한다.

- https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata

Cloud의 웹 조회는 차단되었지만 Microsoft가 관리하는 문서 원문을 GitHub에서 읽었다.

| 공식 원문 | 확인한 blob / 최근 관련 변경 |
| --- | --- |
| [CryptProtectData](https://github.com/MicrosoftDocs/sdk-api/blob/0a160262f8cff85ac596b266c86e16dfd36aaae8/sdk-api-src/content/dpapi/nf-dpapi-cryptprotectdata.md) | `d3ecff65ad20b3f8bee9fa0bafd17b62d4f8d465` / `2025-11-13T20:18:00Z` |
| [CryptUnprotectData](https://github.com/MicrosoftDocs/sdk-api/blob/649ac0310f33d4d8852aaa524ee01918528da125/sdk-api-src/content/dpapi/nf-dpapi-cryptunprotectdata.md) | `92f2e6562cebe2ad0a60329e128d6ea55d7296b2` / `2026-02-18T03:10:32Z` |
| [Microsoft WinSDK dpapi.h](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/dpapi.h) | `b5144c4ac8d9455d03a3b67bc6d3580fb72c19b4` |

### 사용자 범위와 메모리 관리

- `CryptProtectData`는 보통 동일 Windows logon credential과 동일 컴퓨터에 결합된다.
  문서는 roaming profile 예외를 설명하므로 어떤 경우에도 다른 컴퓨터에서 복호화가 불가능하다고 단정하지 않는다.
- `CRYPTPROTECT_LOCAL_MACHINE`을 설정하면 같은 컴퓨터의 다른 사용자도 복호화할 수 있다.
  current-user 저장소는 이 flag를 제외한다. 공식 헤더 값은 `0x4`다.
- `CRYPTPROTECT_UI_FORBIDDEN`은 UI가 필요하면 실패하도록 한다. 공식 헤더 값은 `0x1`이다.
  문서에 해당 실패의 `ERROR_PASSWORD_RESTRICTION` 설명이 있다.
- Protect/Unprotect의 native `DATA_BLOB.pbData`는 `LocalFree`로 해제한다.
  Unprotect의 설명 문자열을 받았다면 null이 아닌 설명 포인터도 해제해야 한다.
- 민감한 native plaintext는 `SecureZeroMemory` 정리를 권고한다. Python의 immutable `str` 및
  모든 interpreter 복사본을 완전히 제거했다고 주장하지 않는다.
- DPAPI 문서는 keyed integrity check를 설명하지만 Unprotect 원문은 변조 검출의 특정 error code에
  의존하지 말고 앱 수준 무결성 검사를 고려하라고 한다. 앱은 반환 plaintext의 JSON 구조·version·
  계정 결합·필수 필드를 검증하고 오류 시 원문이나 토큰을 출력하지 않아야 한다.

공식 문서를 읽은 결과는 PASS다. 실제 Windows DPAPI 실행은 Windows 자동 테스트의 별도 결과로
보고해야 하며 사용자 Windows 11 PC 운영은 실제로 실행하기 전까지 **NOT VERIFIED**다.

## 공개 문서 조회의 보안 경계

조회 도구는 기존 문서 host 외에 Google native-app **문서 경로 하나**와 Microsoft DPAPI **문서 경로 두 개**만
추가한다. HTTPS와 기본 인증서 검증, 문서 전용 경로, timeout·크기 제한, off-host redirect 차단을 유지한다.
`accounts.google.com`, `oauth2.googleapis.com`, Instagram 인증·API endpoint는 문서 조회 allowlist에 없다.
URL의 credential/token query, 로그인, cookies, code·token 교환을 포함하지 않는다.

실제 OAuth provider 연결, 사용자 승인 없는 API 호출 및 실제 SNS 게시는 이번 검증의 범위가 아니다.
