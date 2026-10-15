# NewsFlow AI — Phase 5D Higgsfield API 검증 결과

확인일: 2026-10-15(KST, UTC+9). 담당: Claude Code. 이 문서는 Phase 5D 지시의 "Higgsfield 공식 개발자 문서 검증" 7개 항목에 대한 결과입니다. **실제 Higgsfield API·MCP 호출, 계정 가입, 키 발급, 유료 생성은 0건**입니다(사용자 승인 전 금지).

판정 표기

- **VERIFIED (공식 코드)**: Higgsfield가 직접 배포한 코드·패키지에서 원문을 확인했습니다. 공급사 서버의 실제 동작을 호출로 확인한 것은 아닙니다.
- **CONFLICTING**: 공식 출처끼리 내용이 다릅니다. 이 앱이 택한 방향을 함께 적습니다.
- **NOT VERIFIED**: 공식 문서 사이트를 열지 못해 검색 요약으로만 봤거나 아예 찾지 못했습니다. 구현 완료로 보고하지 않습니다.

## 1. 확인 방법과 한계

| 출처 | 버전·커밋 | 접근 결과 |
| --- | --- | --- |
| `docs.higgsfield.ai`, `higgsfield.ai`, `open.`·`cloud.`·`console.`·`status.higgsfield.ai` | — | **열지 못함**. WebFetch `getaddrinfo ENOTFOUND`, 세션 프록시 `CONNECT 403 (connect_rejected)`. 프록시 정책을 우회하지 않았습니다. |
| 공식 Python SDK `higgsfield-client` (PyPI, author `support@higgsfield.ai`) | 0.2.0 (2026-09-17), wheel sha256 `66a6310c2d9b210f021848eb9e03ed1a8c2991e2e8a1a328c470ce39a033f633` | 내려받아 소스 전체 확인 |
| 공식 JS SDK `@higgsfield/client` (npm, higgsfield-ai 조직) | 0.2.6 (2026-10-06) | README·소스 확인 |
| 공식 앱 템플릿 `github.com/higgsfield-ai/app-templates` (조직 도메인 인증 `higgsfield.ai`) | 커밋 `1e15e224f2815d7d854ea3df27aded6f4e6fefdd` (2026-10-06) | 복제해 `generation/platform.ts`·`credentials.ts`·`poll.ts`·`catalog/` 확인 |
| 공식 CLI·에이전트 스킬 `github.com/higgsfield-ai/cli`, `higgsfield-ai/skills` | main (2026-10-15 조회) | README·MODELS.md·model-catalog 확인. CLI 모델 ID(`kling3_0`)는 REST 경로(`kling-video/v3.0/std`)와 다른 체계라 REST 근거로 쓰지 않음 |
| 검색 엔진 요약(문서 사이트 색인) | — | 참고만. 전부 NOT VERIFIED |

조사 결과는 주장 183건(독립 재확인 CONFIRMED 91 · 확인 불가 90 · 반박 2)으로 정리했습니다. 반박된 2건은 "npm 관리자 전원이 @higgsfield.ai 메일 사용"(5명 중 4명)과 "SDK에 오류 클래스 문서 없음"(Agent API 오류 클래스가 README에 있음)이며 이 앱 설계에는 영향이 없습니다.

## 2. 7개 검증 항목

### 2.1 API 접근 방식과 인증

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 기본 주소 `https://api.higgsfield.ai` | VERIFIED (공식 코드) | Python SDK `BASE_URL = 'https://api.higgsfield.ai'`, JS SDK `baseURL`, 템플릿 `.env.example` `HF_API_BASE_URL=https://api.higgsfield.ai` |
| 인증 헤더 `Authorization: Key <키>` | VERIFIED (공식 코드) | 템플릿 `credentials.ts` `` return `Key ${requireApiKey(apiKey)}` `` |
| 키 형식: open.higgsfield.ai에서 복사한 단일 키(공백 없는 인쇄 가능 ASCII) vs SDK의 `KEY_ID:KEY_SECRET` | CONFLICTING | 템플릿(가장 최신): 단일 키, `/[^\x21-\x7E]/` 거부. SDK: `` `Key ${apiKey}:${apiSecret}` ``. 키 발급 위치도 cloud./console./open. 세 가지로 갈림 |
| 다른 호스트 `platform.higgsfield.ai` | CONFLICTING · NOT VERIFIED | 검색 요약에만 있음. 같은 요약에 "2026-10-31까지 api.higgsfield.ai로 이전"이라는 문구도 있음 |
| 키는 서버에서만 사용, 브라우저 노출 금지 | VERIFIED (공식 코드) | JS SDK README "Server-side only (browser usage blocked for security)" |
| 요청 한도·동시 처리 수 | NOT VERIFIED | 검색 요약: 동시 요청 4개 초과 시 400. SDK·CLI 문서는 429를 재시도 대상으로 둠 |

