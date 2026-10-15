# Phase 5D · AI 고품질 제작(선택 공급사) 구현 설계

작성: 2026-10-15(KST). 상태: **구현 완료(Fake 공급자로 검증)**. 실제 Higgsfield 호출·가격·품질은 사용자 승인 전까지 **NOT VERIFIED**입니다. 5C.1 설계 초안([phase5d_higgsfield_video_provider.md](phase5d_higgsfield_video_provider.md))과 달라진 점은 13절에 있습니다. 공급사 사실의 근거는 [Higgsfield API 검증 결과](../reports/phase5d_higgsfield_api_verification.md)입니다.

## 1. 범위와 두 제작 모드

| 모드 | 화면 | 외부 호출 | 비용 |
| --- | --- | --- | --- |
| 기본 모드 · 로컬 FFmpeg | `/video`, 자동 제작 | 없음 | 없음 |
| AI 고품질 모드 · 공급사 생성 + FFmpeg 합성 | `/video` → `/video/ai` | 사용자가 'AI 생성'으로 고른 장면만, 승인 후 | 사용자가 입력한 단가로 예상, 작업별·월 한도 |

AI 영상 설정의 기본값은 공급사 '사용 안 함'(`off`)이며, 이 상태에서는 기본 모드만 동작합니다. 자동 제작(Autopilot)은 카드 영상만 만듭니다.

## 2. 공급사 계약

`src/newsflow/video/ai/contracts.py`의 `VideoProvider` Protocol은 공급사와 무관합니다.

| 메서드 | 의미 | 규칙 |
| --- | --- | --- |
| `submit(ClipRequest) -> Submission` | 텍스트→영상 요청 1건 | **재시도 금지**(재전송은 이중 청구 위험) |
| `status(request_id) -> ClipStatus` | `queued`·`in_progress`·`completed`·`failed`·`nsfw`·`canceled` | 완료 시 결과 주소 |
| `cancel(request_id) -> bool` | 대기 중 요청만 취소 | 시작된 요청은 False |
| `fetch(ClipStatus, target, cancel) -> FetchResult` | 결과 파일을 안전하게 저장 | 크기·해시·호스트만 반환 |

`ClipRequest`는 모델 경로, 프롬프트(스타일 문장 포함), 초, 해상도, 화면비 `9:16`, 장면 시도별 `idempotency_key`를 담습니다. 오류는 `VideoProviderError` 하위 클래스이며 고정 한국어 문장과 `sent`(외부로 나갔는지)를 가집니다.

| 코드 | 뜻 | `sent` | 사용량 |
| --- | --- | --- | --- |
| `video_ai_key_missing` | 키 없음·형식 오류 | False | 보내지 않음 |
| `video_ai_auth_failed` | 401 | True | 실패(계산) |
| `video_ai_credits` | 402·403 잔액·권한 | True | 실패 |
| `video_ai_bad_input` | 400·422 또는 보내기 전 경로 오류 | 경우별 | 실패 또는 보내지 않음 |
| `video_ai_bad_model` | 제출 404 | True | 실패 |
| `video_ai_rate_limited` | 408·429 → 같은 시도에서 3번까지 다시 대기 | True | 예약 유지 |
| `video_ai_unavailable` | 연결 전 실패 | False | 보내지 않음 |
| `video_ai_unknown_submit` | 보낸 뒤 결과 불명(끊김·5xx·읽을 수 없는 2xx) | True | 결과 불명(계산) |
| `video_ai_request_missing` | 상태·취소 404 | True | 실패 |
| `video_ai_download_failed`·`video_ai_clip_invalid`·`video_ai_disk_full` | 완료 후 받기·검증·공간 문제 | — | 완료(계산), 다시 받기 가능 |
| `video_ai_timeout` | 장면별 제한시간 초과 | True | 실패(계산), 다시 받기 가능 |

## 3. HiggsfieldProvider

