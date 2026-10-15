# NewsFlow AI — Phase 5D 사전 분석: 기존 기능과 신규 기능

작성: 2026-10-15(KST). 대상: 기준 브랜치 `feat/newsflow-phase5c1` @ `830117894464f29ea572f6bdd2d67a02063fc96a`, 작업 브랜치 `feat/newsflow-phase5d`. 방법: 영상 엔진·영상 서비스·GUI·DB·자동 제작·외부 AI 게이트·테스트/CI·보안 기본 요소·5D 설계 초안의 10개 영역을 코드 기준으로 읽고, 별도 검토자가 누락과 오류를 확인했습니다. 지시의 원칙 "스토리보드, 장면 자동 분할, 타이밍, 자막, 소재 적용 기능을 중복 구현하지 않는다"에 따라 아래 표의 기존 기능은 **그대로 재사용**하고, 없는 기능만 새로 만들었습니다.

## 1. 기존 기능 (재사용 · 중복 구현 없음)

| 기능 | 기존 구성 요소 | Phase 5D에서의 사용 |
| --- | --- | --- |
| 장면 자동 분할 | 대본 스키마의 장면 목록(`intelligence/schema.py`), 오프라인·OpenAI 대본 생성 | AI 계획은 저장된 대본의 장면을 그대로 씁니다. 장면을 새로 나누지 않습니다. |
| 장면 타이밍 | `VideoCoordinator.timings`(30·45·60초 비례 배분), 음성 맞춤 `fit_timings`·`_apply_timings` | `AIVideoCoordinator.create_plan`이 `timings` 결과를 복사합니다. 최종 합성에서 음성 맞춤과 자막 구간 기록은 기존 코드가 그대로 수행합니다. |
| 자막·문구 표시 | `engine.card()`(Pillow 카드에 자막·출처·음성 표시·`NEWSFLOW · 미확인 보도 · 사람 검토 필요` 표시를 굽기, 자막 안전 영역 검사) | AI 장면은 같은 글꼴·줄바꿈·안전 영역 규칙을 쓰는 투명 레이어 `overlay()`로 클립 위에 얹습니다. 별도 자막 시스템을 만들지 않았습니다. |
| 소재 적용 | `VideoCoordinator.assets_list`·`asset`(assets 폴더 PNG/JPEG, 이용 권한 확인) | 장면 소재 '로컬 이미지'는 같은 함수와 같은 권한 확인을 거칩니다. |
| 렌더 파이프라인 | `VideoCoordinator._start/_run`(프로젝트·장면·음성·자막·작업 행, 단일 실행 잠금, 취소, 복구, 배타 생성 저장), `FFmpegAdapter.command/execute/inspect`, concat | 최종 합성은 `VideoCoordinator.start_ai` → 같은 `_start/_run` 경로입니다. 엔진에는 클립 장면용 인수 생성기 `clip_command` 하나만 더했습니다. |
| 데이터 모델 | `VideoProject → Scene → AudioTrack/SubtitleTrack → RenderJob` | 그대로 쓰고 `video_projects.ai_plan_id`, `video_scenes.clip_name/ai_generated` 열만 추가했습니다. |
| 승인 구조 | 외부 AI의 날짜가 있는 승인·월 한도(`intelligence/settings.py`), 자동 제작 검토 멈춤, 게시 준비의 사람 확인과 `ai_disclosure` | 같은 형태의 승인을 AI 영상용으로 **별도** 저장합니다. 게시 준비의 `ai_disclosure`는 새 필드를 만들지 않고 AI 장면이 있으면 `disclose`만 통과하도록 강화했습니다. |
| 비용 한도 | OpenAI 토큰 한도 `ai_usage`·`check_budget` | **재사용하지 않고 분리**했습니다. 기존 `usage_this_month`는 `provider != offline`인 모든 행을 더하므로 같은 표에 넣으면 영상 비용이 토큰 한도를 잠식합니다. AI 영상은 `video_ai_usage` 표와 자체 한도를 씁니다. |
| 키 저장 | `AIKeyStore`(현재 사용자 DPAPI, 환경변수 대체, 원자적 저장) | 클래스 상수만 분리해 `VideoAIKeyStore`(다른 파일·다른 엔트로피·다른 환경변수)로 상속했습니다. 동작 변화 없음. |
| 네트워크 보안 | `rss_adapter.validate_url`·`public_addresses`·`PinnedConnection`(SSRF 차단, DNS 고정, TLS 검증) | API 요청과 결과 다운로드가 그대로 가져다 씁니다. RSS 정책·모듈 상수는 바꾸지 않았습니다. |
| GUI 보안 | Origin·Sec-Fetch-Site·HMAC CSRF·64 KiB urlencoded·CSP `'self'` 미들웨어, fetch 단일 제출 JS 패턴 | AI 화면 모든 POST가 같은 미들웨어를 거칩니다. JS는 기존 패턴을 따른 `video_ai.js`만 추가했습니다. |
| 재시작 복구 | `VideoCoordinator.recover`(실행 중 → 중단, 재실행 없음), 자동 제작 복구 | 같은 원칙으로 `AIVideoCoordinator.recover`를 만들었습니다: 제출 중 → 결과 불명(다시 보내지 않음), 내려받기 중 → 상태 재확인. |
| 테스트·CI | `create_app` 주입형 픽스처, `FakeRenderAdapter`·`FakeTTS`, `ci_fixture_server.py`, CI 도구·Windows 워크플로 템플릿 | Fake 공급자 주입을 같은 방식으로 추가했고 5C.1 워크플로를 복제해 AI 영상 단계를 더했습니다. |