이 앱의 선택: 호스트는 `api.higgsfield.ai` 하나로 고정했습니다. 키는 두 형식 모두 받도록 `[\x21-\x7E]{8,520}` 패턴만 검사하고, 앱 화면은 공식 템플릿 안내대로 "open.higgsfield.ai에서 복사한 값을 그대로"라고 안내합니다. 키는 OpenAI 키와 별도의 DPAPI 파일 `video-ai-key.dpapi`(또는 환경변수 `NEWSFLOW_VIDEO_AI_KEY`)에 두고 DB·로그·화면에 남기지 않습니다.

### 2.2 사용 가능한 영상 모델

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 모델은 경로형 ID이고 `POST {base}/{모델 경로}`로 제출 | VERIFIED (공식 코드) | 템플릿 `platform.ts` `send("POST", `/${model}`, input)` |
| 텍스트→영상 경로: `kling-video/v3.0-turbo/text-to-video`, `kling-video/v2.6/pro/text-to-video`, `alibaba/wan-3.0/text-to-video`, `alibaba/wan-3.0-prime/text-to-video`, `wan/v2.7/text-to-video`, `wan/v2.6/text-to-video`, `pixverse/v6/text-to-video`, `lightricks/ltx-2.5/text-to-video/fast`, `minimax/hailuo-2.3/standard/text-to-video`, `bytedance/seedance-2.5/text-to-video`, `kling-video/v3.0/{std,pro,4k}/text-to-video` 등 | VERIFIED (공식 코드) | 템플릿 `catalog/models/*.ts` |
| 일반 영상 모델 요청 항목 `prompt`·`aspect_ratio`·`resolution`·`duration`(숫자, 초) | VERIFIED (공식 코드) | 템플릿 `mappers.ts` `mapByPaths`, Kling 3.0 Turbo 매퍼도 같은 4개 항목 |
| Kling 3.0 Std/Pro는 `resolution` 대신 `sound`·`cfg_scale`·`multi_shots`, Seedance는 `generate_audio`·`bitrate_mode` 추가 | VERIFIED (공식 코드) | 템플릿 `kling-3.ts` `mapKling3`, `mappers.ts` `seedanceBody` |
| 세로 9:16 지원 | VERIFIED (공식 코드, 템플릿 UI 값) | 템플릿 기본 영상 화면비 `["16:9", "9:16", "1:1"]`, Seedance `SEEDANCE_ASPECT`에 `9:16` |
| 모델별 허용 길이·해상도의 서버 기준값 | NOT VERIFIED | 템플릿 일반 모델은 공통 기본값(4–10초, 720p/1080p)을 물려받을 뿐 모델별 서버 한도가 아님. CLI 표와 다른 모델이 있음(MiniMax: 화면비 없음, 512/768/1080) |

이 앱의 선택: 모델 목록은 코드에 고정하지 않고 사용자가 설정 화면에서 경로·허용 길이·초당 단가를 입력하고 "공식 문서와 대시보드에서 직접 확인" 체크를 해야 쓸 수 있게 했습니다. 입력 후보(datalist)에는 템플릿 요청 항목이 이 앱과 같은 4개 항목이고 9:16을 지원하는 8개 경로만 넣었고, MiniMax·Seedance·Kling 3.0 Std/Pro는 요청 항목이 달라 넣지 않았습니다.

### 2.3 요청 생성과 비동기 작업 조회

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 제출 응답 `request_id`·`status`·`status_url`·`cancel_url` | VERIFIED (공식 코드) | 템플릿 `mapQueued`, Python SDK |
| 상태 조회 `GET {base}/requests/{id}/status` | VERIFIED (공식 코드) | 템플릿 `status()`, Python SDK `status_url` |
| 상태 값 `queued`·`in_progress`·`completed`·`failed`·`nsfw`·`canceled` | VERIFIED (공식 코드) | Python SDK 상태 클래스, 템플릿 `poll.ts` `TERMINAL` (JS SDK 0.2.6 V2 타입에는 `canceled` 없음 → CONFLICTING 경미) |
| 폴링 간격·제한시간 | VERIFIED (공식 코드, 클라이언트 기본값) | 템플릿 4초·10분, JS SDK 2초·5분. 서버의 실제 생성 소요 시간은 NOT VERIFIED |
| 웹훅 `?hf_webhook=<url>` | VERIFIED (공식 코드) · 서명·재전송 규칙 NOT VERIFIED | Python SDK `utils.py`. 이 앱은 로컬 PC 앱이라 웹훅을 쓰지 않고 폴링만 함 |