- 호스트는 `api.higgsfield.ai` 하나(공식 SDK와 공식 앱 템플릿이 일치). 헤더 `Authorization: Key <키>`, `Content-Type: application/json`, `Accept-Encoding: identity`, 포트 없는 `Host`, 그리고 `Idempotency-Key`(장면 시도별 UUID; 공급사 지원 여부 NOT VERIFIED이므로 중복 방지는 여기에 의존하지 않음).
- 제출 `POST /{모델 경로}` 본문 `prompt`·`duration`(정수 초)·`aspect_ratio`·`resolution`. 상태 `GET /requests/{id}/status`, 취소 `POST /requests/{id}/cancel`. 결과 주소는 `video.url`(또는 `videos[0].url`).
- 키는 인쇄 가능한 ASCII 8~520자만 헤더에 넣습니다(CR/LF 주입 불가). 응답 본문은 1 MiB까지 읽고, 공급사 문장은 저장·표시하지 않습니다.

## 4. FakeVideoProvider (테스트·CI 전용)

`create_app(..., video_provider=FakeVideoProvider())` 또는 `tools/ci_fixture_server.py --fake-video-provider`로 주입할 때만 존재하며 설정 화면에서 고를 수 없고 모든 화면에 "테스트 전용 Fake 공급자"가 표시됩니다. ffmpeg `testsrc2`로 540x960 재생 가능한 클립을 만들고, 프롬프트 표지 `[fake:auth|credits|input|rate|ambiguous|unavailable|nsfw|fail|slow|bad-clip]`로 실패를 재현합니다. 외부 호출은 없습니다.

## 5. 데이터 모델 (migration `0010`·`0011`, 추가 전용)

| 표·열 | 내용 |
| --- | --- |
| `video_ai_models` | 공급사·모델 경로(유일)·표시 이름·초당 단가·허용 길이·해상도·공식 문서 확인 시각 |
| `ai_video_plans` | 대본·대본 수정 번호·길이·공급사·상태·수정 번호(revision)·통화·확인/검토/승인 시각·합성 작업 번호 |
| `ai_video_scenes` | 계획별 장면(위치 유일): 시간·내레이션·자막·소재(card/local/generated)·로컬 이미지·프롬프트·모델·클립 초·예상 비용·상태·시도·요청 번호·제출 키·오류 코드·고정 메시지·클립 이름·클립 정보(형식·코덱·크기·길이·SHA-256)·검토 여부 |
| `video_ai_usage` | 장면 시도별 예약 1행(장면+시도 유일): 공급사·모델·초·예상 비용·통화·상태·요청 번호, `0011`에서 해상도와 확인 당시 승인 표지(`approval` = 그때의 `video_ai_approved_at`) 추가 |
| `video_projects.ai_plan_id`, `video_scenes.clip_name`·`ai_generated` | 최종 합성 영상과 계획·클립의 연결 |

되돌리기(downgrade)는 0008/0009처럼 열을 제자리에서 지우고 새 표를 삭제합니다. `0011`은 이미 게시된 `0010`을 고치지 않고 예약 열을 더하는 별도 revision이며, 개발 중 빌드가 `0010`에 `resolution`을 이미 만든 폴더도 올릴 수 있도록 없는 열만 추가합니다.

## 6. 장면 상태 기계

```text
planned ──(유료 생성 확인: 예약 1행)──► waiting ──(작업자, 비교 후 갱신)──► submitting
submitting ──► queued / in_progress ──► downloading ──► ready ──(검토)──► 합성
     │               │                       │
     │               ├─► failed / nsfw / canceled (공급사 결과, 계산)
     │               └─► failed(video_ai_request_missing)
     ├─► unknown (보낸 뒤 결과 불명 · 재시작 시 submitting) ──(사용자 확정)──► failed → 같은 제출 키로 다시 보낼 수 있음
     └─► failed (보내지 않음: 키·경로·연결 전 오류)
downloading 실패·제한시간 ──► failed(다운로드·검증·공간·제한시간) ──(결과 다시 받기, 최대 3번, 추가 요청 없음)──► in_progress
waiting ──(설정·대본·모델·프롬프트 조건 불충족)──► canceled(보내지 않음)
```

사용량 상태는 `reserved → submitted → completed / failed / unknown / canceled`이며 `not_sent`만 한도 계산에서 빠집니다.

## 7. 비용·승인·한도

