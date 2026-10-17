# 핵심 제작·게시 A — YouTube

## 구현

- 통합 브랜치 `codex/newsflow-core-production`. PR #33의 `58c474c` 뒤에 있는 로컬 진단 `493daf1`, 사용량 처리 `a6cbc2d` 이력을 그대로 보존한다. 기존 PR/main을 변경하거나 병합하지 않는다.
- 설정에서 Google Desktop OAuth JSON을 DPAPI로 저장하고 공식 시스템 브라우저 로그인, PKCE·일회용 loopback callback, 채널 확인을 수행하는 실제 실행 경로를 연결했다. 토큰과 앱 설정은 별도 암호문이며 DB·오류 화면에는 저장하지 않는다.
- 작업실의 기존 완성 영상 → 게시하기 → 내용·출처·권리 검토 → 채널·제목·설명·해시태그 → 공개 상태·아동용 여부 → 명시적 업로드 동의로 연결한다. 기본값은 비공개이며 공개/일부 공개는 추가 동의가 필요하다.
- 기존 MP4/ffprobe·해시 검사와 게시 테이블을 재사용한다. 공식 resumable POST와 청크 PUT을 사용하며 영상 ID·링크·채널·파일 해시·결과를 기록한다. 업로드 세션 URL/토큰은 DB나 로그에 남기지 않는다.
- 같은 실제 채널+파일 해시는 중복 전송하지 않는다. 중단·시간 초과·결과 불명은 자동 재시도하지 않는다. 재시작은 기록만 복원하며 토큰 갱신/업로드를 자동 수행하지 않는다.
- 미지원 VERIFIED는 기본 선택에서 숨겼다. 기존 AI 분석·대본, 음성, FFmpeg, 모델/계정 설정, 과거 로컬 기능은 그대로 재사용한다. 새 migration은 없다.

## 검증과 보존

- 새 OAuth·업로드·게시 이력·GUI 테스트 95개를 Fake와 임시 DB로 검증했다. 실제 Windows DPAPI 저장·복호화는 가짜 자격증명으로 확인했다. 기존 callback/activation/protocol 관련 174개도 통과했다.
- [최종 Windows CI 1회](https://github.com/jsbae1979-prog/JSBAE/actions/runs/39001611964): Python 3.12/3.14 각각 **189 PASS**, Ruff·pip check PASS. 테스트한 구현 SHA는 `0b2ce83a4b527c36f905958d2c382c9b2cdf3766`이며 이후 변경은 이 보고서의 결과 기록뿐이다. [통합 Draft PR #34](https://github.com/jsbae1979-prog/JSBAE/pull/34).
- Ruff·pip check 통과. 실제 OAuth·Google 업로드·유료 AI·CLI 인증/추론 호출은 0건이다.
- 별도 `127.0.0.1:8794` 서버에서 합성 계정·합성 영상 레코드로 설정 표시, 필수 검토, 같은 게시 패널 복귀, 비공개 기본값·게시 동의 화면을 확인했다. 앱 내 브라우저를 사용했으며 Chrome 연결 및 실제 MP4 재생을 이번 검증으로 대체하지 않는다.
- 화면 캡처는 로컬 `validation-output/youtube-core-ui-20261017/settings.png`, `publish.png`에 보관하며 Git에 포함하지 않는다.
- 운영 서버/데이터 경로는 변경·재시작하지 않았다. 사용자 DB/API Key/토큰/MP4/과거 사용량·예약 기록을 수정하지 않았다. 사용자 콘텐츠 대신 새 테스트 DB와 합성 바이트만 사용했다.

## 실제 사용 전 필요한 조건

Google Cloud 프로젝트에 YouTube Data API 활성화, Desktop OAuth 클라이언트와 동의 화면/테스트 사용자 설정, 게시할 YouTube 채널이 필요하다. 사용자가 Google에서 직접 권한을 승인한 후, 별도 승인된 비공개 영상 한 건으로 실제 계정·할당량·업로드·재생을 확인해야 한다. 이 단계는 **NOT VERIFIED**다. 계정 연결 성공만으로 실게시 성공을 표시하지 않는다.

새 운영 코드 적용은 같은 데이터 경로로 정상 재시작한 뒤 가능하다. 이번 작업에서 운영 앱을 재시작하지 않았다. 업로드 결과가 불명확하면 YouTube Studio에서 확인해야 하며 앱이 임의 재전송하지 않는다. Shorts 분류와 영상 후처리 완료는 공급사가 결정한다.

## 남은 핵심 작업

B Instagram과 C 양 플랫폼 통합/예약 게시가 아직 완료되지 않았으므로 프로그램 전체 완성을 선언하지 않는다. 하나의 통합 브랜치·Draft PR에서 이어간다. Meta 공식 문서상 로컬 파일 resumable 업로드는 Facebook Login for Business 경로의 Page 연결된 프로 계정을 대상으로 한다. 일반 배포용 인증은 등록된 HTTPS redirect 및 app secret 보호 조건을 해결해야 하며, 영상 보관용 클라우드 서버를 먼저 만들 필요는 없다.

공식 계약: [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [YouTube resumable 업로드](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol), [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [Meta Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/).