이 앱의 선택: 작업자 스레드가 상태를 5~60초(기본 10초) 간격으로 확인하고, 장면별 제한시간 5~120분(기본 30분)을 넘기면 취소를 시도한 뒤 `video_ai_timeout`으로 실패 처리합니다. 동시 생성 수는 1~4(기본 2)입니다.

### 2.4 결과 다운로드 방식과 보관 기간

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 완료 시 영상 주소는 `video.url` | VERIFIED (공식 코드) | 템플릿 `mapStatus` `asRecord(data.video).url`, JS SDK V2 타입 |
| 상태 응답이 결과 본문이며 `request_id`로 다시 조회 가능 | VERIFIED (공식 코드) | Python SDK `result(request_id)` |
| 결과 파일 보관 "최소 7일" | NOT VERIFIED | 검색 요약만 |
| 결과 CDN 호스트, 서명·만료 주소 여부, 컨테이너·코덱·최대 크기 | NOT VERIFIED | 공식 예시는 `.mp4`로 끝나는 자리표시자 주소뿐 |

이 앱의 선택: 결과 호스트를 몰라 허용 목록을 만들 수 없으므로 안전 다운로더가 모든 주소를 같은 규칙으로 검사합니다(HTTPS만, 사설·예약 주소 거부와 DNS 고정, 리디렉션 3회마다 재검사, 200 MiB·시간 제한, 영상 콘텐츠 형식만, 인증 헤더를 보내지 않음). 받은 파일은 ffprobe로 형식·코덱·해상도·길이를 검사한 뒤에만 장면에 연결하고, 앱 데이터 폴더 `ai-clips`에 보관하므로 공급사 보관 기간과 무관하게 재합성할 수 있습니다.

### 2.5 사용량·가격·크레딧 구조

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 선불 USD 잔액, 초당 과금(영상), 최소 충전 $5 | NOT VERIFIED | 검색 요약만 |
| 모델별 단가 예: Kling 3.0 Std $0.042/초(할인가), Seedance 2.5 480p $0.2056/초 등 | CONFLICTING · NOT VERIFIED | 검색 요약·제3자 글. 할인 기간·해상도별로 달라짐 |
| 잔액·비용 조회 API | NOT VERIFIED | REST 견적 엔드포인트 경로를 찾지 못함 |
| failed·nsfw 요청은 크레딧 환불 | VERIFIED (공식 코드 문서) · 서버 동작 NOT VERIFIED | JS SDK README 문구만. 대기 중 취소 시 환불 여부는 확인 못 함 |

이 앱의 선택: 가격을 코드에 넣지 않았습니다. 사용자가 모델별 초당 단가를 입력하고, 예상 비용 = 클립 초 × 초당 단가로 계산합니다. AI 영상 한도(작업별·월, USD 또는 KRW)는 대본용 OpenAI 토큰 한도와 별도의 설정·사용 기록 표(`video_ai_usage`)로 관리합니다. 환불 여부가 확인되지 않았으므로 보내지 않은 요청(`not_sent`)만 빼고 실패·취소·결과 불명 요청도 이번 달 사용액에 넣어 한도를 보수적으로 계산합니다.

### 2.6 실패 처리·제한시간·재시도·취소

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 취소 `POST {base}/requests/{id}/cancel`, 대기 중만 가능, 202 후 `canceled` | VERIFIED (공식 코드 주석) | 템플릿 `platform.ts` "Queued requests only; the platform answers 202 and the status turns "canceled"" |
| 처리 시작 후 취소는 400 | VERIFIED (공식 코드) | Python SDK |
| 오류 본문 `detail`, 실패 상태에 선택적 `error` 항목 | VERIFIED (공식 코드) | 템플릿 `messageFromBody`, `mapStatus` |
| 공식 Python SDK는 408·429·5xx에서 **제출(POST)까지** 자동 재시도 | VERIFIED (공식 코드) | wheel 0.2.0 `retry.py` `DEFAULT_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}`, 메서드 구분 없음 → 중복 청구 위험 |
| `Idempotency-Key` 지원 | CONFLICTING · NOT VERIFIED | 검색 요약끼리 "지원" / "지원 안 함"이 갈림 |
| 401=키, 403=잔액 부족 또는 권한 거부, 404=모델·요청 없음 | CONFLICTING | JS SDK는 403을 잔액 부족, 템플릿은 401/403을 키 거부, Agent API는 402를 잔액 부족으로 봄 |

이 앱의 선택:

