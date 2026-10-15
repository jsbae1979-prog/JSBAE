# Phase 5D · Higgsfield 영상 Provider 설계 초안

작성일: **2026-10-15** · 브랜치 `feat/newsflow-phase5c1` · 패키지 E

> **설계 초안 · 구현 없음 · Phase 5D 승인 후 착수 · Phase 5C.1에서는 Higgsfield API/MCP 호출 0건 (catalog/balance 조회도 보류)**

> **Phase 5D 구현 후 안내(2026-10-15 KST):** 이 문서는 Phase 5C.1 당시의 설계 초안으로 기록용으로 보존합니다. 실제 구현은 [Phase 5D 구현 설계](phase5d_ai_video_implementation.md)를 따르며, 자동 제작 연동·표 이름·표시 문구·다운로드 규칙 등 이 초안과 달라진 점은 그 문서 13절에 정리했습니다.

이 문서는 코드베이스(`src/newsflow/video/engine.py`, `video/service.py`, `autopilot/backend.py`,
`autopilot/service.py`, `intelligence/settings.py`, `intelligence/credentials.py`, `db/models.py`,
`news/rss_adapter.py`, `publishing/service.py`)와 일반 지식만으로 작성했다. Cloud 컨테이너는 외부 네트워크가
막혀 있어(프록시 403) `docs.higgsfield.ai` 본문을 읽지 못했다. 따라서 **엔드포인트, 헤더, 상태 이름, 모델 ID,
길이 범위, 가격, 동시성, 약관 등 모든 vendor 사실은 "NOT VERIFIED — 공식 문서에서 확인" 상태**이며, 엔드포인트
이름은 전부 **가정**이다. 구현 착수 시 [docs/publishing_platforms.md](../publishing_platforms.md)와
[docs/oauth_platforms.md](../oauth_platforms.md)처럼 "확인 날짜가 있는 vendor 사실 표"(15절)를 먼저 채운다.
문서 안의 코드 조각은 설계 의도를 보여주는 스케치이며 실행 코드가 아니다.

---

## 1. 목적과 범위

- **FFmpeg 카드 제작은 기본이고 그대로 유지한다.** `FFmpegAdapter.render` → `card()` → `command()` →
  concat → `inspect()` 경로와 그 산출물(1080×1920 H.264/yuv420p/AAC MP4)은 Phase 5D 이후에도 바이트 단위로
  동일해야 하며, 5A–5C 회귀 테스트는 변경 없이 통과해야 한다.
- **Higgsfield는 선택형 Video Provider**다. 실제 콘텐츠 제작(`content_mode == "real"`)에서 사용자가 명시적으로
  고른 작업에 한해, 대본의 "주요 내용" 장면 일부를 AI 생성 B-roll 클립으로 바꾸고, 그 위에 기존 제목·자막·출처·
  표시 띠를 Pillow 오버레이로 얹어 FFmpeg로 합성한다.
- 외부 AI 대본(Phase 5C)의 경계를 그대로 미러한다: 날짜가 있는 승인, 월 한도, DPAPI 키 저장, 체험 제작 금지,
  비밀값 DB/로그/HTML 비저장, 사람 검토 유지, 자동 재요청 금지.

| 포함 (Phase 5D 구현 범위) | 제외 (16절 참조) |
|---|---|
| `VideoProvider` Protocol, `FakeVideoProvider`, `HiggsfieldProvider` 골격 | Webhook 수신, 스케줄러, 무인 운영 |
| 장면별 클립 계획·비용 추정·승인/한도/키 게이트 | OAuth, 실제 SNS 게시, 게시 API에 AI 표시 전송 |
| 비동기 작업 상태 기계와 `video_provider_jobs` 영속화 (migration 0010) | 영상 업스케일·편집·음성 생성 등 다른 vendor 기능 |
| Bounded 다운로드 → ffprobe 검증 → FFmpeg 합성 → 카드 대체 | 대본·자막·내레이션을 AI 영상에 맞춰 자동 수정 |
| AI 생성 장면 표시(화면 각인·대기함 설명·체크리스트) | 플랫폼 AI 표시 의무의 최종 판단(사람이 한다) |

## 2. 제작 모드 · '기본 제작 (FFmpeg)' vs 'AI 고품질 제작 (Higgsfield)'

| 구분 | 기본 제작 (FFmpeg) · `video_mode = "ffmpeg"` | AI 고품질 제작 (Higgsfield) · `video_mode = "ai"` |
|---|---|---|
| 허용 콘텐츠 | 체험·실제 모두 | **실제 콘텐츠만** (체험 제작에서는 절대 불가) |
| 외부 호출 | 0건 | 장면별 클립 제출·조회·다운로드 (유료) |
| 장면 화면 | Pillow 카드 | 주요 내용 장면 = AI 클립 + 오버레이, 나머지 = 카드 |
| 사전 조건 | FFmpeg/ffprobe·글꼴·디스크 | + 제공자 선택, 날짜 있는 승인, 월 초 한도, 키, **작업별 비용 확인 체크** |
| 실패 시 | 작업 실패 | 장면별 카드 대체 또는 작업 실패 (12절) |
| 검토 지점 | 실제 콘텐츠: 대본·최종 영상 | 동일 + AI 장면 체크리스트 항목 (9절) |

### 2.1 게이트 (실행 시점마다 다시 검사)

`PipelineBackend._ai_mode`와 같은 위치·방식으로 `PipelineBackend._video_mode(ctx)`를 둔다.

1. `ctx["content_mode"] != "real"` 이고 `video_mode == "ai"` → `BackendError(code="video_consent", retryable=False)`.
   `AutopilotService.start`도 `ai_mode`와 같은 규칙으로 `video_mode`를 검증해 체험 작업은 저장 단계에서 거부한다.
2. `video_gate()`(`external_ready`를 복제한 `video_ready(sessions, key_store)`)가 `ready=False`면 `video_not_ready`.
3. 작업 시작 폼의 `video_cost_ack`가 없으면 `video_consent`; 승인 체크가 해제되면 진행 중 작업도 다음 클립 제출 전에
   `video_consent`로 멈춘다(렌더 중에도 `video_ready`를 제출 직전마다 재평가).