- 설정 키 `video_ai_*`(공급사·호스트·승인 시각·월 한도·작업별 한도·통화·동시 생성 수 1~4·장면별 제한시간 5~120분·상태 확인 간격 5~60초). 승인은 두 한도가 0보다 커야 저장되고, 승인 시각은 다시 저장해도 유지됩니다. 이번 달 기록이 있으면 통화를 바꿀 수 없습니다.
- 장면 클립 초 = 장면 길이 이상인 가장 짧은 허용 길이(없으면 가장 긴 길이를 반복). 예상 비용 = 클립 초 × 초당 단가.
- 예상 비용은 화면을 열 때와 유료 생성 확인 때(쓰기 잠금 안) 모두 **현재 확인된 모델 단가·허용 길이로 다시 계산**하고, 확인 때 계산한 초·비용·해상도를 장면과 예약 행에 씁니다. 통화를 바꾸면 모든 모델의 확인이 해제됩니다. 예상 화면은 한도를 넘는 묶음이면 그 이유를 표시하고 요청 버튼을 막습니다. 내려받기·검증·제한시간으로 닫혔지만 같은 요청의 결과를 다시 받을 수 있는 장면은 새 묶음에 들어가지 않고 비용 화면에 안내만 표시합니다(다른 장면의 확인은 막지 않음, 다시 생성하려면 프롬프트를 바꿉니다). 검토한 클립 파일이 사라지거나 바뀌면 합성 승인 때 그 장면을 '결과 다시 받기' 가능 상태로 바꿉니다.
- 유료 생성 확인은 체크 + 화면에 보인 합계와 서버 재계산 합계 일치 + 체험 대본 아님 + 프롬프트에 키 없음 + `계획 누적 + 이번 합계 ≤ 작업별 한도`·`이번 달 + 이번 합계 ≤ 월 한도`를 한 트랜잭션(`BEGIN IMMEDIATE`)에서 확인하고, 장면마다 예약 행을 씁니다.
- OpenAI 토큰 한도(`ai_usage`)와 표·설정·키가 모두 분리되어 서로를 잠식하지 않습니다.

## 8. 작업자·잠금·복구

- 확인 직후 작업자 스레드가 시작되고 일이 없으면 스스로 끝납니다. 데이터 폴더의 `ai-video.lock`으로 프로세스 하나만 작업합니다.
- 작업 주기마다 **대기 중인 모든 장면**을 쓰기 잠금 아래에서 검사합니다(동시 생성 칸이 차 있어도 검사는 하고, 보내기만 미룹니다). 조건: 공급사·승인·한도·키, 예약 행의 승인 표지가 **현재 승인과 같을 것**(승인을 해제했다 다시 저장하면 이전 확인은 무효이며, 같은 계획에서 나중에 확인한 다른 장면이 이전 예약을 대신 통과시키지 않습니다. 시계 비교는 쓰지 않습니다), 예약이 이번 달에 만들어졌을 것(지난달 확인은 이번 달 한도에 들어가지 않았으므로 다시 확인), 계획 누적이 작업별 한도 이하, 대본 수정 번호·체험 여부·프롬프트 정책, 예약 행의 모델·초·비용·해상도 = 현재 계산. 통과한 장면만 `submitting`으로 바꾼 뒤 **예약 행의 모델·초·해상도**로 보냅니다. 보내는 시점의 월 한도 검사는 이미 예약된 금액을 포함해 한도를 넘을 때만 멈춥니다. 동시 생성 수를 넘기지 않습니다. 생성 중·결과 불명 장면은 수정할 수 없습니다.
- 429·408은 공급사가 요청을 받지 않았다는 응답이므로 같은 시도·같은 키로 최대 3번 다시 대기열에 넣습니다. 그 밖에 보낸 요청은 다시 보내지 않습니다. 제출 직후 기록 쓰기가 실패하면 짧게 재시도하고, 그래도 실패하면 요청 번호를 메모리에 두었다가 다음 주기에 기록합니다.
- 상태를 먼저 확인하고, 공급사가 아직 대기·생성 중이라고 답했는데 제한시간이 지났으면 취소를 시도한 뒤 실패(`video_ai_timeout`)로 닫습니다. 완료라고 답한 결과는 제한시간과 무관하게 받습니다. 상태 확인 자체가 실패하면 제한시간의 2배까지 다시 확인한 뒤 닫습니다. 취소가 받아들여지면 `canceled`로 닫고(받을 결과 없음), 거절·실패하면 생성이 끝날 수 있으므로 `failed`로 닫아 '결과 다시 받기'(추가 요청 없음)를 허용합니다. 공급사가 '사용 안 함'이면 진행 중 장면에 상태 확인을 멈췄다는 고정 문장을 표시하고, 다시 켜면 이어서 확인합니다. 결과 불명 요청을 실패로 확정한 뒤 다시 보낼 때는 모델·초·해상도가 이전 시도와 같을 때만 같은 Idempotency-Key를 씁니다. 프로그램 종료 시 메모리에 남은 요청 번호를 한 번 더 기록합니다.
- 재시작: `submitting → unknown`(다시 보내지 않음), `downloading → in_progress`(상태 재확인), 참조되지 않는 클립 파일 삭제.