- SDK를 쓰지 않고 표준 라이브러리 HTTPS 클라이언트로 직접 구현했으며 **제출은 절대 재시도하지 않습니다**. 연결 전 실패만 "보내지 않음"으로 보고, 보낸 뒤의 연결 끊김·5xx·읽을 수 없는 2xx는 `unknown`(결과 불명)으로 둡니다. 사용자가 공급사 대시보드를 확인하고 실패로 확정하기 전에는 다시 보내지 않습니다.
- 429·408만 같은 시도 안에서 최대 3번 다시 대기열에 넣습니다.
- 제출에 장면 시도별 `Idempotency-Key`(UUID)를 붙입니다. 결과 불명 요청을 다시 보낼 때만 같은 키를 재사용해, 공급사가 이 헤더를 지원한다면 첫 요청이 돌아오고 두 번째 청구가 생기지 않게 합니다. 지원 여부가 NOT VERIFIED이므로 중복 방지는 이 헤더에 의존하지 않습니다(재시도 금지·`unknown` 상태·작업자 파일 잠금·비교 후 갱신이 1차 방어).
- 403은 "잔액·권한 부족", 401은 "키 확인", 400·422는 "요청 거부(동시 요청이 많은지도 확인)"로 안내합니다.

### 2.7 상업적 이용 약관과 콘텐츠 정책

| 사실 | 판정 | 근거 |
| --- | --- | --- |
| 이용약관 2026-07-26 개정, 결과물 소유권을 주장하지 않고 상업적 이용 제한 없음(4.4) | NOT VERIFIED | 검색 요약만 |
| 입력·결과가 모델 학습에 쓰일 수 있음(엔터프라이즈 제외) | NOT VERIFIED | 검색 요약만 |
| 법이 요구하는 경우 AI 생성 사실 고지, 출처 표시(워터마크·C2PA) 제거 금지(5.5, 6.4) | NOT VERIFIED | 검색 요약만 |
| 개발자 조항(11): AI 결과를 사람이 만든 것처럼 제시 금지, 키 기밀 유지·클라이언트 노출 금지 | NOT VERIFIED | 검색 요약만 |
| 실존 인물 초상·딥페이크·사칭 금지, 모델별 모더레이션 | NOT VERIFIED | 검색 요약만 |

이 앱의 선택: 약관을 확인하지 못했으므로 상업 이용은 사용자가 공식 약관을 직접 확인해야 하는 항목으로 남깁니다(설정 화면 승인 문구와 사용자 안내서). 대신 약관 요약보다 엄격하게, 실제 현장·기록 영상·실존 인물·딥페이크·CCTV 등을 요청하는 프롬프트를 보내기 전에 거부하고, 모든 프롬프트 끝에 "추상 일러스트, 실사·다큐·뉴스 영상 아님, 실존 인물·얼굴·장소·로고·문자 없음" 문장을 붙이며, 최종 영상의 AI 장면마다 끌 수 없는 "AI 생성 장면 · 실제 현장 영상 아님" 표시를 입힙니다. 체험(합성) 뉴스 대본은 외부로 보내지 않습니다.

## 3. 출처 간 충돌과 이 앱의 결정

| 충돌 | 결정 |
| --- | --- |
| 키 형식(단일 키 vs `KEY_ID:KEY_SECRET`) | 둘 다 받음. 첫 실제 호출 전에 사용자가 발급 화면에서 형식 확인 |
| 호스트(`api.` vs `platform.`) | `api.higgsfield.ai`만 허용(공식 코드 3곳 일치) |
| 한도 초과 상태 코드(400 vs 429) | 429·408만 재대기, 400은 실패(비용은 보수적으로 계산) |
| 403 의미 | 잔액·권한을 함께 안내 |
| Idempotency-Key | 보내되 의존하지 않음 |
| 환불 | 사용액에 포함(보수적) |
| Seedance 2.5 해상도(480p/720p vs 최대 1080p) | 후보 목록에서 제외, 사용자가 확인 후 직접 등록 |

## 4. 첫 실제 호출 전에 사용자가 확인할 것 (NOT VERIFIED 목록)

1. API 키 발급 위치와 형식(open.higgsfield.ai API Keys 화면).
2. 쓰려는 모델의 REST 경로, 허용 길이, 9:16·해상도 값, 초당 단가(공식 문서·대시보드).
3. 잔액 충전 방식·최소 금액, 실패·NSFW·취소 요청의 청구·환불 규칙.
4. 결과 파일 보관 기간과 형식.
5. 동시 요청 한도와 초과 시 상태 코드.
6. 이용약관의 상업적 이용·AI 고지·학습 이용 조항.

확인 전에는 앱 설정의 "유료 생성 승인"과 모델별 "공식 문서 확인" 체크를 하지 않아야 하며, 이 체크가 없으면 앱은 외부로 아무 요청도 보내지 않습니다.

## 5. 이 단계의 실제 호출 기록

- Higgsfield REST API 호출: 0건. Higgsfield MCP 도구 호출: 0건. 키 발급·가입·결제: 없음.
- 자동 테스트와 CI는 `FakeVideoProvider`(외부 호출 없음, 테스트 주입 전용, 설정 화면에서 고를 수 없음)와 가짜 요청 함수만 사용합니다.