4. 제출 직전 예산 검사(5절) 실패 → `video_budget`, 제공자 호출 0건.

### 2.2 기본값

`/simple-settings`의 기본값은 `ffmpeg`이며, 설정 화면에서 `ai`를 기본값으로 저장하더라도 체험 제작 작업은 항상
`ffmpeg`로 강제한다(시작 폼은 체험 선택 시 AI 라디오를 비활성화하고 서버도 거부).

### 2.3 GUI 변경 요약

| 화면 | 변경 |
|---|---|
| 준비 상태 칩 (`autopilot_routes.readiness`) | `AI 영상: 사용 가능` / `AI 영상: 불가 (사유)` 칩 추가. 사유는 `video_ready()["reasons"]` 문자열(한국어). |
| `/autopilot/start` (`autopilot_start.html`) | fieldset **`4. 영상 제작 방식`** 라디오 `ffmpeg`(기본) / `ai`. 준비 안 됨·체험 선택 시 `ai` 라디오를 `disabled`로 두고 사유를 라벨 아래에 표시. `ai` 선택 시 모델 `<select>`(허용 목록만), 예상 비용 패널, `video_cost_ack` 체크박스가 나타남. `3. 영상 길이` fieldset 뒤에 추가하며, 번호 없는 기존 `영상의 목적지`·`대본 만들기`·`음성` 선택은 그대로 둠. |
| `/simple-settings` | 기본 영상 제작 방식 저장(`autopilot_video_mode`). |
| **새 페이지 `/video-provider-settings`** (`video_provider_settings.html`, `ai_settings.html` 복제) | 제공자/모델/월 초 한도/작업 초 한도/사용자 입력 단가/제한시간/승인 체크, 키 저장·삭제(값 비표시), 연결 확인(0비용 확인 방법은 15절에서 재확인), 이번 달 사용 초·최근 작업 목록. |
| `/autopilot/jobs/<id>` (`autopilot_job.html`) | 장면별 `clip_source` 칩, AI 장면 수·대체 카드 수, 최종 체크리스트 2개 항목 추가(9절). |
| `/api/autopilot/jobs/<id>` 스냅샷 | `video_mode`, `ai_scenes`(요청/성공/대체 수), `provider_status`(현재 클립 상태 요약) 필드 추가. 키·URL·요청 본문은 포함하지 않음. |
| `/video` (`video.html`) | 장면 목록에 `clip_source` 표시(`card` / `ai` / `ai_fallback_card`). |
| 오류 코드 | `_ERROR_MESSAGES`/`_SOLUTIONS`에 `video_*` 12종(3절)을 한국어로 추가; `backend._AI_CODES`와 같은 `_VIDEO_CODES` 집합. |

## 3. VideoProvider 추상화

새 모듈 `src/newsflow/video/provider.py` (GUI·서비스·영속성·외부 어댑터 분리 규칙 유지).

### 3.1 데이터 계약 (frozen dataclasses)

| 타입 | 필드 | 비고 |
|---|---|---|
| `ClipRequest` | `job_id: int`, `scene_index: int`, `model: str`, `prompt: str`, `seconds: float`, `aspect: str = "9:16"`, `width: int = 1080`, `height: int = 1920`, `image: Path \| None = None`, `idempotency_key: str` | `prompt`는 10절의 고정 템플릿 결과만. `image`는 자막 없는 카드 PNG(선택). |
| `ClipEstimate` | `model`, `seconds`, `units: float \| None`, `currency: str \| None`, `rate_source: "user" \| None` | `units`는 사용자 입력 단가 × 초, 단가 없으면 `None`. |
| `ClipHandle` | `request_ref: str`, `submitted_at: datetime`, `idempotency_key: str` | `request_ref`는 **불투명 ID만**. status_url/cancel_url 같은 토큰 포함 URL은 보관하지 않음. |
| `ClipStatus` | `state: "queued" \| "running" \| "succeeded" \| "failed" \| "rejected" \| "cancelled" \| "unknown"`, `output_ref: str \| None`, `error_code: str \| None`, `retry_after: float \| None` | vendor 상태 어휘를 앱 어휘로 정규화(7절). 원문 응답 본문은 저장하지 않음. |

### 3.2 Protocol

```python
class VideoProvider(Protocol):
    def models(self) -> dict[str, ModelSpec]: ...          # 코드 안 허용 목록 (네트워크 없음)
    def estimate(self, request: ClipRequest, rate_per_second: float | None) -> ClipEstimate: ...
    def submit(self, request: ClipRequest, timeout: int) -> ClipHandle: ...
    def poll(self, handle: ClipHandle, timeout: int) -> ClipStatus: ...
    def fetch(self, status: ClipStatus, target: Path, deadline: float) -> Path: ...  # BoundedDownload (13절)
    def cancel(self, handle: ClipHandle, timeout: int) -> bool: ...
    def check_connection(self, timeout: int) -> dict: ...   # 0비용 확인 방법은 NOT VERIFIED
```

### 3.3 오류 클래스와 코드

`ProviderError`(intelligence)와 같은 모양의 `VideoProviderError(message, code, retryable)`를 두고 코드는 아래 12종으로 고정한다.
메시지는 안전한 한국어 문장만 담고 응답 본문·예외 문자열·URL·키를 포함하지 않는다.

| 코드 | 발생 | retryable | 작업 영향 (12절) |
|---|---|---|---|
| `video_auth_failed` | HTTP 401/403 | no | 작업 실패 |
| `video_rate_limited` | HTTP 429 | 1회 (Retry-After ≤15초) | 장면 대체 |
| `video_timeout` | 소켓 제한시간 | no (제출 재시도 금지) | 장면 대체 |
| `video_unavailable` | 5xx·연결 실패 | 1회 (바이트 전송 전 연결 실패 또는 5xx) | 장면 대체 |
| `video_bad_response` | JSON/필드 형식 오류 | no | 장면 대체 |
| `video_moderated` | vendor 정책 거부(NSFW 등) | **never** | 장면 대체 (`rejected`) |
| `video_key_missing` | 키 없음 | no | 작업 실패 |
| `video_budget` | 월/작업 초 한도 초과 | no | 작업 실패 (호출 0건) |
| `video_consent` | 승인 없음·체험 제작·비용 확인 체크 없음 | no | 작업 실패 (호출 0건) |
| `video_not_ready` | 게이트 실패 종합 | no | 작업 실패 (호출 0건) |
| `video_download_failed` | 다운로드 크기/호스트/제한시간/연결 | 연결 실패 1회 | 장면 대체 |
| `video_clip_invalid` | ffprobe 검증 실패 | no | 장면 대체 |