## 2. 새로 만든 기능

| 영역 | 파일 | 내용 |
| --- | --- | --- |
| 공급사 계약 | `video/ai/contracts.py` | 공급사 독립 `VideoProvider` Protocol(submit·status·cancel·fetch), 요청·상태·결과 데이터, 고정 한국어 오류 코드와 `sent` 표시 |
| 공급사 구현 | `video/ai/higgsfield.py`, `video/ai/fake.py` | Higgsfield REST(제출 재시도 없음), 테스트 전용 Fake(외부 호출 없음, 실제 재생 가능한 클립) |
| 안전 다운로드·클립 보관 | `video/ai/download.py`, `video/ai/clips.py` | HTTPS·DNS 고정·리디렉션 재검사·크기/시간 제한, `data/ai-clips` 저장소와 ffprobe 검증 |
| 오인 방지 | `video/ai/policy.py` | 프롬프트 거부 규칙, 모든 프롬프트에 붙는 스타일 문장, 끌 수 없는 장면 표시 |
| 비용·설정 | `video/ai/costs.py`, `video/ai/settings.py`, `video/ai/keys.py` | 모델별 초당 단가·허용 길이 목록, 작업별·월 한도(USD/KRW), 날짜가 있는 승인, 별도 키 |
| 계획·작업자 | `video/ai/service.py` | 장면별 소재·프롬프트·모델, 예상 비용 확인, 장면 시도별 예약, 비교 후 갱신 상태 기계, 파일 잠금 작업자, 결과 불명 처리, 결과 다시 받기, 관계 검토, 최종 합성 승인·재시도 |
| DB | `migrations/versions/0010_ai_video.py` | `video_ai_models`, `ai_video_plans`, `ai_video_scenes`, `video_ai_usage` 표와 열 3개(추가 전용, 되돌리기 지원) |
| GUI | `gui/video_ai_routes.py`, 템플릿 3개, `static/js/video_ai.js` | `/video/ai`(두 제작 모드), 계획 화면(스토리보드·비용·관계 검토·합성), `/video-ai-settings` |
| 합성 | `engine.py` `overlay()`·`clip_command()`·`CLIP_FILTER` | 클립을 9:16으로 잘라 반복하고 문구 레이어와 노란 표시를 얹음. 클립 소리는 버리고 내레이션만 사용 |
| CI | `tools/ci_ai_video_validation.py`, `.github/workflows/newsflow-phase5d-windows.yml` | 실제 GUI·재시작·최종 MP4 검증 |

## 3. 설계 결정

1. **자동 제작(Autopilot)에는 넣지 않았습니다.** 유료 생성은 장면별로 사람이 소재와 프롬프트를 고르고, 예상 비용 확인과 최종 합성 승인이라는 두 번의 명시적 승인을 거쳐야 합니다. 자동 제작의 6단계 흐름에 넣으면 승인 경계가 흐려지므로 AI 고품질 모드는 영상 스튜디오(`/video` → `/video/ai`)의 독립 흐름으로 두었습니다. 자동 제작 영상은 지금처럼 카드만 씁니다(5C.1 설계 초안 §2의 자동 제작 연동안은 채택하지 않음).
2. **장면 소재 기본값은 카드**이고 AI 생성은 장면마다 고릅니다. 5C.1 설계 초안의 "코드 고정 모델 허용 목록·자동 장면 선정"은 공급사 사실을 확인하지 못한 상태에서 코드에 넣을 수 없으므로, 사용자가 공식 문서에서 확인한 모델·단가·허용 길이를 입력하고 확인 체크를 하는 방식으로 바꿨습니다.
3. **비용은 보수적으로 셉니다.** 보내지 않은 요청만 빼고 실패·정책 거부·취소·결과 불명 요청도 이번 달 사용액에 넣습니다(환불 규칙 NOT VERIFIED).
4. **제출은 절대 자동 재전송하지 않습니다.** 보낸 뒤 결과를 모르는 요청은 '결과 불명'으로 두고 사용자가 공급사 대시보드를 확인한 뒤 실패로 확정해야 다시 보낼 수 있습니다.

