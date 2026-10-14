# Phase 4B-2B · OAuth callback, 채널 identity와 운영 credential 기반

확인일: **2026-10-14 (Asia/Seoul, UTC+09:00)**. 원본 조회 시각은 UTC로도 보존합니다. 이 문서에서 합성 테스트의 성공과 실제 서비스 인증의 성공을 구분합니다. 실제 Google/Instagram 로그인, 코드 교환, 토큰 발급·저장, 계정 조회 및 SNS 업로드/게시를 실행하지 않습니다. 배포 기본 설정은 **OFFLINE/BLOCKED**이며 환경변수와 GUI 승인 값으로 변경할 수 없습니다.

## 공식 근거와 현재 확인 범위

공개 공식 문서만 GET으로 조회했습니다. Cloud의 문서 12개 조회 기록은 기존 프록시에서 차단되어 **NOT VERIFIED**입니다. 네트워크 권한, 프록시와 TLS 설정은 변경하지 않았습니다. 같은 날 Phase 4B-2A의 Windows가 확보한 Google/Microsoft 공식 본문과 이번 단계에서 다시 읽은 공식 유지관리 저장소를 구분하여 사용합니다. 이번 단계 Windows의 공개 문서 재조회와 검증 결과는 완료 보고서에 기록합니다.