### 3.4 FakeVideoProvider

테스트 전용. 생성자에 `script: dict[str, list[ClipStatus | Exception]]`(idempotency_key → 순차 상태)를 받아
`poll` 호출마다 다음 상태를 반환하고, `calls: list[tuple[str, ...]]`에 모든 호출을 기록한다. `fetch`는 지정한 합성 MP4
(테스트가 `lavfi testsrc`로 만들거나 fixture로 둔 파일)를 복사한다. `submit`은 같은 `idempotency_key`에 대해 같은
`request_ref`를 돌려주어 중복 제출 테스트를 가능하게 한다. 상태 전이·취소·예외를 모두 스크립트로 지정할 수 있다.

### 3.5 HiggsfieldProvider 골격

- `urllib.request` + `NoRedirect`(intelligence/provider.py의 것을 재사용), 기본 TLS 검증, 리디렉션 거부.
- 고정 상수 `HIGGSFIELD_BASE = "https://<api-host>/<version>"` — 호스트·버전·경로 **모두 가정, NOT VERIFIED**.
  설정·환경변수로 바꿀 수 없다(OpenAI `OPENAI_BASE`와 동일 정책).
- 엔드포인트 **가정**: `POST <base>/<text-or-image-to-video>` 제출, `GET <base>/<requests>/{request_ref}` 상태,
  `POST <base>/<requests>/{request_ref}/<cancel>` 취소, 0비용 연결 확인(`balance` 또는 `models` 조회 여부 자체가 NOT VERIFIED).
- 키는 `key_provider()`로 받아 **`Authorization` 헤더에만** `<scheme> <api-key>` 형태로 넣는다. 스킴(`Key`/`Bearer`)은
  NOT VERIFIED. 키는 로그·예외·DB·메타데이터·HTML에 절대 넣지 않으며, 요청 객체를 로그에 출력하는 코드 경로를 두지 않는다.
- `Idempotency-Key` 헤더 = `sha256("|".join([str(job_id), str(scene_index), prompt, model, f"{seconds:.3f}"])).hexdigest()`.
  vendor가 이 헤더를 지원·존중하는지는 NOT VERIFIED이므로 앱 쪽 중복 제출 방지(DB unique)가 1차 방어다.
- 응답 크기 ≤ 256 KiB(JSON), `Accept-Encoding: identity`, `Content-Type: application/json`, 요청 본문은 ClipRequest의 허용
  필드만 직렬화한다(대본·RSS 텍스트 없음).

## 4. 모델 선택과 장면별 클립 계획

### 4.1 허용 목록 `CURATED_MODELS` (전부 NOT VERIFIED)

```python
CURATED_MODELS = {
    # 식별자·초 범위·스텝·세로 지원·이미지 입력 모두 가정값. 공식 모델 카탈로그로 교체한다.
    "<vendor-model-standard>": ModelSpec(label="표준 (가정)", min_seconds=2, max_seconds=10, step=1,
                                         supports_916=True, image_input=True),
    "<vendor-model-fast>":     ModelSpec(label="빠름·저가 (가정)", min_seconds=2, max_seconds=5, step=1,
                                         supports_916=True, image_input=False),
}
```

사용자는 이 목록에서만 고른다(`video_provider_model` 값이 목록에 없으면 `read_settings`가 첫 항목으로 되돌림, AISettings의
`Options(model=...)` 검증과 같은 방식). 자유 입력 모델 이름은 받지 않는다.

### 4.2 장면 선정 규칙

| 규칙 | 근거 |
|---|---|
| **주요 내용 장면만** AI 클립 후보. `Script.scenes`의 **마지막 장면(마무리·요약·검토 안내 성격)은 항상 카드**. Offline 대본의 "출처 목록 텍스트 카드"·"검토 안내 카드" 장면도 카드. | 출처·검토 안내는 텍스트 정보가 핵심이고, B-roll로 대체하면 오해 소지. |
| `ContentDraft.review_notes`에 `numbers_not_in_source`가 있는 대본의 장면은 기본값 카드(사용자가 장면별로 켜지 않는 한). | 원문에 없는 숫자가 있는 장면에 사실처럼 보이는 영상을 붙이지 않는다. |
| `scene.material` 텍스트는 프롬프트에 쓰지 않는다(10절). | 대본 텍스트는 신뢰할 수 없는 입력. |
| 상한: **클립 ≤ 8개**(RenderPlan 장면 상한과 동일), **작업당 생성 초 ≤ `per_job_seconds_limit`(기본 60)**, **클립 1개 ≤ 30초**. | 비용·시간 폭주 방지. |

### 4.3 장면별 초 계산

`seconds = round_to_step(min(scene_seconds_after_audio_fit, model.max_seconds), model.step)`; `model.min_seconds` 미만이면
그 장면은 카드. **audio-fit 뒤의 장면 초**를 쓰므로 `FFmpegAdapter.render`의 `fit_timings` 결과(또는 무음일 때 대본 장면 초)가
확정된 다음에 클립 계획을 만든다. 클립이 장면보다 짧으면 합성 시 `-stream_loop -1`로 채우고, 길면 `-t`로 자른다(11절).

### 4.4 해상도와 이미지 입력

- 모델이 9:16을 지원하면 **1080×1920**을 요청한다(가정). 지원하지 않거나 다른 크기가 오면 FFmpeg `scale ... crop`으로 맞춘다.
- 선택 옵션 **image-to-video**: `card()`와 같은 레이아웃이되 **자막 텍스트를 뺀** 카드 PNG(제목·장면 번호·배경만)를 입력 이미지로
  보낸다. 전송 전 PNG 크기 ≤ 4 MiB, 픽셀 1080×1920 고정. 이미지 업로드 방식(멀티파트/사전 URL)은 NOT VERIFIED.

