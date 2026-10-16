# Phase 5D.1 Higgsfield 공식 API 재검증

확인일: **2026-10-16 KST**. 공개 공식 문서의 HTTPS GET만 수행했다. 실제 인증·estimate·생성·취소 API 호출은 **0건**, 발생 비용 **0**이다. 아래 PASS는 문서 확인을 뜻하며 실제 서비스 검증을 뜻하지 않는다. HTTP 상태·최종 URL·확인 시각·응답 SHA256은 [조회 증거](evidence/phase5d1/official-docs-access.json)에 보존했다. 이전 5D 보고서의 접근 제한은 당시 기록으로 유지한다.

## 인증·요금·운영 조건

| 항목 | 공식 근거 | 확인 결과 및 적용 |
| --- | --- | --- |
| 키 형식·인증 | [Authentication](https://docs.higgsfield.ai/docs/authentication.md) | PASS: 서버 측 `Authorization: Key KEY_ID:KEY_SECRET`. 기존 단일 키의 실제 호환성은 NOT VERIFIED. 키 발급·인증은 실행하지 않았다. |
| Idempotency-Key | [Idempotent requests](https://docs.higgsfield.ai/docs/concepts/idempotency.md) | PASS: 선택 헤더, 1–255 visible ASCII, 계정 단위·키 교체 후 유지. 같은 endpoint/body/webhook이면 기존 요청 ID 반환; 다른 매개변수는 422. terminal 요청을 재시작하지 않는다. 실제 계정 동작은 NOT VERIFIED. |
| 오류·재시도 | [Errors and retries](https://docs.higgsfield.ai/docs/concepts/errors.md) | PASS: 400 입력/동시성, 401 인증, 403 잔액, 404, 422, 423, 500/503 설명. 문서는 동일 키 재전송을 안내하지만 앱은 더 보수적으로 **모든 제출 POST 자동 재전송 금지**. 408·429가 미접수라는 보장은 확인하지 못했다. |
| 요금·크레딧 | [Billing and retention](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md) | PASS: 성공 생성에 크레딧 사용, 모델/매개변수별 비용, API 문서는 크레딧 1년 만료를 명시하나 일반 약관 §9.4/§9.6은 구독 기간 종료/추가 구매 90일을 명시하여 **계정·상품별 적용 기간은 NOT VERIFIED**. 인증된 `POST /estimate/{model}` 문서 존재. **실제 모델별 금액·계정 잔액 NOT VERIFIED**; 예제 숫자와 웹 구독 가격을 API 단가로 사용하지 않았다. estimate 호출 0건. |
| 실패·취소·환불 | [Billing](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md), [Cancel](https://docs.higgsfield.ai/docs/api-reference/requests/cancel-a-queued-request.md) | PASS: failed/nsfw 예약 크레딧 환불, 처리 전 queued 취소 성공 시 환불이라고 명시. 실제 환불 NOT VERIFIED. 앱은 공급사 청구서를 조회하지 않으므로 실패·취소·결과 불명 비용을 보수적으로 유지한다. |
| 결과 보관 | [Billing](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md) | PASS: 생성 후 최소 7일 접근, 이후 제거 가능. 받은 로컬 클립을 보존한다. 실제 보관 기간 NOT VERIFIED. |
| 동시성 | [Rate limits](https://docs.higgsfield.ai/docs/concepts/rate-limits.md) | PASS: 계정·모델별 콘솔 값, 주로 queued/processing 개수 제한. 문서 예시 4를 보편 한도로 사용하지 않는다. 표준 rate-limit/Retry-After 헤더 미제공. 실제 계정 제한 NOT VERIFIED. |
| 상태 조회 | [Get request status](https://docs.higgsfield.ai/docs/api-reference/requests/get-request-status.md) | PASS: 기존 요청 ID로 조회. 재시작 시 조회/다운로드를 이어가며 번호 없는 결과 불명은 잠근다. |
| 상업 이용 | [Terms of Use Agreement](https://higgsfield.ai/terms-of-use-agreement), 2026-07-26 갱신, §4.4·§9.3·§11 | PASS: §4.4는 입출력 소유권을 주장하지 않고 상업 이용을 제한하지 않는다고 설명. 제3자 권리·프롬프트 권한 보증은 별개. Enterprise 예외 외 입력/출력의 학습 사용 조건 확인 필요. §9.3 미사용 크레딧 구매 환불과 생성 실패 크레딧 환불을 구분해야 한다. API 개발자 조건에는 독립적 가치 없는 재판매/패스스루 제한 등이 있다. 개별 사용의 법적 적합성 NOT VERIFIED. |

## 모델별 요청 스키마

공통 요청은 `prompt`, 정수 `duration`, `aspect_ratio="9:16"`, `resolution` 4필드다. 아래 문서는 모두 HTTP 200으로 읽고 입력 JSON schema를 비교했다. 추출한 8개 스키마는 `evidence/phase5d1/model-schemas/schema-40.json`~`schema-47.json`에 표의 원래 조회 순서(Kling3, Kling2.6, Wan2.6, Wan2.7, Wan3, Wan3prime, Pixverse, LTX)로 보존했다. 이름이 비슷한 모델끼리 스키마를 추정하지 않았다. 앱의 설정 해상도는 기존 480p/720p/1080p와의 교집합만 사용한다. 표의 지원은 문서 기준이며 실제 생성·권한·가격은 전부 NOT VERIFIED다.

| 공식 문서 / endpoint | 길이(초) | 해상도 | 9:16 / 현재 어댑터 |
| --- | --- | --- | --- |
| [Kling 3 turbo](https://docs.higgsfield.ai/docs/models/kling-3/turbo-text-to-video.md) / `kling-video/v3.0-turbo/text-to-video` | 정수 3–15 | 720p,1080p | 문서 PASS / 필드 일치 |
| [Wan 2.7](https://docs.higgsfield.ai/docs/models/wan-2-7/text-to-video.md) / `wan/v2.7/text-to-video` | 정수 2–15 | 720p,1080p | 문서 PASS / 필드 일치 |
| [Wan 3](https://docs.higgsfield.ai/docs/models/wan-3/text-to-video.md) / `alibaba/wan-3.0/text-to-video` | 정수 2–30 | 480p,720p,1080p | 문서 PASS / 필드 일치 |
| [Wan 3 prime](https://docs.higgsfield.ai/docs/models/wan-3-prime/text-to-video.md) / `alibaba/wan-3.0-prime/text-to-video` | 정수 2–30 | 480p,720p,1080p | 문서 PASS / 필드 일치 |
| [Pixverse v6](https://docs.higgsfield.ai/docs/models/pixverse-v6/text-to-video.md) / `pixverse/v6/text-to-video` | 1–15 (문서는 소수도 허용; 앱은 정수만) | 360p,540p,720p,1080p | 문서 PASS / 필드 일치 |
| [LTX 2.5 fast](https://docs.higgsfield.ai/docs/models/ltx-2-5/text-to-video-fast.md) / `lightricks/ltx-2.5/text-to-video/fast` | 6,8,10 | 720p,1080p,2k,4k | 문서 PASS / 필드 일치 |
| [Kling 2.6 pro](https://docs.higgsfield.ai/docs/models/kling-2-6/pro-text-to-video.md) / `kling-video/v2.6/pro/text-to-video` | 5,10 | **resolution 필드 없음** | 9:16 명시 / 현재 어댑터 **차단** |
| [Wan 2.6](https://docs.higgsfield.ai/docs/models/wan-2-6/text-to-video.md) / `wan/v2.6/text-to-video` | 5,10,15 | 720p,1080p | **aspect_ratio 필드 없음**, 현재 어댑터 **차단** |

모델별 기본 음성 생성, fps, 추가 옵션이 비용과 결과에 영향을 줄 수 있다. 현재 어댑터가 생략한 옵션의 공급사 기본값까지 확인한 단가를 입력해야 한다. 초당 단가 모델은 실제 견적 API와 연결되지 않은 사용자 추정치다. 공식 문서의 임의 예제 가격을 채워 넣지 않았다. 사용자 입력의 기타 모델은 기존 명시적 확인 정책을 유지하며 사전 점검에서 NOT VERIFIED로 표시한다. 날짜가 지난 스냅샷은 최신 공급사 변경을 자동 감지하지 않는다.

## 공식 문서 사이의 적용 범위 불확실성

API billing 문서의 크레딧 1년과 일반 약관 §9.6의 추가 구매 90일은 서로 다르다. §11.1은 API에도 일반 약관이 적용된다고 설명한다. API 전용 잔액과 웹 구독/추가 구매 상품의 차이인지, 어느 조건이 우선하는지는 공개 문서만으로 확정하지 않았다. 실제 구매·유료 검증 전에 계정에 적용되는 만료 기간과 약관을 공급사에 확인해야 한다. 앱은 만료 기간을 추정하거나 잔액을 자동 충전하지 않는다.

## 적용 결정

- 제출 408/429/서버 오류·전송 중 단절·잘못된 접수 응답은 결과 불명으로 보존, 자동 POST 0회.
- 5D의 `waiting + requeues` 행도 새 제출 전에 결과 불명으로 격리한다. 기존 비용/클립 삭제·환불 추정 없음.
- 알려진 스키마 불일치는 키 조회·네트워크 전에 거절한다. 그 외 로컬 설정 검사는 실제 인증이나 유료 실행 승인이 아니다.
- 실제 유료 생성은 이번 개발에서 실행하지 않는다. 계정·가격·동시성·약관 재확인과 별도 사용자 승인이 선행되어야 한다.