| 근거 | 확인한 내용 | 실제 검증의 한계 |
| --- | --- | --- |
| [Google 설치형 OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) | Windows 데스크톱 loopback, 임의의 사용 가능한 포트에서 listener 시작, 실제 포트를 redirect에 대입, PKCE S256와 state | 실제 OAuth Client 등록, redirect 허용 및 사용자 로그인은 NOT VERIFIED |
| [공식 Google Python OAuth flow](https://github.com/googleapis/google-cloud-python/blob/30b4f440c24db348b043382178e53727c49c96de/packages/google-auth-oauthlib/google_auth_oauthlib/flow.py) | bind 후 `server_port`에서 redirect 생성, Windows `SO_EXCLUSIVEADDRUSE`, `allow_reuse_address=False` | 예제의 URL/요청 로그를 제품 코드에 복사하지 않음; 소스를 실행하지 않음 |
| [YouTube channels.list](https://developers.google.com/youtube/v3/docs/channels/list)와 [공식 discovery](https://github.com/googleapis/google-api-python-client/blob/19fd51d1d18446206091a21eec763057d032c2b3/googleapiclient/discovery_cache/documents/youtube.v3.json) | `GET https://youtube.googleapis.com/youtube/v3/channels`, `mine=true`, 필수 `part`, 허용 scope | 실제 YouTube 계정 조회 0건; 채널 identity와 Google 사용자 identity는 다름 |
| [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) / [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata) | current-user 보호, 동일 entropy, UI 금지, 반환 버퍼 정리 및 추가 무결성 검사 | 합성 DPAPI 테스트는 실제 서비스 토큰 저장 검증이 아님 |

Google Python OAuth 패키지는 이전 `google-auth-library-python-oauthlib` 저장소에서 `google-cloud-python/packages/google-auth-oauthlib`로 이동했습니다. 최신 공식 소스의 파일 commit은 `30b4f440c24db348b043382178e53727c49c96de` (2026-09-28)이며 blob은 `4e006c2655071087e32a980dfd7e36ed504768da`입니다. YouTube discovery revision은 `20261001`입니다. 조회한 소스의 SHA와 내용 SHA-256은 [공식 근거 JSON](reports/phase4b2b_evidence/oauth_official_sources.json)에 기록합니다.

## Callback URI와 포트 결정

GUI는 기존 **`http://127.0.0.1:8765`**를 유지합니다. 운영 callback 코드에는 별도의 **`127.0.0.1` 임시 listener**를 사용합니다. 포트 `0`으로 먼저 bind하여 OS가 빈 포트를 배정하도록 하고, 실제 배정된 포트를 포함한 URI를 요청에 고정합니다. 동일한 URI를 authorization, callback 검증 및 token exchange에서 사용합니다. 포트를 확보했다가 닫은 후 다시 여는 방식은 사용하지 않습니다.

이는 Google 데스크톱 문서의 “HTTP listener on a random available port” 지침과 현재 공식 Python flow의 bind 순서에 근거합니다. `localhost`는 DNS/IPv6 및 일부 방화벽 차이를 만들 수 있어 숫자 IPv4 loopback을 사용합니다. Instagram의 callback 지원 여부를 이 결정으로 추정하지 않습니다. 기존 8765 callback metadata 계약은 회귀 호환성을 유지하며 새로운 listener의 동적 URI 검증과 구분합니다.

Windows에서는 주소 재사용을 금지하고 `SO_EXCLUSIVEADDRUSE`로 포트를 독점하여 다른 프로세스의 같은 주소/포트 bind를 차단합니다. 이미 점유된 명시적 포트에서는 오류를 반환하며 다른 포트로 조용히 이동하지 않습니다. 실제 Google OAuth에 listener를 연결하지 않으며 운영 listener 시작도 production activation 경계에서 차단합니다. 합성 listener의 실제 로컬 HTTP 테스트만 허용합니다.

검증은 세션에 묶인 URI, 정확한 Host, loopback peer, 허용된 요청 방식과 경로, Origin 정책, 고유 state, S256 verifier/challenge, 만료 및 callback 일회성 소비를 확인합니다. 취소, timeout, replay, 중복 매개변수와 위조 요청은 연결 성공으로 바꾸지 않습니다. Origin 없는 일반 브라우저 navigation과 임의 Origin 입력을 구분하며 실제 Google 브라우저 응답의 호환성은 후속 실계정 승인 전 검증해야 합니다. 임의 외부 redirect를 제공하지 않습니다.

code/state/verifier를 로그, DB, HTML 또는 callback 응답으로 반사하지 않습니다. 응답은 고정 문구와 cache/referrer 제한을 사용합니다. callback 수신은 인증 완료나 계정 연결 완료를 뜻하지 않습니다. 다른 로컬 프로세스의 요청·flood로 가용성이 저하될 수 있으며 포트 독점과 PKCE가 악성 코드, 관리자 권한 또는 브라우저 확장에 대한 완전한 격리를 제공하지는 않습니다.

## YouTube channel identity와 scope

`youtube.upload`는 업로드 권한이며 공식 `channels.list`의 허용 scope에 없습니다. identity 조회에 사용할 최소 후보는 **`https://www.googleapis.com/auth/youtube.readonly`**입니다. 이 scope는 업로드 scope와 별도로 검토하고 후속 사용자 동의를 받아야 합니다. 코드에서 허용 scope를 정의한 것은 실제 동의나 grant를 얻었다는 의미가 아닙니다.

identity 요청 설계는 공식 `channels.list(part=id, mine=true)`를 사용합니다. email, Google `sub`, 사용자 프로필 또는 채널 제목을 수집하는 가상의 endpoint/scope를 추가하지 않습니다. 채널 ID는 로컬 계정 ID와 token grant에 함께 바인딩하며 채널 변경, 이미 다른 로컬 계정에 묶인 채널, scope 축소 및 계정 교차 연결을 차단합니다. 채널이 없거나 하나로 확정할 수 없으면 자동 선택하지 않습니다. 권한 오류, timeout, 잘못된 응답 및 결과 불명 상태는 준비 완료로 표시하지 않습니다.

이 결과가 확인하는 것은 **YouTube 채널**입니다. 서로 다른 Google 로그인이 같은 채널에 접근하는 경우를 채널 ID 하나만으로 구분한다고 주장하지 않습니다. 실제 Google 계정 식별과 Brand Account/채널 선택 동작은 추가 공식 정책 검토 및 실계정 승인 후 검증할 항목입니다. 합성 채널 응답 테스트는 실제 계정 검증으로 보고하지 않습니다.

## 별도 Production CredentialVault

Phase 4B-1의 합성 전용 `WindowsCredentialVault`와 `nf-synthetic-*` 제한을 보존합니다. 새 운영 backend는 별도의 계정·identity·credential reference 계약과 current-user DPAPI 경계를 사용합니다. 실제 서비스 토큰을 저장·조회하는 public 진입점은 production activation 이전에 차단하며 합성 토큰으로만 암호화 커널을 검증합니다. Windows가 아닌 환경에서 평문 또는 Fake backend로 자동 대체하지 않습니다.

토큰은 평문 DB 필드와 분리합니다. DB에는 opaque reference, identity digest, revision과 작업 상태만 저장합니다. 암호화 payload에는 해당 계정과 identity를 바인딩하고 경로, reference 및 무결성을 검증합니다. 파일 쓰기와 다시 읽어 검증하기, DB pointer 전환, 이전 파일 삭제를 서로 다른 단계로 관리합니다. refresh rotation에서는 기존 DB revision의 CAS가 성공한 작업만 pointer를 바꿀 수 있습니다. stale 작업은 최신 계정의 토큰을 덮어쓰거나 현재 사용 중인 ciphertext를 삭제하지 못해야 합니다.

SQLite와 filesystem은 하나의 원자적 트랜잭션이 아닙니다. crash 지점마다 journal과 실제 파일/DB pointer를 함께 확인하고 미완료·모순·결과 불명 작업을 격리합니다. ciphertext orphan은 활성 pointer와 소유·계정 바인딩을 확인한 뒤 정리하며 임의 파일, symlink/junction 또는 다른 계정의 파일을 삭제하지 않습니다. refresh/revoke의 결과 불명은 자동 성공 또는 자동 재시도로 처리하지 않습니다. 운영 복구 경로도 실제 서비스 호출을 수행하지 않습니다.

DPAPI는 `CRYPTPROTECT_UI_FORBIDDEN`을 사용하고 `CRYPTPROTECT_LOCAL_MACHINE`은 사용하지 않습니다. Microsoft 문서는 LOCAL_MACHINE이 같은 컴퓨터의 다른 사용자도 복호화하도록 허용한다고 명시합니다. current-user 보호는 일반적으로 동일 logon 사용자와 컴퓨터를 요구하지만 roaming profile 예외가 있습니다. 같은 Windows 사용자 권한의 다른 프로세스를 막는 저장소라고 주장하지 않습니다. 실제 다른 Windows 사용자 컨텍스트에서의 거부 테스트는 수행 증거가 없으면 NOT VERIFIED로 유지합니다.

DPAPI가 변조된 입력을 특정 오류 코드로만 거부한다고 가정하지 않습니다. 공식 문서는 오류 코드가 달라지거나 손상된 출력이 반환될 수 있다고 설명하므로 payload 무결성, account/identity 바인딩과 schema 검사를 추가합니다. native 반환 버퍼는 `LocalFree`로 해제하고 mutable/native 비밀 버퍼는 정리합니다. Python immutable 문자열을 완전히 지웠다고 보장하지 않습니다. 같은 사용자 권한의 악성 프로세스, 관리자 또는 호스트 침해는 남는 위험입니다.

## Instagram: 확인되지 않은 흐름은 BLOCKED

로그인 방식별 공식 자료를 다시 요청합니다.

- [Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)
- [Instagram Business Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login)
- [Instagram Login Content Publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing)
- [Facebook Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login)

Cloud에서는 프록시가 공개 문서 연결을 차단했습니다. 기존 Windows 조회에서는 허용된 공개 문서 경로 밖으로 redirect되어 인증 페이지를 따라가지 않았습니다. 이번 단계 Windows 결과 역시 별도로 보고합니다. 로그인별 scope, redirect, PKCE 지원, 계정 자격, 앱 등록·검수, identity, token 교환·갱신·회수는 확정되지 않으면 NOT VERIFIED로 유지합니다. endpoint와 권한을 추정하거나 YouTube의 데스크톱 loopback/PKCE 구현을 복사하지 않습니다. Instagram adapter는 계속 BLOCKED입니다.

## Phase 4B-2C 진입 조건

후속 코드 검토·사용자 승인, production activation 변경, 실제 Desktop OAuth Client/동의 화면/필요 scope 확인, token과 채널 identity 바인딩, callback 호환성, Windows current-user 저장·회전·복구 검증을 먼저 완료해야 합니다. 실계정 또는 token 검증이 필요하면 별도 승인 범위를 정해야 합니다. OAuth 승인은 SNS 업로드/게시 승인으로 확대하지 않습니다. Publisher 차단은 유지합니다.

실제 Google/Instagram 로그인과 서비스 토큰, Instagram 정책, 사용자 Windows 11 PC 운영, 실제 RSS/AI API, 한국어 TTS 및 완성 영상 품질은 계속 NOT VERIFIED입니다. 이 문서의 설계가 실운영 승인으로 사용되지 않도록 완료 보고서에서 Cloud/Windows 합성 자동 테스트와 미검증 항목을 구분합니다.