## 5. 예상 비용·월 한도·날짜가 있는 승인

### 5.1 `VideoProviderSettings` (`src/newsflow/video/settings.py`, `AISettings` 미러)

| 필드 | AppSetting 키 | 검증 |
|---|---|---|
| `provider: "none" \| "higgsfield"` | `video_provider` | 목록 외 값 → `none` |
| `model` | `video_provider_model` | `CURATED_MODELS` 키만 |
| `approved` / `approved_at` | `video_provider_approved_at` | 체크 시 최초 승인 시각 보존, 해제 시 빈 문자열(= 즉시 중단) |
| `monthly_seconds_limit: int` | `video_provider_monthly_seconds` | 0 ≤ n ≤ 36 000; 승인하려면 > 0 |
| `per_job_seconds_limit: int` | `video_provider_job_seconds` | 1 ≤ n ≤ 240, 기본 60 |
| `rate_per_second: Decimal \| None`, `rate_entered_at` | `video_provider_rate`, `video_provider_rate_at` | 사용자가 입력한 값·날짜, **표시 전용** |
| `timeout: int` | `video_provider_timeout` | 1–60초, 기본 20 |

기존 `video_default_*` 키(음성·자막 기본값)와 충돌하지 않도록 접두사를 `video_provider_`로 고정한다(`AppSetting.key`는 50자).
`write_settings`는 `BEGIN IMMEDIATE`로 직렬화하고, `usage_this_month`는 `video_provider_usage.seconds` 합계를 돌려준다.

### 5.2 예상 비용

`estimate = 계획된 생성 초 합계 × rate_per_second`; 단가가 없으면 `None`("단가 미입력"). 화면과 작업 상세에는 항상 다음 문구를
붙인다(Phase 5C.1의 AI 토큰 비용 추정과 같은 문구):

> 단가는 사용자가 입력한 값이며 공식 요금표를 확인하세요. 예상 비용은 참고용 추정치이고 실제 청구는 제공자 대시보드에서 확인합니다.

### 5.3 예산 검사와 작업별 확인

- **제출 전** `check_budget`: `이번 달 사용 초 + 이번 작업 계획 초 > monthly_seconds_limit` 이면 `video_budget`, 제공자 호출 0건.
  작업 계획 초가 `per_job_seconds_limit`를 넘으면 계획 단계에서 클립 수를 줄이지 않고 거부한다(사용자가 모델·장면 수를 바꾸도록).
- **작업별 확인 체크박스 `video_cost_ack`**: 시작 폼(또는 대본 검토 일시정지, 16절 미결)에서 체크해야 하며 서버는
  `autopilot_jobs.video_cost_ack_at`(UTC)에 시각을 저장한다. 체크 없는 요청은 `video_consent`. 이 확인은 사실 확인·게시 승인이 아니다.
- 체험 제작에서는 체크박스 자체를 표시하지 않고, 서버가 값이 와도 무시하고 `ai`를 거부한다.

## 6. 키 저장

- `AIKeyStore`를 **매개변수화**한다: `AIKeyStore(data_dir, cipher=None, *, file="ai-key.dpapi", env_name="NEWSFLOW_AI_API_KEY",
  entropy_label=b"NewsFlowAI:Phase5C:ai-api-key")`. 기본값은 현재 동작과 동일하므로 **기존 AI 키의 DPAPI entropy는 바이트 단위로 동일**해야
  하며, 회귀 테스트가 `_entropy()` 결과를 `sha256(b"NewsFlowAI:Phase5C:ai-api-key").digest()`와 비교하고, 5D 이전 코드로 저장한
  FakeCipher 파일이 그대로 복호화되는지 확인한다.
- `VideoKeyStore = AIKeyStore(data_dir, file="video-key.dpapi", env_name="NEWSFLOW_VIDEO_API_KEY",
  entropy_label=b"NewsFlowAI:Phase5D:video-api-key")`. 별도 파일·별도 환경변수·별도 entropy라 두 키를 서로 복호화할 수 없다.
- 키 형식 정규식은 공식 문서 확인 후 조정(현재 `[A-Za-z0-9_\-.:]{20,256}` 가정). 키는 DB·로그·HTML·오류 메시지·`metadata_json`·
  `stage_results`에 들어가지 않는다.
- **secret-in-content 검사 확장**: `VideoCoordinator._start`의 `NEWSFLOW_AI_API_KEY` 포함 검사, `IntelligenceService.check_secret`,
  `publishing.reject_secrets`가 `NEWSFLOW_VIDEO_API_KEY`와 저장된 video 키도 검사한다. `AutopilotService._validated_result`의 키 이름
  정규식(`token|secret|password|authorization|api_key|verifier`)은 그대로 적용되며, 렌더 단계 결과에는 `request_ref`·`clip_sha256` 같은
  비밀 아닌 키만 둔다.

## 7. 비동기 작업 상태 기계와 영속화

### 7.1 앱 상태 (`video_provider_jobs.status`)

| 상태 | 진입 | 다음 | 사용량 기록 | 비고 |
|---|---|---|---|---|
| `submitted` | 제출 2xx 응답 수신 | running / succeeded / failed / rejected / cancelled / expired / unknown | — | 이 상태에서만 vendor 취소 요청 |
| `running` | poll이 처리 중 보고 | succeeded / failed / rejected / abandoned / expired / unknown | — | |
| `succeeded` | 클립 다운로드·검증 완료 | 종료 | 기록 | `clip_sha256`, `clip_bytes` 채움 |
| `failed` | vendor 실패·다운로드/검증 실패 | 종료 | 기록(보수적) | 장면 대체 |
| `rejected` | moderation 거부 | 종료 · **재시도 없음** | 기록 | 장면 대체 |
| `cancelled` | submitted 상태에서 취소 성공 | 종료 | 기록(보수적) | vendor가 아직 대기열이던 경우 |
| `abandoned` | running 상태에서 취소/앱 종료 | 종료 | **기록** | vendor는 계속 생성·청구할 수 있음 |
| `expired` | 앱 제한시간(8절) 초과 | 종료 | 기록 | |
| `unknown` | 재시작 시 submitted/running 발견 | 종료 (읽기 전용 "결과 확인"만 허용) | 기록 | **자동 재제출 금지** |

