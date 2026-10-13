# SNS 게시 공식 API 조사 및 Phase 4A 준비 기준

확인 날짜: **2026-10-13 UTC**. 이 문서는 실제 SNS 계정 연결이나 게시를 승인하지 않는다.
Phase 4A는 로컬 MP4의 준비 상태를 검증하고 Fake Publisher로 상태 전이를 시험한다.
SNS 인증·게시 요청은 **0건**이다. 조사에 사용한 요청은 공개 공식 문서와 공식 공급자 GitHub 파일의 읽기 요청이다.

## 조사 결과와 검증 범위

Google/Meta 공식 웹 문서 12개에 HTTPS로 접근했지만 Codex Cloud의 기존 프록시가
CONNECT 요청을 **403 Forbidden**으로 거절했다. 프록시, DNS, TLS, 허용 목록을 변경하지 않았다.
따라서 웹 문서의 최신 본문과 계정별 제한은 **NOT VERIFIED**다. 접속 실패를 문서상 금지나 API 오류로 해석하지 않는다.

대신 Google/YouTube/Meta가 관리하는 공식 GitHub 파일을 기존 GitHub 접근 경로로 읽어
아래 API 구조를 확인했다. 이는 API 스키마 검증이며, 인증 성공·실제 업로드·콘텐츠 승인 검증이 아니다.
작은 근거 스냅샷과 접근 결과는
[publishing_official_sources.json](reports/phase4a_evidence/publishing_official_sources.json)에 기록한다.

| 항목 | 판정 | 직접 확인한 근거 |
| --- | --- | --- |
| YouTube 공식 동영상 업로드 | PASS | 공식 discovery의 `youtube.videos.insert`, POST `youtube/v3/videos`, media upload 지원 |
| YouTube 최소 업로드 권한 후보 | PASS | discovery와 YouTube 공식 예제가 `https://www.googleapis.com/auth/youtube.upload`를 사용 |
| YouTube AI 표시 필드 | PASS | 공식 `VideoStatus.containsSyntheticMedia` boolean |
| YouTube Shorts 전용 업로드 API | PASS | 읽은 공식 v3 discovery에서 Shorts 전용 업로드 메서드가 없고 동영상 업로드는 `videos.insert` |
| Shorts 최신 자동 분류 조건·정책 | NOT VERIFIED | 공식 지원 문서 본문 접근 실패; discovery에 분류 조건 없음 |
| Instagram 게시 컨테이너·게시 API 구조 | PASS | Meta 공식 SDK의 POST `/media`, POST `/media_publish` 및 `creation_id` |
| Instagram 소재·AI 표시 매개변수 | PASS | `/media`에 `video_url`, `upload_type`, `is_ai_generated`가 정의됨 |
| Instagram 게시 한도 조회 구조 | PASS | GET `/content_publishing_limit`, `config`와 `quota_usage` 응답 필드 |
| Instagram 최신 계정 자격·OAuth 권한·게시 제한 | NOT VERIFIED | 공식 웹 문서 본문 접근 실패; SDK는 자격·권한·수치의 근거가 아님 |
| Instagram Login 경로의 AI 표시 적용 범위 | NOT VERIFIED | Business SDK 필드 존재와 별개로 해당 로그인 경로의 최신 지원 범위 확인 필요 |
| 실제 토큰·계정·SNS 게시 | NOT VERIFIED | 이번 단계의 금지 범위이며 실행하지 않음 |

## YouTube Shorts

### 확인한 공식 API