## 4. 분석에서 발견해 고친 결함

분석·테스트 작성 과정에서 발견한 결함은 모두 고쳤고, 각 결함에 회귀 테스트가 있습니다.

| 결함 | 수정 |
| --- | --- |
| 0010 되돌리기가 테이블을 다시 만들어 외래키로 영상 장면이 지워지거나 실패 | 0008/0009처럼 열만 제자리에서 삭제 |
| 합성이 끝나도 계획 상태가 '최종 합성 중'에 머묾(화면이 계속 새로고침) | 목록·계획·상태 API를 읽을 때 렌더 작업 결과로 상태 갱신 |
| 합성 실패 후 같은 계획을 다시 합성할 수 없어 비용을 낸 클립이 묶임 | 실패·중단된 합성은 장면 수정과 재합성 허용(추가 생성 비용 없음) |
| 완료 후 다운로드·검증 실패 시 새 유료 요청 외에 방법이 없음 | 같은 요청의 결과를 최대 3번 다시 받기, 제한시간이 지나도 완료된 결과는 내려받음 |
| 정책을 통과하지 못하는 저장 프롬프트 하나가 작업자 전체를 멈춤 | 보내기 직전 재검사, 실패 시 그 장면만 '보내지 않음'으로 취소 |
| 작업자 예외(유니코드 숫자 Content-Length 등)로 장면이 '내려받는 중'에 영구 정지 | 장면 단위로 모든 예외를 분류, ASCII 숫자만 허용 |
| 키가 들어간 프롬프트가 SQLite에 저장됨 | 장면 저장 단계에서 키(와 키 ID·비밀값 각각)를 검사해 거부 |
| 잘못된 키·모델 경로가 '보낸 뒤 결과 불명'으로 비용 계산 | 보내기 전 검사 실패는 '보내지 않음'으로 분류, 헤더 주입 차단 |
| API·다운로드 요청이 `Host: 주소:443`을 보냄 | 포트 없는 Host 헤더 |
| 서명된 결과 주소의 쿼리가 RSS 자격 증명 규칙에 걸려 결과를 못 받을 위험 | 다운로드는 쿼리를 분리해 길이·문자만 검사(주소는 저장·기록하지 않음) |
| 프롬프트 정책이 '실제영상'·'deep fake'·제어 문자·주소를 통과 | 띄어쓰기·하이픈 무시 비교, Cc/Cf 문자와 URL·이메일 거부 |
| 클립 장면과 카드 장면의 H.264 헤더 차이(SAR·색 정보)로 `-c copy` 이어 붙이기가 첫 장면 헤더만 유지 | 클립 필터에서 화면비·색 표시를 비워 장면 파일 헤더를 바이트 단위로 일치 |
| 검토한 클립과 합성한 클립이 같은지 확인하지 않음 | 승인 시와 렌더 직전에 SHA-256 비교, 프로젝트 스냅숏·작업 메타데이터에 기록 |
| 클립 문제가 '완성 MP4 실패'로 안내됨 | 렌더 오류 종류 `clip`과 "AI 생성 장면 파일" 안내 |
| 게시 준비에서 AI 장면 영상을 'AI 표시 불필요'로 통과시킬 수 있음 | AI 장면이 있으면 `disclose`만 통과 |
| AI 장면이 계획 화면 밖(영상 작업·보관함)에서 구분되지 않음 | 작업 화면 장면별 소재 표시와 "AI 생성 장면 포함" 표시 |
| 디스크 여유 공간 확인 없이 다운로드 | 200 MiB + 512 MiB 여유가 없으면 받지 않고 다시 받기 가능 상태로 둠, 렌더 사전 검사에 클립 크기 포함 |

## 5. 남은 한계 (구현하지 않음)

- `newsflow.migrate_data`는 DB와 세션 키만 복사합니다. `data\ai-clips` 폴더와 `video-ai-key.dpapi`는 이전 도구가 복사하지 않으므로 데이터 폴더를 옮길 때 사용자가 함께 복사해야 합니다(기존 영상 출력 폴더와 같은 정책).
- 받은 클립은 계획이 참조하는 동안 보관하며, 참조되지 않는 파일만 시작 시 지웁니다. 오래된 계획의 클립을 자동으로 지우는 보관 기간 정책은 없습니다.
- 월 한도는 OpenAI 토큰 한도와 같은 UTC 월 기준(한국 시간 매월 1일 09:00 초기화)이며 화면에 그렇게 안내합니다.
- 실제 Higgsfield 호출, 가격, 생성 품질, 결과 보관 기간은 사용자 승인 전까지 확인하지 않습니다(NOT VERIFIED). 자세한 내용은 [Higgsfield API 검증 결과](phase5d_higgsfield_api_verification.md)를 참고하세요.