vendor 상태 어휘(가정: `queued/in_progress/completed/failed/nsfw/canceled`)는 `HiggsfieldProvider.poll`에서 위 어휘로 변환하며,
알 수 없는 값은 `running`으로 두되 제한시간이 보호한다. 변환 표 자체가 NOT VERIFIED.

### 7.2 Migration `0010` (Phase 5D 예약 · additive · Phase 5C.1은 마이그레이션 없음)

`video_provider_jobs`

| 열 | 타입 | 비고 |
|---|---|---|
| `id` | Integer PK | |
| `render_job_id` | FK `render_jobs.id` | |
| `project_id` | FK `video_projects.id` | |
| `scene_position` | Integer | `unique(render_job_id, scene_position)` |
| `provider` | String(20) | `higgsfield` |
| `model` | String(80) | 허용 목록 키 |
| `status` | String(20) | 7.1 어휘 |
| `request_ref` | String(100) nullable | **불투명 ID만**; status_url/cancel_url 저장 금지 |
| `idempotency_key` | String(64) unique | sha256 hex |
| `prompt_sha256` | String(64) | |
| `prompt` | Text | **실제 전송한 정제 프롬프트**(감사용, 10절) |
| `seconds` | Float | 요청 초 |
| `estimated_units` | Float nullable | 사용자 단가 기준 추정 |
| `error_code` | String(40) nullable | `video_*` |
| `attempts` | Integer default 0 | 제출 시도 수 |
| `clip_name` | String(100) nullable | 작업 폴더 안의 생성 파일명 |
| `clip_sha256` | String(64) nullable | |
| `clip_bytes` | Integer nullable | |
| `submitted_at` / `updated_at` / `finished_at` / `created_at` | DateTime | UTC naive 직렬화(기존 UTCDateTime) |

`video_provider_usage` — `ai_usage` 미러: `id, job_id FK video_provider_jobs.id nullable, provider, model, status, seconds, elapsed_ms, created_at`
+ `ix_video_provider_usage_created_at`. **모든 종료 상태에 1행**을 써서 월 초 예산이 보수적으로 계산되도록 한다.

열 추가: `autopilot_jobs.video_mode String(16) NOT NULL server_default 'ffmpeg'`, `autopilot_jobs.video_cost_ack_at DateTime nullable`,
`video_scenes.clip_source String(20) NOT NULL server_default 'card'`.

스키마 head가 `0009` → `0010`으로 바뀌면 다음 **여섯 테스트의 schema-head 단언**과 두 파일을 함께 고친다:
`tests/test_database.py`, `tests/test_intelligence.py`, `tests/test_publishing.py`, `tests/test_autopilot_state.py`,
`tests/test_oauth_lifecycle.py`, `tests/test_oauth.py` + `src/newsflow/migrate_data.py`(지원 버전 집합에 `("0010",)`) +
`AGENTS.md`("migrations 0001–0009" → 0010 포함). 기존 0001–0009 파일은 수정하지 않는다.

## 8. 재시작 복구·제한시간·재시도 규칙

| 항목 | 규칙 |
|---|---|
| HTTP 제한시간 | 설정값 1–60초(기본 20), 요청마다 적용 |
| 폴링 간격 | 2초에서 시작해 10초까지 증가, ±20% jitter — vendor 권장 간격은 **NOT VERIFIED** |
| 클립 제한시간 | 제출부터 600초. 초과 시 `expired`, 취소 시도는 `submitted` 상태일 때만 |
| 렌더 제한시간 | AI 모드 1500초. `backend._render`의 `deadline = time.monotonic() + 1200`은 **`video_mode == "ai"`일 때만** 1500+여유로 올리고 FFmpeg 모드는 그대로 |
| 제출 재시도 | **제한시간 초과 뒤 자동 재제출 금지(이중 청구 방지)**. 바이트 전송 전 연결 실패 또는 5xx에 한해 같은 `Idempotency-Key`로 **1회** |
| 폴링 재시도 | 5xx/네트워크 오류는 제한시간까지 backoff 계속; 401/404는 즉시 중단(`video_auth_failed`/`failed`); 429는 Retry-After ≤15초를 주기당 1회 존중 |
| 다운로드 재시도 | 연결 실패 1회; 크기 초과·검증 실패는 재시도 없음 |
| vendor 취소 | 앱 상태 `submitted`에서만 호출; `running`이면 `abandoned`로 기록만(청구 가능성 안내) |
| 취소 신호 | `VideoCoordinator.request_cancel`의 job Event를 폴링 루프가 `cancel.wait(interval)`로 관찰해 1초 안에 종료 |
| 재시작 복구 | `VideoCoordinator.recover()`가 `running` RenderJob을 `interrupted`로 바꿀 때 `video_provider_jobs`의 `submitted/running` 행을 `unknown`으로 바꾸고 메시지 **"이전 AI 장면 생성 결과를 확인하지 못했습니다. 자동 재요청하지 않습니다."** 를 남긴다. 제공자 호출 0건. |
| 결과 확인 (읽기 전용) | `unknown` 행에 대해 사용자가 명시적으로 누르는 "결과 확인"만 `poll` 1회를 허용(16절 미결). 성공이어도 새 렌더에 자동 재사용하지 않음 |
| 사용량 | 모든 종료 상태(`succeeded/failed/rejected/cancelled/abandoned/expired/unknown`)에 `video_provider_usage` 행 기록 |

`AutopilotService.recover()`는 기존대로 `queued/running` 작업을 `interrupted`로 바꾸며, 이 설계는 그 위에 vendor 행 격리를 더할 뿐이다.

## 9. AI 생성 장면 표시

