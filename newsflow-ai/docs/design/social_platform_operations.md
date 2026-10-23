# 네 플랫폼 게시·성과·캘린더 설계

확인일: 2026-10-19 KST. 적용 기준: `8b2295f` 이후 로컬 확장. 사용자 “모두 진행” 승인에 따라 화면 일치 범위 검토안의 1~5단계를 구현한다. 실계정 실행 승인과 구분한다.

## 재사용 및 데이터 경계

- `PublishingService`의 MP4 경로/해시/ffprobe, 출처·저작권·내용·AI 표시 검사 유지.
- `UnifiedPublishingService`의 검토 snapshot, 승인 digest, 플랫폼별 claim 및 append-only evidence를 확장. YouTube/Instagram 전송·인증 엔진을 다시 작성하지 않는다.
- `ExtendedPublishingService`: TikTok/Facebook 대상에 기존 PublishDraft/PublishJob/PublishAttempt/PublishEvidence를 사용. 계정 identity는 검토 시 고정하고 실행 직전 재비교. 동시 claim은 SQLite write transaction과 unique idempotency key로 보호.
- 신규 migration **0014**: `publish_schedules`, `social_metrics`, `social_metric_runs`. 기존 0001~0013 내용 변경 없음. 데이터 복사 도구의 지원 버전만 추가하고 복사본의 armed 게시 예약은 paused/승인 해제, running은 unknown으로 보존.
- DB에 token, secret, 임시 upload URL을 저장하지 않는다. 업로드 URL에 포함된 capability는 메모리에서만 사용한다. 오류는 고정 문구로 반환한다.
- 새 운영 인증 연결은 구현·활성화하지 않는다. 기존 YouTube/Instagram 경로는 유지한다. 새 플랫폼에는 합성 계정 binding만 주입 가능하며 실제 grant는 fail-closed다.

## 공식 문서 조사

아래 URL은 실제 GET으로 확인했다. 계정 조회·OAuth·게시 API 호출이 아니다. 공식 문서의 조건 확인은 실제 계정 자격/심사/공급사 동작 검증과 다르다.

| 영역 | 공식 근거 | 확인 내용 |
|---|---|---|
| TikTok Direct Post | https://developers.tiktok.com/doc/content-posting-api-reference-direct-post | `video.publish`, POST `/v2/post/publish/video/init/`, FILE_UPLOAD, publish_id와 임시 upload_url, AI 표시·브랜드 공개 항목 |
| TikTok 정책 | https://developers.tiktok.com/doc/content-sharing-guidelines | 미심사 앱 private/SELF_ONLY 및 사용자 수 제한. **자신/팀 계정만을 위한 내부 업로드 도구는 허용되지 않는 예시**. 현재 NewsFlowAI의 운영 형태가 공개 심사에 적합한지 확인 필요 |
| TikTok creator | https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info | 게시 전 최신 creator 조건 조회, 선택 가능한 공개 범위, 최대 길이, 댓글/듀엣/스티치 제한 |
| TikTok 상태 | https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status | POST `/v2/post/publish/status/fetch/`; PROCESSING / PUBLISH_COMPLETE / FAILED. `publicaly_available_post_id` 원문 철자 유지. 비공개 게시에 public ID가 없으면 추정하지 않음 |
| TikTok 성과 | https://developers.tiktok.com/doc/tiktok-api-v2-video-query | `video.list`, 영상별 view_count/like_count/comment_count/share_count. 수익 API로 간주하지 않음 |
| TikTok Login Kit | https://developers.tiktok.com/doc/login-kit-web | 웹 로그인 승인·등록 redirect·서버 측 secret 관리가 필요한 별도 연동. Windows 바이너리에 client_secret 내장하지 않음 |
| Facebook Reels | https://developers.facebook.com/documentation/video-api/guides/reels-publishing | Page 전용, CREATE_CONTENT task, pages_show_list/pages_read_engagement/pages_manage_posts. start→local upload→finish→status. Page는 Public. 24시간 30회 제한. v26.0 |
| Facebook 영상 성과 | https://developers.facebook.com/docs/graph-api/reference/video/video_insights/ | 영상별 video_insights, total_video_views/total_video_views_unique. Page의 read_insights/pages_read_engagement와 실제 미디어 자격은 추가 확인 필요. 광고/수익 항목을 모든 Reels에 제공되는 것으로 가정하지 않음 |
| YouTube Analytics | https://developers.google.com/youtube/analytics/reference/reports/query | 공식 reports endpoint, youtube.readonly/yt-analytics.readonly. 금액은 별도 yt-analytics-monetary.readonly. 누락/지연 행을 0으로 보충하지 않음 |
| YouTube 지표 | https://developers.google.com/youtube/analytics/metrics | views, subscribersGained/Lost, estimatedRevenue. USD 공급사 추정 수익이며 확정 정산/매출과 구분 |
| Instagram Insights | https://developers.facebook.com/documentation/instagram-platform/insights | Facebook Login 경로의 instagram_manage_insights/instagram_basic/pages_read_engagement. Business Manager 역할에 따라 추가 ads 권한이 필요할 수 있음. 빈 결과는 0이 아님 |
| Instagram 미디어 지표 | https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights | v26.0 미디어 insights. views/reach/likes/comments/saved/shares 및 values/total_value 응답. 공급사 정의 보존 |

