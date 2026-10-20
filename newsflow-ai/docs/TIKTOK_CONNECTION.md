# TikTok Desktop 앱 연동

확인일: **2026-10-20 KST**. 최종 운영 환경은 Windows 11입니다.

## 현재 사용할 수 있는 범위

설정 → 게시 계정 → 추가 플랫폼 → TikTok에서 Desktop 앱 정보 등록과 연결 상태를 확인합니다.
Client key/secret은 기존 Windows 현재 사용자 DPAPI 방식의 별도 파일에 저장하며, 화면에 다시 표시하지 않습니다.
앱 설정 저장은 로그인이나 게시 승인이 아닙니다.

Desktop Login Kit의 브라우저 시작, loopback callback, 코드 교환, 계정 확인, 갱신·해제 코드가 있습니다.
현재 배포 기본값은 **실계정 인증·토큰 취급·게시 차단**입니다. 환경변수·동의 체크박스로 해제되지 않습니다.
Fake 인증은 명시적으로 주입한 합성 환경에서만 가능하며 실제 계정 연결로 표시하지 않습니다.
기존 TikTok 게시 엔진과 합성 계정 연결을 통합 검증하지만 운영 게시 전송에는 연결하지 않았습니다.
지금 실제 TikTok에 올리려면 완성 MP4를 내려받아 TikTok의 공식 웹/앱에서 직접 업로드하세요.

## 공식 문서와 구현 계약

| 항목 | 공식 근거 및 적용 |
|---|---|
| Desktop 인증 | [Login Kit Desktop](https://developers.tiktok.com/doc/login-kit-desktop). `https://www.tiktok.com/v2/auth/authorize/`, Authorization Code, `client_key`, state, PKCE S256. |
| PKCE | 같은 문서의 **SHA256 hex** 지침을 따른 별도 구현. Google의 base64url S256 코드를 복제하지 않음. 실제 TikTok 서버 수용 여부는 NOT VERIFIED. |
| callback | Desktop 문서의 localhost/127.0.0.1 및 wildcard 포트 허용. 이 앱은 **127.0.0.1만** 바인딩. 기본 `http://127.0.0.1:*/oauth/tiktok/callback/` 등록, 실제 인증에는 선택된 숫자 포트를 사용. 고정 포트 1024–65535도 지원하되 앱 포트8765 제외. |
| scope | 계정 확인 `user.info.basic`, 기존 Direct Post 연결용 `video.publish` 두 개만 요청. 승인 범위가 줄거나 예상 밖이면 중단. |
| 교환·갱신·회수 | [User access token management](https://developers.tiktok.com/doc/oauth-user-access-token-management). `/v2/oauth/token/`, `/v2/oauth/revoke/`, form POST. 문서의 access24시간/refresh365일 응답 수명을 검증하고 실제 반환 만료시각 저장. |
| 계정 | [User info](https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info). `open_id,display_name` 조회, grant의 open_id와 동일해야 연결 완료. |
| 게시 심사 | [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines). 광범위한 사용자 대상 앱이어야 함. “A utility tool to help upload contents to the account(s) you or your team manages.”는 부적합 사용례로 명시. |

공식 공개 문서 GET만 수행했습니다. 문서를 읽은 결과는 실제 앱 심사·인증·게시 성공을 의미하지 않습니다.

## 운영 활성화 전 준비

1. 앱의 이용 대상/목적이 Content Posting API 심사 정책에 적합한지 확인합니다. 개인·팀 전용 업로드 용도를 심사 가능한 앱으로 임의 간주하지 않습니다.
2. TikTok for Developers에서 Desktop 앱, Login Kit, 필요한 권한과 정확한 redirect를 등록하고 필요한 심사를 받습니다.
3. Client secret을 공개 소스·다운로드 ZIP·공유 배포본에 넣지 않습니다. 이 구현은 사용자 자신이 제공한 앱 정보를 Windows에 암호화해 저장합니다. **공용 앱의 비밀값을 일반 사용자에게 배포하는 방식은 지원하지 않으며, 다중 사용자 배포의 비밀값 관리 구조는 별도 보안 검토가 필요합니다.**
4. 합성 데이터로 Windows Python3.12/3.14, 네이티브 DPAPI, 실제 시스템 브라우저/포트 충돌/콜백을 먼저 검증합니다.
5. 별도의 운영 활성화 코드 검토와 사용자 승인을 거친 다음에만 실제 인증을 시험합니다. 현재 `production_enabled()`는 False이며, 게시 서비스도 기존 BlockedTransport를 유지합니다.
6. 실제 업로드는 인증과 별개입니다. 최신 creator_info의 공개 범위·길이·상호작용 옵션, 영상/출처/권리 검토, 음악·브랜드 동의, AI 표시와 이번 게시 승인을 확인해야 합니다. 무인 예약 게시는 지원하지 않습니다.

## 안전·복구 구조

- 실제 앱의8765와 별도의 일시적 loopback 포트를 사용합니다. 지정 포트 충돌은 오류로 반환하며 임의 고정 포트 변경을 하지 않습니다.
- 정확한 Host/path, state, callback 일회성, 만료, query 중복, Origin/body/외부 redirect를 검증합니다. 코드·state는 callback 응답이나 서버 로그에 넣지 않습니다.
- 코드 교환·갱신·해제는 고정 HTTPS 주소, 인증서 검증,20초 타임아웃,64KiB 응답 제한. POST 재시도/redirect/다른 제공자 전환 없음.
- Client secret은 `tiktok-desktop-client.dpapi`, 토큰은 별도 `tiktok-oauth/` 현재 사용자 DPAPI 공간. DB에는 계정 ID·권한·만료시각·암호문 reference·처리 상태만 저장합니다.
- SQLite 기존 PlatformAccount/OAuthConnection/OAuthIdentityBinding/OAuthLifecycleOperation 재사용. **새 migration 없음.** 기존 YouTube/Instagram 계정 키 검증 기본값 유지.
- 작업 선점 및 revision CAS → 작업 journal → 새 암호문 쓰기·복호화 확인 → DB pointer 전환. 계정/앱 identity 불일치는 연결 거절.
- 갱신·회수 중 timeout/종료/저장 실패는 성공으로 처리하지 않습니다. 이전 포인터·암호문을 보존하되 게시 준비를 차단합니다. 재시작은 미완료 작업을 결과 불명으로 전환하며 네트워크를 재실행하지 않습니다.
- 회수 성공 후 DB 참조를 해제합니다. 회전 전/실패 중 남은 암호문은 자동 삭제하지 않습니다. 안전한 고아 파일 정리 도구는 이번 범위에서 구현하지 않았습니다.
- Python 메모리의 모든 immutable secret 문자열을 완전 소거한다고 보장하지 않습니다. DB/HTML/진단·예외 응답 비노출을 검증합니다.

## 격리 검증 명령

프로젝트 전용 venv에서 실행하며 사용자 운영 앱·DB·키는 사용하지 않습니다.

```bat
.venv\Scripts\python -m pytest -q -rs tests/test_tiktok_connection.py tests/test_tiktok_gui.py tests/test_tiktok_publishing_connection.py
```

GUI 테스트에는 기존 Playwright와 Chrome 설치가 필요합니다. Windows 테스트는 실제 Windows에서만 PASS로 기록하세요.
Cloud에서는 `NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium`을 명시해 로컬 Chromium으로 확인합니다.
테스트는 합성 앱 key/secret, 합성 계정·토큰, 임시 SQLite·파일, Fake HTTPS 응답만 사용합니다.
Native Windows DPAPI 테스트만 Windows 외 환경에서 명시적으로 skip합니다.