- 모든 AI 장면에 Pillow 오버레이로 **`AI 생성 장면 · 실제 영상 아님`** 라벨을 각인한다(우상단 띠, `small_font`, 반투명 배경).
  설정이나 폼으로 끌 수 없고 `overlay()`가 `ai_generated=True`면 항상 그린다.
- 작업 상세 최종 체크리스트(`autopilot_job.html`의 `final-checklist`)에 다음 두 항목을 추가한다:
  - `AI 생성 장면이 실제 보도 화면·실제 인물로 오해되지 않는지 (B-roll 전용)`
  - `AI 생성 장면 표시가 화면에 보이는지`
- `backend._queue`의 대기함 설명 접두사: **`AI 생성 장면 포함 · 실제 촬영 아님 · 플랫폼 AI 콘텐츠 표시 요건 확인 필요`**
  (기존 "외부 AI 초안 · 사실 확인 미완료"와 병기).
- `PublishDraft.ai_disclosure`는 사람이 고를 때까지 **`unreviewed`** 유지. 앱이 `disclose`를 미리 선택하지 않는다(16절 미결).
- `video.html`과 작업 상세에 장면별 `clip_source`(`card` / `ai` / `ai_fallback_card`)를 표시한다.

## 10. 뉴스 사실성 검토

- AI 클립은 **B-roll 전용**이다. 보도 장면·실제 인물·실제 사건 재현을 생성하지 않는다.
- 프롬프트는 `NewsArticle.category`별 **고정 영어 템플릿**(`정치/경제/사회/IT·과학/문화/스포츠/국제/미분류`, `ranking.CATEGORY_WORDS` 키와 일치)
  + 고정 안전 접미사(항상 한 줄 상수):
  **`no text, no captions, no logos, no recognizable real people or public figures, no faces in close-up, no depiction of real events, no violence, no weapons`**.
  예: 경제 → "abstract vertical b-roll of a modern city skyline and financial district at dusk, slow camera motion,
  cinematic lighting" + 접미사.
- **내레이션·자막·제목·material·RSS 요약은 프롬프트에 절대 넣지 않는다**(신뢰할 수 없는 외부 입력, prompt injection 경로).
- 선택적 `user_prompt` ≤ 200자: 허용 정규식 `^[A-Za-z0-9 ,.'-]{0,200}$`(영문·숫자·기본 문장부호), URL·`://`·`@` 거부, 템플릿 앞이
  아니라 뒤에 붙이며 안전 접미사는 항상 마지막.
- 전송한 프롬프트 전문은 `video_provider_jobs.prompt`에 감사용으로 저장한다(비밀값·대본 텍스트가 섞일 수 없는 구조).
- `review_notes`에 `ai_scene_generic_broll`(level `info`) 코드를 추가해 "AI 장면은 기사 내용과 무관한 일반 B-roll임"을 대본 검토 화면에 알린다.
- moderation 거부(`video_moderated`)는 종료 상태 `rejected`이며 프롬프트를 바꿔 자동 재시도하지 않고 카드로 대체한다.

## 11. FFmpeg 합성

### 11.1 `ScenePlan`·`RenderPlan` 확장 (`engine.py`)

`ScenePlan`에 `clip: Path | None = None`, `ai_generated: bool = False`를 **기본값 있는 필드로 추가**해 기존 생성자 호출과
`card()`·`command()` 경로를 바꾸지 않는다. `RenderPlan`에 `video_mode: str = "ffmpeg"`, `provider: str | None = None`을 추가한다.

### 11.2 `overlay(plan, scene, index, target, font, *, ai_generated)`

RGBA 투명 캔버스(1080×1920)에 제목, 자막(기존 안전 영역 검사 `len(lines) > 4 or subtitle_y + ... > 1790` 동일), 출처 2줄,
`NEWSFLOW · 미확인 보도 · 사람 검토 필요` 띠, 음성 라벨, 그리고 `ai_generated`일 때 AI 라벨(9절)을 그린다. 자막 뒤에는 반투명
검정 박스를 깔아 밝은 클립 위에서도 읽히게 한다. `card()`는 손대지 않는다.

### 11.3 `clip_command(binary, scene, clip, overlay_png, audio, target, *, loop)` — 상수 argv

```text
ffmpeg -hide_banner -loglevel error -nostdin -n [-stream_loop -1] -i <clip> -i <overlay.png> -i <audio.wav>
  -t <sec> -filter_complex
  '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p[v0];[v0][1:v]overlay=0:0[v]'
  -map '[v]' -map 2:a -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -r 30
  -c:a aac -b:a 128k -af apad -ar 48000 -ac 2 -threads 2 -movflags +faststart <target>
```