Facebook 공식 문서에는 upload_phase 표 일부에 `complete`, 실제 요청 예제에는 `finish`라는 불일치가 있다. 구현은 요청 예제의 `finish`를 사용하며 실제 공급사 호환성은 NOT VERIFIED다. 기존 Instagram 업로드 v25.0 코드는 변경하지 않는다.

## 어댑터 / HTTPS

`platforms.py`는 각 공식 요청·응답 계약을 구현한다. TikTok 공개 범위는 creator 응답에 있는 값만, 기본 선택 없음. 상호작용은 사용자가 켜야 하며 계정이 금지한 항목을 켤 수 없다. branded+SELF_ONLY 불가. Music Usage / Branded Content 동의를 별도로 확인한다. 단일 FILE_UPLOAD는 앱 내부 **64MiB 프로파일**로 제한하며 공급사의 전체 최대 규격이라고 표시하지 않는다.

Facebook은 Page ID와 공개 동의, CREATE_CONTENT task, scope와 최근 24시간 로컬 요청 수를 검사한다. 원격 서비스의 전체 rate limit도 따라야 한다. 승인되지 않은 외부 공개 URL이나 CDN 업로드는 만들지 않는다.

`official_transport.py`는 공식 HTTPS 호스트·경로·메서드 allowlist, 시스템 TLS 검증, 30초 timeout, 제한된 응답 읽기, 파일 streaming을 구현한다. redirect 및 자동 retry 없음. upload capability URL에 bearer를 추가하지 않는다. **`production_activation()`은 항상 False이며 GUI/환경변수로 바꿀 수 없다.** 테스트는 `nf-synthetic-` 문자열과 메모리 HTTP connection만 주입한다. 앱은 기본 `BlockedTransport`를 사용한다. HTTP 코드를 구현했다는 사실을 실제 계정 실행으로 표시하지 않는다.

추가 플랫폼 완료 상태는 `ext_simulated` → UI “합성 검증 완료”; 기존 실제 성공 상태로 바꾸지 않는다. 실패/불명 요청은 새 작업으로 자동 재생성하지 않는다. processing은 다음 명시적 클릭에서 상태만 조회한다. 성공한 플랫폼은 재전송하지 않는다.

## 게시 캘린더

- 기존 제작 scheduler와 별도 로컬 게시 계획. UI에서 날짜 선택, 저장, 재진입, 수정, 해제 가능. KST 입력/표시, DB UTC.
- 기본 paused. 일정 저장은 전송 승인이 아니다. 변경 시 예약 승인 삭제 및 revision 증가.
- 실제 예약 전송은 별도 운영 활성화 전까지 차단. UI에 동작하는 것처럼 보이는 활성화 버튼을 넣지 않는다.
- 합성 dispatcher로 승인→기한 도래→기존 unified 실행→플랫폼별 결과까지 검증 가능. 테스트 callback은 설정에서 주입할 수 없다.
- 승인 digest·미디어 hash·초안 revision·계정·공개 범위를 그대로 적용. 게시 시점에 재검증한다.
- 실행 중 죽으면 unknown. 앱 종료 중 지난 occurrence는 missed, 일괄 catch-up 없음. 실행 중 2분 grace 이후에도 missed. 자동 retry 없음.
- TikTok은 최신 계정 조건과 사용자 직접 선택이 필요한 정책 때문에 무인 예약 대상에서 제외한다.
- 같은 cohort에는 하나의 일정만 허용. 동시 revision CAS로 중복 실행 방지.

## 성과 / 추천

