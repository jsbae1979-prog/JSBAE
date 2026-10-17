# Instagram 인증 중계 배포 준비

이 중계는 **Facebook Login for Business의 Authorization Code 경로 하나**만 사용합니다. Windows NewsFlow 앱과 별도로 운영하며 로그인 코드 교환·토큰 검증·계정 선택만 담당합니다. MP4 저장·전송·Reels 게시 엔드포인트는 없습니다. 실제 배포·로그인·외부 요청은 별도 승인 후 수행합니다.

## Meta 앱 준비

- Meta Business 유형 앱에 Facebook Login for Business와 Instagram API with Facebook Login을 설정합니다.
- **User access token** 구성을 만들고 `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` 권한을 선택합니다. 시스템 사용자 토큰이나 Instagram Login 토큰을 혼용하지 않습니다.
- 실제 공개 HTTPS 도메인을 준비하고 유효한 OAuth redirect를 정확히 `https://<인증 도메인>/oauth/callback`으로 등록합니다. Strict Redirect URI Matching과 HTTPS를 유지합니다.
- Instagram Business/Creator 계정이 Facebook 페이지에 연결되어 있어야 하며 로그인 사용자가 해당 페이지의 콘텐츠 작성 또는 전체 관리 권한을 가져야 합니다.
- 직접 소유·관리하고 앱 역할이 있는 계정의 개발 검증은 Standard Access 범위입니다. 다른 사용자 계정에 배포하려면 필요한 권한의 Advanced Access, Meta App Review와 Business Verification을 준비합니다. 일부 계정의 Business Manager 권한·Page Publishing Authorization 조건은 실제 앱 심사와 계정에서 별도로 확인합니다.
- 일반 Facebook 문서의 오래된 데스크톱 implicit/token 예제는 이 경로에 추가하지 않습니다. 코드 교환에 사용하는 공유 App Secret은 Windows 배포본에 포함하지 않습니다.

## 서버 설정과 시작

기존 프로젝트 의존성을 설치한 **별도 인증 서버**에서 다음 환경변수를 설정합니다.

| 서버 환경변수 | 값 |
| --- | --- |
| `NEWSFLOW_META_RELAY_ORIGIN` | 경로 없는 실제 공개 HTTPS origin. 예: `https://auth.example.com` |
| `NEWSFLOW_META_APP_ID` | Meta 앱 ID |
| `NEWSFLOW_META_CONFIG_ID` | 최소 권한의 Facebook Login for Business 구성 ID |
| `NEWSFLOW_META_APP_SECRET` | 서버의 비밀 관리 기능으로 주입한 App Secret |

App Secret을 저장소, 명령행 인수, 터미널 기록, 브라우저 또는 Windows 클라이언트 설정에 넣지 않습니다. 아래 명령은 해당 환경변수가 이미 안전하게 주입된 서버에서 실행하는 예입니다.

```powershell
python -m uvicorn newsflow.oauth.relay_server:create_relay_app --factory `
  --host 127.0.0.1 --port 8443 --workers 1 `
  --ssl-certfile C:\NewsFlowRelay\tls\fullchain.pem `
  --ssl-keyfile C:\NewsFlowRelay\tls\privatekey.pem `
  --no-access-log --no-proxy-headers
```

인증서·도메인·외부 HTTPS 443 연결은 서버 운영자가 준비합니다. 앞단 프록시를 사용한다면 중계까지 TLS를 유지하고 원래 공개 `Host`를 전달해야 합니다. `X-Forwarded-Proto`로 HTTP 요청을 HTTPS처럼 표시하는 구성은 지원하지 않습니다. 이 명령만으로 인터넷 공개·DNS·방화벽 설정을 자동 변경하지 않습니다.

**로그 보호가 배포 필수 조건입니다.** 중계와 앞단 프록시의 인증 경로 access log를 끄고, URL query·Authorization header·요청/응답 body를 APM·에러 수집·HTTP 디버그 로그에 기록하지 않습니다. 브라우저 callback에는 일회용 code/state가 있습니다. 서버는 이를 ASGI access-log용 query에서 제거하지만 앞단 프록시 기록은 서버 운영자가 별도로 차단해야 합니다.

Meta 공식 `debug_token` 검증은 서버 내부의 고정 `graph.facebook.com` HTTPS 요청에 `input_token` query를 요구합니다. 이는 브라우저나 중계 API URL에 포함되지 않으며, 이 업스트림 URL 또한 로그·트레이싱에 남겨서는 안 됩니다. App Secret은 코드 교환 POST body 또는 서버 내부 인증 헤더에만 사용합니다.

## 클라이언트 연결 계약

1. Windows 앱이 메모리에만 보관하는 무작위 verifier를 만들고 SHA-256 challenge로 `POST /v1/sessions`를 호출합니다.
2. 중계가 반환한 공식 Facebook 로그인 URL을 시스템 브라우저로 엽니다. 브라우저에는 토큰이 반환되지 않습니다.
3. 중계는 state를 먼저 1회 소비하고 코드 교환, `debug_token`의 앱·사용자·유효기간 검증, 권한·Page 조회를 수행합니다. 실패·시간 초과 시 재시도하지 않습니다.
4. Windows 앱은 verifier를 Authorization Bearer 헤더에 보내 상태를 확인합니다. 상태 조회 자체는 Meta를 호출하지 않습니다.
5. 사용자가 연결할 Page/Instagram 계정을 선택하면 `POST /v1/sessions/{id}/redeem`으로 한 번만 인증 결과를 가져옵니다. Windows 앱이 기존 계정 확인·DPAPI 저장 절차를 이어갑니다.
6. 취소는 `DELETE /v1/sessions/{id}`입니다. 취소가 확인되면 후속 인증 요청과 토큰 전달을 중단합니다. 이미 진행 중인 네트워크 요청을 공급사에서 취소했다고 주장하지 않습니다.

세션은 최대 10분 동안 서버 메모리에만 존재합니다. 한 프로세스·한 worker로 실행하며 서버 재시작·세션 만료는 새 사용자 로그인 준비가 필요합니다. 수신 결과를 잃어도 소비한 코드나 토큰 전달 요청을 자동 재전송하지 않습니다. 세션 생성은 IP별 분당 10회·동시 100개로 제한됩니다. 계정 선택은 최초 응답의 최대 100개 Page만 제공합니다.

## 검증 범위

Fake 전송으로 앱 ID·권한·계정 확인, 코드와 결과의 1회 처리, 취소, 만료, 결과 불명, HTTPS 경계와 비밀값 비노출을 검증합니다. 서버 배포, 실제 Meta 로그인·토큰 교환, 앱 심사, 운영 계정 Reels 게시는 이 검증으로 완료되지 않습니다.

공식 자료: [Facebook Login for Business](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business), [로그인 코드 흐름](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow), [로그인 보안](https://developers.facebook.com/documentation/facebook-login/security), [Instagram 플랫폼 개요](https://developers.facebook.com/documentation/instagram-platform/overview).