- 필터 문자열은 **모듈 상수**이며 사용자 텍스트·파일명이 필터 그래프에 들어가지 않는다(docs/architecture.md "FFmpeg 필터에 사용자 문자열을
  삽입하지 않는다" 규칙). 경로는 `-i` 인수로만 전달하고 작업 폴더 안의 고정 이름(`clip-003.mp4`, `overlay-003.png`)만 쓴다.
- `-stream_loop -1`은 **클립이 장면보다 짧을 때만** 입력 앞에 붙인다. 클립 자체의 오디오 스트림은 **절대 매핑하지 않는다**(`-map 2:a`만).
- 장면 MP4 산출은 기존 `command()` 결과와 같은 프로파일이라 concat manifest·`inspect()`·`_validate`를 그대로 통과한다.

### 11.4 `validate_clip(probe, path)` — 합성 전 ffprobe 검증

컨테이너 `mp4/mov`, 비디오 코덱 `h264/hevc/vp9`, 크기 ≤ 64 MiB, 길이 ≤ 30초·유한, 작업 임시 폴더 안·심볼릭 링크 아님, 비디오 스트림 1개
이상. ffprobe는 기존 `-protocol_whitelist file,pipe`·제한시간·정제된 환경으로 실행한다. 실패 시 `video_clip_invalid`.

### 11.5 메타데이터

`metadata_json`에 `video_mode`, `provider`, `models`(사용 모델 목록), `ai_scenes`(위치 목록), `fallback_scenes`(위치 목록)를 추가한다.
FFmpeg 모드에서는 이 키들을 넣지 않아 **카드 경로의 metadata·산출물이 바이트 단위로 동일**하게 유지된다.

### 11.6 `FFmpegAdapter.render` 흐름 (AI 모드)

1. `plan.validate()` → `check()` → 글꼴 → (audio-fit이면) 음성 합성·`fit_timings` → 장면 초 확정.
2. `VideoCoordinator._run`이 주입한 `clip_planner`가 4절 규칙으로 `ClipRequest` 목록을 만들고 예산 검사(5절) → 제출 → 폴링 → 다운로드 → `validate_clip`.
   이 단계는 `FFmpegAdapter`가 아니라 `VideoCoordinator._run` 안의 `ClipStage`(새 클래스, `video/clips.py`)가 담당하며 `cancel` Event를 공유한다.
3. 각 장면: 클립이 있으면 `overlay()` + `clip_command()`, 없으면 기존 `card()` + `command()`.
4. concat → `inspect()` → `_apply_timings` → `video_scenes.clip_source` 갱신.

## 12. 실패 시 FFmpeg 카드 대체 정책

- **권장: 장면별 대체.** `failed/expired/rejected/cancelled/abandoned/unknown` 클립의 장면은 `clip_source = "ai_fallback_card"`로 기존 카드
  경로를 쓴다. 작업 상세에 **`AI 장면 N개를 만들지 못해 기본 카드로 대체했습니다`** 를 표시한다.
- **작업 전체 실패**: `video_auth_failed`, `video_consent`, `video_budget`, `video_key_missing`, `video_not_ready`는 제출 전/직후 멈추고
  렌더를 시작하지 않는다(카드로 조용히 바꾸지 않는다).
- **조용한 대체는 없다**: 실제 콘텐츠는 항상 `validate` 단계에서 일시정지하므로 사용자가 대체 사실을 보고 나서 대기함에 넣는다.
- 대기함 설명에 **`AI 생성 장면 N개 · 대체 카드 M개`** 를 덧붙인다(N=0이면 AI 접두사 없이 기존 설명만).
- `abandoned` vendor 작업도 사용량에 포함해 월 한도를 보수적으로 소모한다.
- 장면 전체 대체(N=요청 수)면 결과는 사실상 FFmpeg 모드와 같지만 `video_mode`는 `ai`로 남겨 비용·시도 이력을 보존한다.

## 13. 보안

| 위협 | 대응 |
|---|---|
| Prompt injection | RSS·대본·material 텍스트가 프롬프트에 들어가지 않음(10절). `user_prompt`는 허용 정규식·길이·URL 금지. |
| 키 유출 | `Authorization` 헤더에만; 로그·예외 메시지·DB·HTML·`metadata_json`·`stage_results` 금지; `_validated_result` 키 이름 검사; 저장 키·환경 키 모두 secret-in-content 검사. |
| SSRF·리디렉션 | `BoundedDownload`가 `rss_adapter.validate_url`·`public_addresses`·`PinnedConnection`을 재사용. **https만**, 기본 포트만, 리디렉션 거부, `Accept-Encoding: identity`. |
| 호스트 허용 목록 | 코드 상수 `ALLOWED_DOWNLOAD_HOSTS = {<api-host>, <output-cdn-hosts...>}` — 공식 문서로 출력 CDN 호스트를 확인한 뒤 채움(16절 미결). 목록 밖 호스트는 `video_download_failed`. |
| 크기·시간 | ≤ 64 MiB, 전체 읽기 deadline(`PublicTransport`의 deadline 루프와 같은 방식), 청크 64 KiB. |
| 파일 쓰기 | 렌더 임시 폴더 안에 `open("xb")`로만 생성, 심볼릭 링크·폴더 밖 경로 거부, sha256 계산 후 `validate_clip`. **실행 중인 렌더 밖에서는 절대 다운로드하지 않음**. |
| 응답 파싱 | JSON ≤ 256 KiB, 필드 타입 검증, 모르는 필드 무시, 본문·URL 미저장(`request_ref`만). |
| 프로세스 | FFmpeg/ffprobe는 기존처럼 `shell=False`, 인수 배열, `local_process_env()`, 제한시간, stdout/stderr 비저장. |
| GUI | CSP·CSRF·Origin/Host 정책 변경 없음. vendor URL·이미지·플레이어를 HTML에 렌더하지 않음(로컬 MP4만). |
| 비용 폭주 | 작업당 클립·초 상한, 월 한도, 제출 전 검사, 제출 재시도 금지, `Idempotency-Key` + DB unique. |

## 14. 테스트 계획

모두 `FakeVideoProvider` 기반·오프라인. 기본 `python -m pytest -q -rs`에 포함한다.

| 파일 (예정) | 검증 |
|---|---|
| `tests/test_video_provider.py` | Protocol 준수, 12개 오류 코드 매핑, 7.1 상태 전이 표(parametrize), vendor 상태 어휘 변환, `Idempotency-Key` 계산 고정값 |
| `tests/test_video_provider_gate.py` | 체험 제작 거부(`provider.calls == []`), `video_not_ready` 거부, **예산 초과는 제출 전 차단(`provider.calls == 0`)**, 승인 해제가 작업 중간에 반영, `video_cost_ack` 없는 시작 거부 |
| `tests/test_video_clips.py` (coordinator) | 클립 2개 + 카드 1개 합성, 대기열 중 취소 → `provider.cancel` 1회·`cancelled`, running 중 취소 → `abandoned`·cancel 미호출, **폴링 중 `close()` 시 1초 이내 종료**, 재시작 `recover()` → `unknown`·제공자 호출 0건, 문자열 `"SECRET"`이 DB·metadata·stage_results·로그에 없음, 모든 종료 상태에 usage 1행 |
| `tests/test_video.py` 추가 (engine) | `clip_command` argv가 상수와 일치(`-stream_loop` 조건), 클립 오디오 미매핑, `overlay()`가 `ai_generated`일 때만 AI 라벨 픽셀을 그림(픽셀 샘플 비교), `validate_clip`이 잘못된 파일을 **ffmpeg 실행 전** 거부, 카드 경로 산출물 바이트 동일(기존 fixture 해시) |
| Windows CI (`newsflow-phase5d-windows.yml`, 예정) | 실제 FFmpeg로 `lavfi testsrc` 합성 클립(5초)을 만들어 `clip_command` 합성·concat·`inspect` 통과 |
| `tests/test_video_provider_migration.py` | 0010 upgrade, 반복 upgrade 멱등, **0009 → 0010이 기존 행 보존**, server_default 값 확인, 여섯 schema-head 단언 갱신 |
| `tests/test_easy_ui.py` 추가 (GUI) | 준비 칩 문구, 체험·미준비 시 `ai` 라디오 `disabled`+사유, 설정 저장 응답에 키 값 미포함(`"SECRET" not in body`), 스냅샷 `video_mode/ai_scenes/provider_status` |
| `tests/test_live_video_provider.py` (opt-in) | `NEWSFLOW_LIVE_VIDEO_TEST=1` + 키 + 예산 게이트가 모두 있을 때만, 가장 싼 모델 ≤ 5초 1건. 기본 스위트·CI에서는 `skip`. |

## 15. 공식 문서로 재확인할 vendor 사실 목록

상태는 전부 **NOT VERIFIED**이다. 확인 URL·날짜 열은 구현 착수 시 채운다(publishing_platforms.md 형식).

| 항목 | 현재 가정 | 상태 | 확인 URL·날짜 |
|---|---|---|---|
| Base URL·엔드포인트 경로 | `https://<api-host>/<version>/...` 제출·상태·취소 분리 | NOT VERIFIED | |
| 인증 헤더 형식·키 형식/길이 | `Authorization` 헤더, 스킴 `Key` 또는 `Bearer`, 키 20–256자 | NOT VERIFIED | |
| 제출 응답 필드 | `request_id`, `status_url`, `cancel_url`; status_url에 자격증명 포함 여부 | NOT VERIFIED | |
| 상태 어휘·오류 payload | `queued/in_progress/completed/failed/nsfw/canceled`, 오류 객체 구조 | NOT VERIFIED | |
| 취소 방법·의미·취소 작업 청구 | POST 취소, 대기열에서만 가능, 청구 여부 | NOT VERIFIED | |
| `Idempotency-Key` 의미 | 헤더 지원 여부·중복 제출 시 동일 응답 여부·유효기간 | NOT VERIFIED | |
| 폴링 권장·rate limit·동시성 티어 | 2–10초, 429 Retry-After, 계정별 동시 작업 수 | NOT VERIFIED | |
| 출력 URL 수명·컨테이너·코덱·해상도·fps·오디오·워터마크·C2PA | 서명 URL 수명, mp4/h264, 1080×1920, 24–30fps, 오디오 포함 여부, 워터마크·C2PA 메타데이터 | NOT VERIFIED | |
| 모델별 길이 범위·스텝·9:16·이미지 입력·프롬프트 길이·moderation | 2–10초, 1초 스텝, 9:16 지원, image-to-video, 프롬프트 ≤ N자, moderation 기준 | NOT VERIFIED | |
| 초당 가격·실패 시 환불 | 모델별 초당 과금, 실패/거부 시 환불 여부 | NOT VERIFIED | |
| 선불 잔액·0비용 잔액 조회 | 선불 크레딧, 잔액 조회 엔드포인트가 무료인지 | NOT VERIFIED | |
| 이용약관: 상업적 이용 | 생성물 상업 이용 허용 범위 | NOT VERIFIED | |
| 이용약관: 학습 이용 라이선스 | 프롬프트·입력 이미지·출력의 모델 학습 이용 여부·opt-out | NOT VERIFIED | |
| 금지 콘텐츠 | 실제 인물, 뉴스/정치 묘사, 기타 금지 범주 | NOT VERIFIED | |
| AI 콘텐츠 표시 의무 | vendor 약관상 표시 의무와 플랫폼(YouTube `containsSyntheticMedia`, Instagram `is_ai_generated`) 요건의 관계 | NOT VERIFIED | |
| 프롬프트·출력 데이터 보존 | vendor 측 보관 기간·삭제 요청 방법 | NOT VERIFIED | |

## 16. 범위 제외와 미결 질문

### 16.1 범위 제외

Webhook 수신(앱은 폴링만), 스케줄러·예약 실행, OAuth/SNS 게시, 무인 운영, 영상 업스케일·립싱크·음성 생성 등 다른 vendor 기능,
AI 장면에 맞춘 대본·자막 자동 수정, Linux/Docker 배포.

### 16.2 미결 질문 (제품 오너 결정 필요)

1. **장면별 대체 vs 작업 전체 실패**: 12절은 장면별 대체를 권장한다. 한 장면이라도 실패하면 전체를 멈추는 보수적 옵션을 설정으로 둘지.
2. **사용자 입력 단가 허용 여부**: 표시 전용 추정이라도 "비용을 계산하지 않는다"는 기존 문구와 충돌하지 않는지, 아니면 초 단위 한도만 둘지.
3. **작업별 확인 체크박스 위치**: 시작 폼(계획 초를 아직 모름) vs 대본 검토 일시정지(장면 초 확정 후 정확한 추정 가능).
4. **`unknown` 작업의 읽기 전용 재조회 허용 여부**: 허용하면 제공자 호출이 1회 발생하고, 금지하면 결과를 영영 모른다.
5. **초기 모델 허용 목록**: 공식 카탈로그 확인 후 1–2개로 시작할지.
6. **backend 렌더 제한시간**: 1500초가 적절한지, 클립 수에 비례시킬지.
7. **`ai_disclosure` 사전 선택**: AI 장면 포함 초안에 `disclose`를 미리 고를지(9절은 `unreviewed` 유지를 권장).
8. **출력 호스트 허용 목록**: 출력 CDN 호스트가 여러 개이거나 바뀌는 경우 코드 상수 갱신 주기.

---

Phase 5C.1 범위에서는 이 문서와 `tests/test_phase5d_design_doc.py`만 추가하며 코드·마이그레이션·설정·GUI 변경은 없다.