## 9. 오인 방지

1. 프롬프트 정책: NFKC·대소문자·띄어쓰기·하이픈 무시 비교로 실제 현장·기록 영상, 촬영 장비, 실존 인물·딥페이크 표현을 거부하고, 제어·서식 문자와 URL·이메일을 거부합니다(600자).
2. 모든 프롬프트 끝에 붙는 문장: `Stylized abstract illustration for a news briefing background. Not photorealistic, not documentary or news footage, no real people, no faces, no real places or landmarks, no logos, no on-screen text.`
3. 최종 영상의 모든 AI 장면에 끌 수 없는 노란 표시 **AI 생성 장면 · 실제 현장 영상 아님**.
4. 장면별 관계 검토와 표시 확인 문장을 저장해야 최종 합성을 승인할 수 있습니다(검토와 합성 승인은 별도 단계).
5. 게시 준비에서 AI 장면이 있는 영상은 AI 표시 `disclose`만 통과합니다. 영상 작업·보관함 화면에도 "AI 생성 장면 포함"이 표시됩니다.

## 10. 다운로드와 클립 검증

HTTPS만, 기본 포트, 사용자 정보·조각 없음, 모든 DNS 응답이 공인 주소, 리디렉션 3번까지 매번 재검사, `identity` 인코딩, 영상·octet-stream 형식, 200 MiB·시간 제한·취소, 배타 생성 후 fsync, 실패 시 삭제. 공급사 키는 다운로드 호스트로 보내지 않습니다. 서명 주소의 쿼리는 길이·문자만 검사하며 주소는 저장·기록하지 않습니다. 받은 파일은 `ffprobe -protocol_whitelist file -format_whitelist mov,mp4,m4a,3gp,3g2,mj2,matroska,webm`로 형식(mov/mp4·matroska/webm)·코덱(h264/hevc/vp8/vp9/av1/mpeg4)·크기 128~4096·길이를 확인한 뒤 `data/ai-clips/clip-<32hex>.mp4`로 둡니다.

## 11. FFmpeg 합성

- 클립 장면: `ffmpeg -protocol_whitelist file -f <ffprobe가 정한 형식> -stream_loop -1 -i clip -loop 1 -framerate 30 -i overlay.png -i 내레이션.wav -filter_complex <상수 필터> -map [v] -map 2:a -t <장면 초>` + 카드 장면과 같은 인코더 인수. 사용자 문자열은 FFmpeg 인수에 들어가지 않습니다. 클립 소리는 버립니다.
- 상수 필터는 9:16으로 채우고 잘라 30fps로 맞추며 `setsar=0`·`setparams=...unknown`으로 화면비·색 표시를 비워 카드 장면과 **H.264 헤더가 바이트 단위로 같게** 만듭니다(`-c copy` 이어 붙이기 안전).
- 문구 레이어 `overlay()`는 카드와 같은 글꼴·줄바꿈·자막 안전 영역 규칙을 씁니다.
- 승인 시와 렌더 직전에 클립 SHA-256을 검토 당시 값과 비교하고, 프로젝트 스냅숏 `ai_clips`와 작업 메타데이터에 남깁니다. 클립 문제는 렌더 오류 종류 `clip`("AI 생성 장면 파일")으로 안내합니다.

## 12. GUI