- 공식 스키마: [google-api-python-client YouTube v3 discovery](https://github.com/googleapis/google-api-python-client/blob/19fd51d1d18446206091a21eec763057d032c2b3/googleapiclient/discovery_cache/documents/youtube.v3.json).
  읽은 discovery revision은 `20261001`, 해당 파일 최신 변경일은 `2026-10-06`이다.
- 업로드는 `videos.insert`이며 simple/multipart 및 resumable media upload 구조가 있다.
  스키마의 media 최대 크기는 `274877906944` bytes(256 GiB), 허용 MIME은 `video/*`, `application/octet-stream`이다.
  이는 API 파일 크기 상한이며 Shorts의 길이·분류·계정 자격을 보장하지 않는다.
- [YouTube 공식 업로드 예제](https://github.com/youtube/api-samples/blob/master/python/upload_video.py)는
  인증한 사용자의 채널 업로드에 `youtube.upload` scope와 `videos().insert(...)`를 사용한다.
  예제는 오래된 코드이므로 그 인증 UI·Python 문법·재시도 구현을 제품 코드에 복사하지 않는다.
- `VideoStatus`에 `privacyStatus`(`public`, `unlisted`, `private`),
  `selfDeclaredMadeForKids`, `containsSyntheticMedia`가 있다.
  AI 표시 값은 사람의 사실적인 변경·합성 여부 검토 결과를 반영해야 한다.
  대본이 AI로 생성되었다는 사실 하나만으로 플랫폼의 표시 의무 판단을 완료하지 않는다.
- `VideoStatus.uploadStatus`는 `uploaded`와 `processed`를 구분하고 `failed`/`rejected`도 제공한다.
  추후 업로드 요청 수락과 최종 처리 성공을 다른 상태로 관리해야 한다.

### 재확인해야 하는 공식 웹 문서

| 공식 URL | 확인할 내용 | 2026-10-13 접근 |
| --- | --- | --- |
| https://developers.google.com/youtube/v3/docs/videos/insert | 필수 입력, 업로드 quota, 미검증 API 프로젝트의 공개 범위 제한, 오류 | 프록시 CONNECT 403 |
| https://developers.google.com/youtube/v3/docs/videos | 제목·설명·태그 한도, AI 표시 및 개인정보 필드 의미 | 프록시 CONNECT 403 |
| https://developers.google.com/youtube/v3/guides/auth/installed-apps | Windows 데스크톱 공식 OAuth, redirect/PKCE/offline 권한 | 프록시 CONNECT 403 |
| https://developers.google.com/youtube/v3/determine_quota_cost | 업로드 요청 비용·일일 할당량 | 프록시 CONNECT 403 |
| https://support.google.com/youtube/answer/15424877?hl=en | 세로·정방형, 업로드 날짜, 길이에 따른 Shorts 분류와 Content ID 제한 | 프록시 CONNECT 403 |
| https://support.google.com/youtube/answer/1722171?hl=en | MP4/H.264/AAC 등의 권장 인코딩 | 프록시 CONNECT 403 |
| https://support.google.com/youtube/answer/14328491?hl=en | 사실적으로 변경·합성한 콘텐츠 공개 의무와 예외 | 프록시 CONNECT 403 |

30/45/60초 1080×1920 MP4가 내부 영상 프로파일을 통과해도 **YouTube Shorts 분류를 보장하지 않는다**.
`#Shorts`나 별도의 가상 업로드 API를 Shorts 분류 보증으로 사용하지 않는다.
조회수·정책 승인·공개 업로드 가능 여부도 로컬 검증으로 확인할 수 없다.

## Instagram Reels

### 확인한 공식 API 구조

[Meta Business SDK `iguser.py`](https://github.com/facebook/facebook-python-business-sdk/blob/788f363d15b1269ab5efb7cd00fb5e3b133cd99b/facebook_business/adobjects/iguser.py)는
Meta가 생성·관리하는 공식 SDK 파일이다. 해당 파일 최신 변경일은 `2026-08-25`다.

- `create_media`: POST `/media`; `caption`, `media_type`, `video_url`, `upload_type`,
  `share_to_feed`, `is_ai_generated`(boolean) 등이 정의되어 있다.
- `create_media_publish`: POST `/media_publish`; `creation_id`를 받아 별도 게시 단계를 실행한다.
- `get_content_publishing_limit`: GET `/content_publishing_limit`;
  [공식 응답 모델](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/contentpublishinglimitresponse.py)의
  필드는 `config`와 `quota_usage`다. SDK에는 일일 제한 수치가 없으므로 고정된 최신 한도를 주장하지 않는다.

`video_url`이 있는 사실만으로 모든 업로드 방식에 공개 URL이 필수라고 단정할 수 없다.
`upload_type`도 확인되어 공식 resumable 전송 지원 여부를 해당 로그인 경로·API 버전별로 재조사해야 한다.
Phase 4A는 로컬 영상 URL을 생성·공개하지 않고, 파일을 외부 저장소에 전송하거나 터널을 열지 않는다.
URL 방식의 검증을 추후 구현한다면 Meta가 다운로드할 수 있는 제공 방식·HTTPS·리다이렉트·유효기간·접근제어를 먼저 확인해야 한다.
OAuth 토큰이 URL 쿼리나 공개 영상 링크에 포함되어서는 안 된다.

### 로그인 경로와 계정 자격의 재확인

Instagram Login과 Facebook Login의 권한명·계정 요구사항을 섞어서 사용하지 않는다.
아래는 Phase 4B 조사 대상이며, 이번 Cloud에서 최신 공식 본문을 읽지 못했으므로 **검증된 계정 연결 설정이 아니다**.

| 경로 | 공식 문서 | 반드시 재확인할 사항 |
| --- | --- | --- |
| Instagram API with Instagram Login | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login | professional(비즈니스/크리에이터) 계정 지원, Facebook Page 연결 요구 여부, 지원 API 버전 |
| Instagram Login content publishing | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing | `instagram_business_basic` 및 `instagram_business_content_publish`의 현재 이름·최소 필요 범위, 앱 검수·권한 레벨, AI 표시·미디어 전송 방식 |
| Facebook Login content publishing | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/content-publishing | professional 계정과 연결 Page 자격, `instagram_basic`/`instagram_content_publish` 및 필요한 Page 권한, 앱 검수·역할 |
| 공통 publishing 문서 | https://developers.facebook.com/docs/instagram-platform/content-publishing | Reels `media_type`, 컨테이너 상태·유효기간, 분량·크기·프레임레이트·오디오·캡션·해시태그 한도, 현재 게시 제한 |
| Meta AI 표시 정책 | https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/ | 사람이 신고해야 하는 생성·변경 미디어와 표시 방식, 최신 후속 정책 |

위 다섯 URL 모두 `2026-10-13` 프록시 CONNECT 403으로 본문을 확인하지 못했다.
기존 권한명 후보나 과거 게시 제한 수치를 곧바로 실행 설정으로 확정하지 않는다.
Business SDK의 `is_ai_generated`를 Instagram Login 경로에서 실제로 적용할 수 있는지도 별도 검증한다.

## Phase 4A 앱 준비 프로파일과 플랫폼 보증의 구분

내부 프로파일은 Phase 3에서 만든 **30/45/60초, 1080×1920, H.264 MP4**를 기반으로 한다.
파일 무결성, 실제 ffprobe 결과, 제목·설명·해시태그, 출처·저작권 확인, AI 표시 검토,
콘텐츠 사람 검토, 계정/권한/API 준비 상태를 각각 검사한다.
이는 앱의 보수적인 품질 기준이며 최신 플랫폼의 모든 승인 요건을 검증한 목록이 아니다.

계정 미연결, 공식 정책 재확인 미완료, 승인 미완료 또는 검증 실패가 있으면 실제 게시 가능으로 표시하지 않는다.
Fake 성공은 **모의 실행 성공**으로만 기록하며 실제 SNS `SUCCESS`나 원격 게시 ID를 만들지 않는다.
타임아웃으로 결과를 알 수 없으면 `UNKNOWN`으로 보존하고 자동 재시도하지 않는다.

텍스트 예산도 **앱의 준비 프로파일**이다. 현재 Instagram용으로 제목·설명·해시태그를 합친
캡션에 2,200자, 해시태그에 최대 30개를 적용한다. YouTube용 준비 텍스트 예산은 5,000자다.
이 수치를 최신 공식 플랫폼 제한이라고 표시하지 않는다. 플랫폼이 사용하는 byte 수,
태그별 계산 방식·현재 해시태그 정책은 공식 본문을 읽은 후 별도로 확인해야 한다.
내부 검사를 통과해도 계정/API/정책 상태가 미검증이면 게시 가능 상태가 되지 않는다.

## OAuth 및 토큰 보호 설계

### Phase 4A의 차단 경계

- 공식 Instagram/YouTube Adapter에는 HTTP 게시 transport와 실행 가능한 OAuth callback이 없다.
  `connect()`/`publish()`는 사용자 승인 인수의 값과 관계없이 실제 연결·게시를 거부한다.
- `Phase4AUnavailableCredentialVault`는 실제 access/refresh token의 저장·조회를 거부하는
  자격증명 저장소 경계다. GUI, 일반 DB, Git 파일, 실행 인수로 실제 토큰을 전달하지 않는다.
- Fake credential vault는 테스트용 합성 토큰을 메모리에만 보관한다. 토큰 객체의 `repr`은
  값을 숨기며 파일/DB/HTML로 직렬화하지 않는다. 이것은 Windows 비밀 저장소 검증이 아니다.
- `PlatformAccount`에는 플랫폼, 익명 또는 로컬 계정 식별자, scope·상태·만료 시각과 같은
  공개 가능한 메타데이터만 저장한다. 토큰을 저장할 경우의 향후 DB 값은 비밀 원문 대신
  전용 저장소의 불투명 참조만 사용해야 한다.
- 만료·취소·인증 오류 상태에서는 검증을 차단한다. 현재 만료/취소 처리는 합성 데이터 테스트이며
  실제 OAuth 공급자의 refresh/revoke 요청은 **NOT VERIFIED**다.

### Phase 4B에 필요한 공식 인증 흐름

아래는 구현 승인 전의 **설계 조건**이다. Phase 4A에서 인증 브라우저를 열거나
callback을 수신하거나 사용자를 로그인시키지 않는다.

1. 사용자에게 실제 계정 연결에 대한 명시적 동의를 받은 뒤 공급자의 공식 브라우저 OAuth
   authorization flow를 사용한다. 비밀번호 수집, 브라우저 자동 로그인, 비공식 쿠키·세션 인증을 금지한다.
2. Public desktop client는 공급자가 지원하는 PKCE `S256`을 사용하고, 매 실행마다 충분한
   난수 `state`를 생성·비교한다. 짧은 유효기간, 한 번만 사용하는 code/state, 정확히 등록된
   loopback callback URI를 검증한다. 공급자별 native-app/redirect 지원은 공식 문서에서 재확인한다.
   GUI의 기존 CSRF 검사는 유지하며 OAuth `state` 검증으로 GUI CSRF 검사를 대체하지 않는다.
3. YouTube 업로드에는 공식 discovery/예제에서 확인한 `youtube.upload`를 최소 권한 후보로 둔다.
   채널 정보 조회나 추가 동작에 더 넓은 권한이 필요하면 그 이유를 사용자에게 제시하고 별도 동의를 받는다.
   Instagram은 로그인 경로별 현재 scope가 **NOT VERIFIED**이므로 기존 이름 후보를
   승인된 실제 권한 목록으로 사용하지 않는다.
4. Windows에서는 **Credential Manager 또는 DPAPI 기반 전용 저장소**를 검토한다.
   이는 Phase 4B 계획이며 이번 단계에 구현·검증한 기능이 아니다. 앱 단위 접근,
   현재 Windows 사용자에 대한 보호, 암호화·삭제·백업·계정 전환을 확인해야 한다.
   `%LOCALAPPDATA%` 아래 일반 JSON이나 SQLite에 토큰을 평문 저장하지 않는다.
5. Access/refresh token, authorization code, client secret은 Git·로그·HTML·URL 쿼리·오류 메시지에
   노출하지 않는다. 오류를 고정된 유형으로 변환하고 HTTP 응답/요청을 원문으로 기록하지 않는다.
6. 만료 시각·실제 granted scope·동의 취소 상태를 검증한다. Refresh는 승인된 grant와
   공급자의 공식 endpoint에 한정하며, refresh 실패·revocation 이후에는 재인증을 요구한다.
   게시 작업의 결과가 불명인 상태에서 토큰을 갱신했다는 이유로 자동 재게시하지 않는다.
7. 로컬 요청의 중복 식별자와 원격 세션/컨테이너/게시 ID를 연결한다. 네트워크 타임아웃은
   게시 실패 확정이 아니라 `UNKNOWN`일 수 있으므로 자동 신규 업로드·재게시를 금지한다.
   공급자의 상태 조회를 통한 조정 절차와 사람의 확인을 먼저 수행한다.
8. YouTube OAuth 앱 검증 및 업로드 프로젝트 감사·공개 범위·quota, Instagram 앱 검수·권한 레벨·
   대상 계정 자격·한도를 확인한다. Shorts 자동 분류와 AI 표시 정책도 최신 공식 문서로 재확인한다.

## Phase 4B 실계정 연동 선행 조건

1. 사용자에게 실제 계정 연결 및 별도의 실제 게시 범위 승인을 받는다.
2. 접근 가능한 환경에서 위 공식 정책 본문을 다시 확인하고 확인 날짜·API 버전을 고정한다.
3. 플랫폼별 계정 자격, 앱 심사·검증, 최소 OAuth scope, 사용량/게시 한도를 실제 대상 계정 기준으로 확인한다.
4. Windows 로컬 비밀 저장소, OAuth `state`/PKCE/정확한 callback, 토큰 만료·취소·refresh 처리의 보안 검토를 완료한다.
5. Instagram의 승인된 미디어 제공 방식과 YouTube의 resumable 업로드·처리 완료 확인을 설계한다.
6. 출처·저작권·사실 확인·AI 표시 및 아동 대상 여부를 사람이 검토한다.
7. 중복 식별자와 원격 작업/게시 ID를 통한 결과 조정 절차를 마련하고 결과 불명 작업을 자동 재게시하지 않는다.

Phase 4A 종료 시점에는 이러한 실계정 검증이 **NOT VERIFIED**이며 Phase 4B 실행 권한이 없다.