`AnalyticsAdapter`는 YouTube 일별 reports, Instagram/Facebook 미디어 insights, TikTok video/query를 분리한다. YouTube는 videos.list의 실제 채널 ID와 영상 소유권을 대조하고 publishedAt을 보존한다. 계정/게시 job/media ID 불일치·중복 binding을 거부한다.

- 공급사 지표명·단위·기간·시간 기준·수집 시각·합성 여부 저장. 값을 임의 추정하지 않는다.
- YouTube 날짜는 태평양 시간, Meta/TikTok 누적은 **수집일의 lifetime snapshot**. 누적을 일별 성과로 오인하거나 일자별로 중복 합산하지 않는다.
- 수익은 YouTube 별도 monetary scope의 estimatedRevenue만. 타 플랫폼 미지원 수익/구독자 지표를 0으로 만들지 않는다.
- 실패 시 기존 성과 보존, 오류 이력 기록, 자동 재시도 없음. 동일 기간 재조회는 해당 측정값 갱신, 중복 행 없음.
- 일반 화면에는 synthetic=False만 표시. 격리 preview만 synthetic=True를 명확히 표시한다.
- 추천은 **YouTube만** 지원: 동일 계정, 완전한 첫 7개 태평양 날짜의 views, 최소 영상 10개, 3개 이상 표본을 가진 시간대가 2개 이상. KST 시간대별 중앙값. 미래 성과 예측/인과 보장/외부 AI 호출 없음.
- 나머지 플랫폼은 동등한 관찰 기간 자료가 확정되기 전 추천하지 않는다. 지리 지도·광고 수익·일괄 성장률·가상 AI 예측을 만들어 넣지 않는다.
- 현재 실제 성과 계정 binding은 차단되어 있으며 실계정 권한·ID 매핑 활성화가 필요하다. Fake 계약·저장·집계 검증과 실제 수집을 구분한다.

## 화면 대응과 남은 범위

| 참고 화면 | 연결된 기존/신규 기능 | 한계 |
|---|---|---|
| 뉴스 수집 | 기존 검색·분류·소스 관리·실제 저장 수치, source tiles/지도형 배경 | 글로벌 실시간 트렌드 API/지도 분석은 없음. 장식 지도를 실제 지역 트래픽으로 표시하지 않음 |
| AI 대본 | 원본/요약/편집 3영역, 실제 장면 선택·수정·검토 | 존재하지 않는 tone/prompt 엔진은 가짜 토글로 표시하지 않음 |
| 영상 제작 | 기존 음성/소재/자막/장면 타이밍, 실제 MP4 미리보기·제작 | 9:16 최종 사양 유지. 가상 앵커 생성·임의 효과/BGM 믹싱은 이번 승인 범위 검토안에서 제외됨 |
| 게시 허브 | 4개 플랫폼 준비, 기존 통합 검토·부분 결과, 로컬 일정/해제/복구 | 신규 플랫폼 실계정과 실제 예약 전송은 차단 |
| 분석 리포트 | 성과 KPI/일별 차트/플랫폼 필터/영상 기록/근거 기반 시각 추천 | 실제 계정 조회 미실행. 일반 화면 자료 없음, 데모는 별도 합성 표시 |
| 설정 | 이전 완료된 배타적 6탭 유지, 새 플랫폼 준비 화면 연결 | OS·API·키·기존 기본값 변경 없음 |

## 실제 활성화 선행 조건

1. 앱의 이용 목적이 TikTok 심사 정책에 적합한지 공급사 확인. 부적합하면 개인용 공개 Direct Post 제공 불가.
2. TikTok 웹 OAuth/서버 secret 경계, Facebook Page용 승인 scope와 task, 토큰 만료/회수·계정 binding을 기존 안전 저장소와 별도 검토해 연결.
3. 실제 반환 지표/공개 ID·권한을 확인하고 합성 binding 대신 승인된 운영 binding을 연결. monetary/Meta 조건별 추가 권한 확인.
4. 공식 HTTPS production activation 변경은 별도 코드 리뷰·사용자 승인. 단순 설정 저장이나 환경변수로 우회 불가.
5. Windows 11 Python 3.12/3.14·Chrome·DPAPI·실제 영상 규격·재부팅/절전 후 예약 동작 확인.
6. 별도 승인된 비공개/제한 공개 1건부터 계정·영상·사용권·AI 표시·최종 검토 확인. 이번 작업에서는 실행하지 않음.