| 경로 | 내용 |
| --- | --- |
| `GET /video/ai` | 두 제작 모드, 준비 상태와 이유, 새 계획, 최근 계획 |
| `GET /video/ai/plans/{id}` | 스토리보드(장면별 소재·로컬 이미지·프롬프트·모델), 예상 비용 확인, 장면 취소·결과 불명 확정·결과 다시 받기, 관계 검토, 최종 합성(실패 시 다시 합성), 생성 기록 |
| `POST …/scenes`·`/confirm`·`/scenes/{n}/cancel`·`/resolve`·`/refetch`·`/review`·`/approve` | 모두 CSRF·수정 번호 확인, 거부 시 고정 문장(JSON `detail`) |
| `GET /api/video/ai/plans/{id}` | 상태 폴링(3초) |
| `GET /video/ai/scenes/{id}/clip` | 준비된 클립만 같은 출처로 재생 |
| `/video-ai-settings` (+ `/models`, `/key`, `/key/clear`) | 공급사·승인·한도·모델·키(별도 DPAPI 파일) |

주 메뉴 6개는 그대로이며 `/video`와 간단 설정에서 링크합니다. 모든 시각은 KST로 표시합니다.

## 13. 5C.1 설계 초안과 달라진 점

| 초안 | 구현 | 이유 |
| --- | --- | --- |
| 자동 제작 안의 `video_mode`·비용 확인 체크 | 영상 스튜디오의 독립 계획 흐름 | 장면별 선택과 두 번의 명시 승인을 분리하기 위해 |
| 코드 고정 모델 허용 목록·자동 장면 선정 | 사용자가 확인·입력한 모델 목록, 장면별 선택 | 공급사 사실을 확인하지 못함 |
| 고정 영어 프롬프트 템플릿 | 사용자 프롬프트 + 거부 규칙 + 고정 스타일 문장 | 장면 맞춤과 오인 방지를 함께 |
| 초 단위 월 한도, 표시용 단가 | 통화 단위 작업별·월 한도, 단가로 예상 | 지시의 "모델별 예상 비용·작업별·월 한도" |
| 표시 "AI 생성 장면 · 실제 영상 아님" | "AI 생성 장면 · 실제 현장 영상 아님" | 뉴스 현장 오인 방지를 더 분명히 |
| 리디렉션 거부·64 MiB·출력 호스트 허용 목록 | 리디렉션 3번 재검사·200 MiB·공인 주소 검사 | 결과 호스트를 확인하지 못해 허용 목록을 만들 수 없음 |
| 실패 시 카드 자동 대체 | 사용자가 카드·로컬 이미지로 바꾸고 합성 | 유료 결과의 처리를 사람이 결정 |

## 14. 보안 요약

키는 DPAPI 파일 `video-ai-key.dpapi` 또는 `NEWSFLOW_VIDEO_AI_KEY`에만 있고 DB·로그·화면·프롬프트에 남지 않습니다(프롬프트에 키·키 일부가 있으면 저장 거부). 공급사 응답 문장·결과 주소는 저장하지 않습니다. FFmpeg·PowerShell 자식 프로세스 환경에서 `*_KEY` 변수를 지웁니다. GUI는 기존 CSRF·Origin·CSP 미들웨어를 그대로 거칩니다.

## 15. 테스트와 CI

`tests/test_ai_video_provider.py`·`test_ai_video_settings.py`·`test_ai_video_service.py`·`test_ai_video_compose.py`·`test_ai_video_gui.py`(소켓 차단·Fake 공급자·실제 ffmpeg 합성), `tests/test_publishing.py`의 AI 표시 강제, `tools/ci_ai_video_validation.py`(실제 서버·브라우저·재시작·최종 MP4), `.github/workflows/newsflow-phase5d-windows.yml`.

## 16. NOT VERIFIED

실제 Higgsfield 요청·응답, 모델별 허용 길이·해상도, 가격·청구·환불, 요청 한도, 결과 보관 기간·형식, `Idempotency-Key` 지원, 이용약관, 생성 영상 품질. 실제 호출은 사용자가 공식 문서를 확인하고 설정 화면에서 승인·한도·모델·키를 저장한 뒤 사용자 PC에서만 일어납니다.
