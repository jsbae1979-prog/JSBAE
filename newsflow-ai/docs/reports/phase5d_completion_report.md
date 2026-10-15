# NewsFlow AI — Phase 5D 선택형 AI 영상 공급사(Higgsfield) 완료 보고서

작성: 2026-10-16 07:35 (한국 시간 KST, UTC+9). 운영 대상 Windows 11 / Python 3.12. 개발 담당: Claude Code. 기준 브랜치 `feat/newsflow-phase5c1` @ `830117894464f29ea572f6bdd2d67a02063fc96a`, 작업 브랜치 `feat/newsflow-phase5d`, Draft PR [jsbae1979-prog/JSBAE#12](https://github.com/jsbae1979-prog/JSBAE/pull/12).

판정 표기: **PASS** / **FAIL** / **SKIPPED** / **NOT VERIFIED** / **CONFLICTING**. 자동 테스트·Fake 공급자 검증의 성공을 실제 Higgsfield 동작이나 생성 품질의 검증으로 보고하지 않습니다. **실제 Higgsfield API·MCP 호출, 계정·키 발급, 유료 생성은 0건**입니다(사용자 승인 전 금지).

## 1. 요약

| 요구 | 판정 | 근거와 한계 |
| --- | --- | --- |
| 기본 모드: 외부 영상 API 없이 기존 로컬 FFmpeg 제작 | PASS | AI 영상 설정 기본값 '사용 안 함'. 기존 Video Studio·자동 제작은 그대로(Cloud·Windows 전체 회귀, 브라우저 검증 `default_off_and_basic_mode`) |
| AI 고품질 모드: Higgsfield 생성 후 FFmpeg 최종 합성 | PASS (Fake 공급자) · 실제 Higgsfield **NOT VERIFIED** | 장면별로 고른 AI 장면만 공급사에 보내고, 받은 클립을 같은 FFmpeg 경로(`VideoCoordinator.start_ai` → `_start/_run`)로 합성. 테스트·CI는 외부 호출이 없는 Fake 공급자만 사용 |
| 사전 분석 보고서(기존/신규, 중복 구현 금지) | PASS | [phase5d_existing_analysis.md](phase5d_existing_analysis.md): 기존 13개 영역 재사용, 신규 10개 영역 |
| Higgsfield 공식 문서 7개 항목 검증 | PASS (보고서) · 항목별 VERIFIED/CONFLICTING/NOT VERIFIED | [phase5d_higgsfield_api_verification.md](phase5d_higgsfield_api_verification.md). 문서 사이트는 세션 프록시가 막아 공식 SDK·공식 앱 템플릿 코드로 확인. 가격·보관 기간·요청 한도·Idempotency-Key·환불·약관은 NOT VERIFIED |
| 공급사 독립 Provider | PASS | `VideoProvider` 계약(submit·status·cancel·fetch), `HiggsfieldProvider`, 테스트 전용 `FakeVideoProvider`(주입만) |
| 스토리보드 확장(장면별 프롬프트·생성/로컬 선택·상태·실패 이유·관계 검토·승인 후 합성) | PASS | 계획 화면 §5. 실제 현장처럼 오인하게 하는 표현 거부·스타일 문장·끌 수 없는 "AI 생성 장면 · 실제 현장 영상 아님" 표시 |
| 비용·보안(기본 꺼짐, 승인 전 유료 호출 없음, 모델별 예상, 작업별·월 한도, 키 보호, 로그 비밀 없음, 다운로드 주소 검사, 실패 시 기존 경로 보존, OpenAI 한도와 분리) | PASS | §6 |
| Fake/Mock 우선 검증, 실제 유료 호출 금지 | PASS | 실제 호출 0건(§14) |
| 기존 회귀·게이트·비용 한도·비동기·중복 방지·재시작 복구·결과 파일 검증·FFmpeg·Windows Actions·GUI 브라우저 | PASS | §7~§11 |
| 적대적 검토 | PASS | 13차까지(결함마다 독립 반박 검증), 확인된 결함 84건 수정·회귀 테스트, 마지막 확인 차수 0건(§12) |
| 공급사 실제 동작·가격·생성 품질·약관 | NOT VERIFIED | §13. 첫 실제 호출 전 사용자 확인 목록은 검증 보고서 §4 |

## 2. 변경 파일

기준 `8301178` 대비 최종 코드 `698508e`: 66개 파일 변경, 11264줄 추가, 78줄 삭제(보고서·증거 제외. 전체 목록: [changed-files.txt](phase5d_evidence/changed-files.txt)).

- 신규 패키지 `src/newsflow/video/ai/`: `contracts.py`, `higgsfield.py`, `fake.py`, `download.py`, `clips.py`, `policy.py`, `costs.py`, `settings.py`, `keys.py`, `service.py`
- DB: `migrations/versions/0010_ai_video.py`(게시본 그대로), `0011_ai_video_reservation.py`(추가 전용, 없는 열만 추가), `db/models.py`, `migrate_data` 0011 허용
- 영상: `video/engine.py`(`overlay()`·`clip_command()`·`CLIP_FILTER`), `video/service.py`(`start_ai`, 클립 해시·검사, 메타데이터)
- GUI: `gui/video_ai_routes.py`, 템플릿 `video_ai.html`·`video_ai_plan.html`·`video_ai_settings.html`, `video_ai.js`, 기존 템플릿의 AI 장면 표시·KST 표시
- 게시: `publishing/service.py`(AI 장면 영상은 `disclose`만 통과)
- 테스트: `test_ai_video_provider.py`·`test_ai_video_settings.py`·`test_ai_video_service.py`·`test_ai_video_compose.py`·`test_ai_video_gui.py`·`test_phase5d_implementation_doc.py`(835개), 기존 테스트는 마이그레이션 head 값·라벨 등 추가·갱신만(삭제·skip 없음)
- CI: `tools/ci_ai_video_validation.py`, `tools/ci_fixture_server.py --fake-video-provider`, `.github/workflows/newsflow-phase5d-windows.yml`
- 문서: 분석·API 검증·[구현 설계](../design/phase5d_ai_video_implementation.md)·[사용 안내](../user_guide_ai_video.md)·README·START_HERE·AGENTS.md·Windows 체크리스트 §12·이 보고서

## 3. 기존 기능 분석 (중복 구현 없음)

장면 자동 분할(대본 장면 목록), 타이밍(`VideoCoordinator.timings`·음성 맞춤), 자막·문구(`engine.card()` 규칙), 소재 적용(`assets_list`·`asset`·이용 권한), 렌더 파이프라인, 데이터 모델, 승인 구조, 키 저장(DPAPI), 네트워크 보안(SSRF·DNS 고정·TLS), GUI 보안(Origin·CSRF·CSP), 재시작 복구, 테스트·CI 픽스처를 그대로 재사용했습니다. 새로 만든 것은 공급사 계약·구현, 안전 다운로드·클립 저장소, 오인 방지 정책, 비용·설정·별도 키, 계획·작업자, DB 표, GUI, 클립 합성 인수, CI 도구입니다. AI 영상 비용은 OpenAI 토큰 한도(`ai_usage`)를 재사용하지 않고 별도 표 `video_ai_usage`와 별도 한도로 관리합니다. 자세한 표: [phase5d_existing_analysis.md](phase5d_existing_analysis.md) §1–§3.

## 4. Higgsfield 공식 문서 검증 (7개 항목)

`docs.higgsfield.ai` 등 문서 사이트는 세션 프록시(`CONNECT 403`)로 열지 못했고 우회하지 않았습니다. 대신 공식 Python SDK `higgsfield-client` 0.2.0(wheel sha256 `66a6310c…`), 공식 JS SDK `@higgsfield/client` 0.2.6, 공식 앱 템플릿 `higgsfield-ai/app-templates` 커밋 `1e15e22`를 읽었습니다.

| 항목 | 판정 | 이 앱의 선택 |
| --- | --- | --- |
| 1 접근·인증 | 기본 주소 `https://api.higgsfield.ai`, `Authorization: Key <키>` VERIFIED(공식 코드). 키 형식(단일 키 / `KEY_ID:KEY_SECRET`) CONFLICTING | 호스트 하나로 고정, 두 형식 모두 `[\x21-\x7E]{8,520}`로 검사, 별도 DPAPI 파일 |
| 2 영상 모델 | 경로형 모델 ID·요청 항목(`prompt`·`aspect_ratio`·`resolution`·`duration`)·9:16 VERIFIED(공식 코드). 모델별 서버 한도 NOT VERIFIED | 코드에 모델·가격을 넣지 않음. 사용자가 경로·허용 길이·단가를 입력하고 "공식 문서 확인" 체크해야 사용 |
| 3 요청·비동기 조회 | `POST /{model}`, `GET /requests/{id}/status`, 상태 6종 VERIFIED(공식 코드) | 폴링만(웹훅 미사용), 비교 후 갱신 상태 기계 |
| 4 다운로드·보관 | 결과 `video.url` VERIFIED. 보관 기간·CDN 호스트·형식 NOT VERIFIED | HTTPS만·사설 주소 거부·DNS 고정·리디렉션 재검사·200 MiB·ffprobe 검증, 주소 저장·기록 안 함 |
| 5 가격·크레딧 | NOT VERIFIED(검색 요약만) / 일부 CONFLICTING | 사용자가 입력한 초당 단가 × 초로 예상, 실패·정책 거부·결과 불명도 보수적으로 사용액에 포함 |
| 6 실패·제한시간·재시도·취소 | 취소(대기 중만, 202)·오류 본문 VERIFIED. 공식 SDK는 제출까지 자동 재시도(중복 청구 위험) VERIFIED. Idempotency-Key CONFLICTING·NOT VERIFIED | 제출은 재시도하지 않음(429·408만 같은 키로 최대 3번), 결과 불명은 자동 재전송 없음, 키는 보내되 의존하지 않음 |
| 7 상업 이용·콘텐츠 정책 | NOT VERIFIED(검색 요약만) | 사용자가 약관 직접 확인, 약관 요약보다 엄격한 오인 방지 규칙 |

## 5. 스토리보드 확장과 오인 방지

- 계획은 저장된 대본의 장면·시간·내레이션·자막을 그대로 복사합니다. 장면마다 소재를 `기본 카드`(기본값) / `로컬 이미지` / `AI 생성 영상(유료)`에서 고르고, AI 장면은 프롬프트(600자)와 확인된 모델을 고릅니다.
- 장면 상태: 계획 → 제출 대기 → 공급사 대기열 → 생성 중 → 내려받는 중 → 생성 완료, 또는 실패·정책 거부·취소·결과 불명. 실패 이유는 고정 한국어 문장(공급사 원문·주소·요청 번호·프롬프트를 저장하지 않음).
- 관계 검토(장면별 "추상적 연출 화면이며 실제 사건 현장·인물로 오인될 표현 없음" + 표시·자막·출처 확인 문장)와 최종 합성 승인은 별도 단계입니다. 승인 시와 렌더 직전에 검토한 클립의 SHA-256을 비교합니다.
- 오인 방지: 실제 현장·기록 영상·CCTV·실존 인물·딥페이크처럼 보이게 하는 표현, 제어·폭 0 문자, 주소·이메일 거부(띄어쓰기·하이픈 무시 비교). 모든 프롬프트에 영어 스타일 문장(추상 일러스트, 실사·뉴스 영상 아님, 실존 인물·얼굴·장소·로고·문자 없음)이 붙습니다. 최종 영상의 AI 장면에는 끌 수 없는 노란 표시가 들어가고, 영상 작업·보관함에 "AI 생성 장면 포함", 게시 준비는 `disclose`만 통과합니다.
- 받아 둔 유료 결과 보호: 바뀌지 않은 유료 장면은 다시 검사하지 않고(모델 확인이 해제돼도 합성 가능, 화면에 "(현재 사용 불가)"), 바꾸려면 `받아 둔 유료 AI 영상 버리기` 체크가 필요합니다. 대본을 고쳐도 장면 수·시간이 같으면 `바뀐 대본 반영`으로 클립을 유지합니다.

## 6. 비용·보안

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 기본 비활성 | 공급사 '사용 안 함', 승인 없음, 한도 0 | PASS |
| 사용자 승인 전 유료 호출 금지 | 날짜가 있는 승인 + 0보다 큰 작업별·월 한도 + 확인된 모델·단가 + 키 + 장면별 예상 비용 확인 체크 + 화면 합계와 서버 재계산 합계 일치. 예약 행마다 확인 당시 승인 표지를 저장하고 보내는 시점에 현재 승인과 같을 때만 전송 | PASS |
| 모델별 예상 비용 | 현재 확인된 단가·허용 길이로 화면과 확인 시(쓰기 잠금 안) 모두 재계산, 예약 행에 모델·초·비용·해상도 고정 | PASS |
| 작업별·월 한도 | `계획 누적 + 이번 합계 ≤ 작업별 한도`, `이번 달 + 이번 합계 ≤ 월 한도`를 `BEGIN IMMEDIATE` 안에서 확인, 보내는 시점에 다시 확인. 지난달 확인·다른 통화 사용액이 있는 계획은 보내지 않음 | PASS |
| OpenAI 토큰 한도와 분리 | 별도 표 `video_ai_usage`, 별도 설정 키 `video_ai_*`, 별도 키 파일 | PASS |
| 키 보호 | 현재 사용자 DPAPI 파일 `video-ai-key.dpapi`(또는 환경변수), DB·화면·로그·증거에 없음, 프롬프트에 키(또는 키 ID·비밀값)가 들어가면 저장 거부 | PASS |
| 로그 비밀 없음 | 고정 오류 문장만 저장, 공급사 본문·결과 주소·요청 본문 미기록 | PASS |
| 다운로드 주소 검사 | HTTPS, 공인 주소만, DNS 고정, 리디렉션 3회 재검사, 쿼리 길이·문자 검사, 200 MiB·시간 제한, ffprobe 형식·코덱·크기·길이 검사(형식 허용 목록) | PASS |
| 실패 시 기존 경로 보존 | AI 장면 실패 시 카드·로컬 이미지로 바꿔 기본 경로로 계속 제작, 합성 실패 시 받은 클립 유지·재합성(추가 비용 없음) | PASS |
| 중복 청구 방지 | 제출 재시도 없음, 작업자 파일 잠금, 결과 불명은 자동 재전송 없음(사용자가 대시보드 확인 후 실패 확정), 같은 요청 재전송만 같은 Idempotency-Key | PASS (Fake) · 공급사 키 지원 NOT VERIFIED |

## 7. 비동기·중복·재시작 복구·결과 파일

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| 비동기 생성(대기열·진행·완료·내려받기·검증) | PASS | 서비스 테스트, 브라우저 검증 `async_generation` |
| 중복 확인·중복 전송 거부 | PASS | 같은 수정 번호 재확인 409/422, 예약 1행(브라우저 검증 `budget_and_duplicate`) |
| 재시작 복구 | PASS | 제출 중 → 결과 불명(재전송 없음), 내려받는 중 → 상태 재확인, 브라우저 검증에서 서버 재시작 후 요청 번호 유지·추가 제출 0 (`restart_recovery`) |
| 결과 파일 검증 | PASS | ffprobe 허용 형식·코덱·해상도·길이, SHA-256 기록·승인 시·렌더 직전 비교, 없거나 바뀐 파일은 '결과 다시 받기'(추가 요청 없음), 읽을 수 없는 파일은 상태 유지 + 다시 받기 제공 |
| 결과 다시 받기 | PASS | 최대 3번(실패한 받기만 셈, 디스크 부족 제외). 다시 받을 수 있는 동안 새 유료 묶음에서 제외하고, 3번 실패하거나 공급사에 결과가 없으면 비용 화면에 따로 안내한 뒤 새 생성 대상 |

## 8. FFmpeg 합성

`clip_command`가 클립을 9:16으로 잘라 장면 길이만큼 반복하고, 카드와 같은 글꼴·안전 영역의 투명 문구 레이어와 노란 AI 표시를 얹습니다. 클립 소리는 버리고 내레이션만 씁니다. `CLIP_FILTER`가 화면비·색 표시를 비워 카드 장면과 H.264 헤더를 바이트 단위로 맞추므로 기존 `-c copy` 이어 붙이기가 그대로 동작합니다. Cloud 브라우저 검증 최종 MP4: 1080×1920 H.264/AAC 30.02초, AI 장면 프레임에만 표시, 카드 장면에는 없음(`final_mp4`). 영상 품질은 사람이 봐야 하는 항목입니다(NOT VERIFIED).

## 9. Cloud 전체 테스트와 도구

최종 코드 `698508e`에서 `python -m pytest -q` (Python 3.12.3, Linux, `NEWSFLOW_FONT_PATH`=핀 고정 Noto Sans KR): **2200 passed / 7 skipped / 0 failed** ([cloud-pytest.txt](phase5d_evidence/cloud-pytest.txt), [cloud-pytest.xml](phase5d_evidence/cloud-pytest.xml)). `ruff check .` 통과. skipped 7 = opt-in live RSS·live AI 2 + Windows 전용 DPAPI·OAuth 5(기존과 같음). 기준(5C.1) 1363 passed / 7 skipped(1370개) → 2207개, Phase 5D 테스트 837개 추가(신규 6개 파일 835개 + 기존 파일 추가 2개), 기존 테스트 삭제·skip 없음.

| 도구 | 판정 | 요약 |
| --- | --- | --- |
| `ci_ai_video_validation --mode cloud` | PASS | 기본 꺼짐 → 승인·한도 없이 승인 거부 → 오인 프롬프트 거부 → 작업별 한도 초과 표시·버튼 비활성·서버 422·예약 0 → 유료 확인 1회 → Fake 생성·다운로드·검증 → 유료 클립 버리기 확인(409) → 재시작 후 재전송 없음 → 관계 검토 → FFmpeg 합성 → 보관함 표시. 보안: 위조 Origin 403, CSP self, DB에 키 없음, 브라우저 외부 요청 0. Higgsfield 호출 0 ([ai-video-validation.json](phase5d_evidence/cloud/ai-video-validation.json), 스크린샷 §10) |
| `ci_docs_link_check` | PASS | 189개, 깨진 링크 0 ([docs-links.json](phase5d_evidence/cloud/docs-links.json)) |
| 브라우저 MP4 재생 | NOT VERIFIED (Cloud) | Cloud Chromium에 H.264 디코더 없음. Windows 실행 15의 Google Chrome에서 클립 미리보기 재생 PASS(§11) |

## 10. GUI 브라우저 검증 (스크린샷)

Cloud Playwright Chromium, Fake 공급자, 데이터는 합성 뉴스입니다.

| 화면 | 파일 |
| --- | --- |
| AI 고품질 제작 시작(기본 꺼짐, 두 제작 모드) | [ai-home-default-off.png](phase5d_evidence/cloud/ai-home-default-off.png) |
| AI 영상 설정(승인·한도·모델·키, NOT VERIFIED 안내) | [ai-settings.png](phase5d_evidence/cloud/ai-settings.png) |
| 스토리보드(장면별 소재·프롬프트·모델) | [ai-plan-storyboard.png](phase5d_evidence/cloud/ai-plan-storyboard.png) |
| 예상 비용 확인(작업별 한도 표시) | [ai-plan-cost.png](phase5d_evidence/cloud/ai-plan-cost.png) |
| 생성 완료·클립 미리보기·버리기 체크 | [ai-plan-ready.png](phase5d_evidence/cloud/ai-plan-ready.png) |
| 관계 검토 저장 | [ai-plan-reviewed.png](phase5d_evidence/cloud/ai-plan-reviewed.png) |
| 영상 작업 화면(장면별 소재, AI 안내) | [ai-job-page.png](phase5d_evidence/cloud/ai-job-page.png) |
| 제작 영상 보관함("AI 생성 장면 포함") | [ai-library.png](phase5d_evidence/cloud/ai-library.png) |
| 최종 MP4 프레임(AI 장면 표시 / 카드 장면 표시 없음) | [ai-final-frame-ai-scene.png](phase5d_evidence/cloud/ai-final-frame-ai-scene.png), [ai-final-frame-card-scene.png](phase5d_evidence/cloud/ai-final-frame-card-scene.png) |

## 11. Windows Actions

워크플로 `newsflow-phase5d-windows.yml`(5C.1 단계 전체 + "Actual AI high-quality mode with the offline Fake provider, restart recovery and labelled MP4"). **최종 실행 15 [38814293774](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38814293774)** (커밋 `698508e`, windows-latest Windows Server 2025, Python 3.12.10, Google Chrome, 실제 FFmpeg, 핀 고정 Noto Sans KR, 2026-10-16 07:02~07:26 KST): **success**. 증거: [windows-actions-evidence.json](phase5d_evidence/windows/windows-actions-evidence.json) (check annotation 41건, FAIL 0).

| 단계 | 판정 | 요약 |
| --- | --- | --- |
| `pytest -q -rs` | PASS | **2204 passed / 3 skipped / 0 failed** (2207개). skipped = Windows에는 실제 DPAPI가 있어 건너뛰는 Fake 암호 테스트 1, opt-in live AI 1, opt-in live RSS 1 |
| **AI 고품질 모드(Fake 공급자)** `ci_ai_video_validation --mode windows` | PASS | 기본 꺼짐·설정 게이트·프롬프트 정책·작업별 한도 초과 거부(422, 예약 0)·중복 거부·비동기 생성·**클립 미리보기 재생 PASS(Chrome, 재생 시간 진행 확인)**·유료 클립 버리기 확인(409)·재시작 후 재전송 없음·보안(위조 Origin 403, CSP, DB에 키 없음, 외부 요청 0)·최종 MP4 PASS. Higgsfield 호출 0. 공급사 동작·생성 품질 NOT VERIFIED |
| 5A·5B·5C·5C.1 기존 단계 | PASS (NOT VERIFIED 항목 명시) | 짧은 MP4·로컬 TTS, DPAPI 합성 vault·production vault, 실제 BAT·OAuth 차단(OFFLINE/BLOCKED, 실제 OAuth 호출 0), Easy UI(easy/guided-30s 재생), 초기 설정(setup-30/45/60s), 실제 콘텐츠 흐름(real-30/45/60s 재생, 외부 AI 0) |
| run.bat 실서버 RSS 연결 테스트(조선일보) | PASS | 기사 100 (네트워크 의존) |
| 공개 RSS 피드 검토(실행을 실패시키지 않는 단계) | PASS | 22개 중 17개 시도 · PASS 14 · BLOCKED 3(robots, 예상대로) · NOT VERIFIED 5(비활성) · FAIL 0. 같은 단계가 실행 13에서는 FAIL 2(nasa-news·un-news 수집 실패)였으며 외부 피드 응답에 따라 달라짐(Phase 5D는 RSS·수집 코드를 바꾸지 않음) |
| 한국어 음성 프로브 | NOT VERIFIED | 러너에 한국어 SAPI 음성 0개(en-US David·Zira만) |
| 문서 링크 검사 | PASS | 189개, 깨진 링크 0 |
| 토큰 0 OpenAI 연결 확인 | SKIPPED | 수동 dispatch·secret 없음 |

실행 이력(모두 2026-10-16 KST, 실행 1~15):

| 실행 | 커밋 | 결과 | 내용 |
| --- | --- | --- | --- |
| 1 [38760558728](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38760558728) | `ba24a97` | success | 최초 구현·CI·문서 |
| 2 [38768625382](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38768625382) | `8c6b29b` | success | 2차 검토 수정 |
| 3 [38774652319](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38774652319) | `65a470c` | success | 3차 검토 수정 |
| 4 [38778046231](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38778046231) | `a61e947` | success | 4차 검토 수정(0011 추가) |
| 5 [38781201550](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38781201550) | `08123d0` | success | 5차 검토 수정 |
| 6 [38787135021](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38787135021) | `8a91919` | success | 6차 검토 수정 |
| 7 [38791810526](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38791810526) | `9b18b5e` | **FAIL** | 2187 passed / 1 failed: 새 테스트 `test_a_directory_at_the_clip_path_counts_as_a_lost_clip` — Windows는 폴더를 열 때 `PermissionError`를 냄. 8차 검토도 같은 결함을 찾음 |
| 8 [38794073139](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38794073139) | `b626faa` | cancelled | 사용자 계정의 다른 Claude 세션("PR #12 CI 통과시키기")이 같은 한 줄 수정을 먼저 올림. 이 세션의 8차 수정과 병합 커밋으로 합치며(강제 푸시 없음) 동시 실행 설정으로 취소 |
| 9 [38796112771](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38796112771) | `a503b11` | success | 8차 수정 + 병합 |
| 10 [38800746368](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38800746368) | `1c339c4` | success | 9차 |
| 11 [38803072809](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38803072809) | `30d9cd6` | cancelled | 다음 푸시로 동시 실행 취소 |
| 12 [38806059510](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38806059510) | `c18b075` | success | 11차 |
| 13 [38808765856](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38808765856) | `9a1903e` | success | 12차 |
| 14 [38813139059](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38813139059) | `8ff00d0` | cancelled | 13차, 다음 보정 푸시로 동시 실행 취소 |
| 15 [38814293774](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38814293774) | `698508e` | **success** | 최종(13차 보정). 위 표 |

아티팩트 ZIP과 job 로그 다운로드 주소는 이전 단계와 같이 Cloud 프록시가 Azure blob 호스트를 거부(CONNECT 403)해 내려받지 못했고, GitHub 커넥터로 읽은 job 로그의 check annotation을 증거로 옮겼습니다([github-access.json](phase5d_evidence/github-access.json)).

## 12. 적대적 검토와 수정

분석 단계 결함 17건과 적대적 검토 2~12차에서 확인된 결함 67건, 모두 84건을 고쳤고 각 결함에 회귀 테스트가 있습니다. 매 차수마다 찾는 에이전트와 별도로, 결함 하나마다 독립 검증자가 코드와 임시 재현 테스트로 반박을 시도했고 반박되지 않은 것만 고쳤습니다(반박된 항목과 이유는 각 절에 기록). 11·12차는 모든 장면 상태를 실제 계획 화면(TestClient)으로 띄워 장면 문장·버튼·비용 화면·거부 문장·안내서를 대조했습니다. 차수별 목록: [분석 보고서 §4–§4.12](phase5d_existing_analysis.md).

| 차수 | 수정 | 대표 항목 |
| --- | --- | --- |
| 분석 | 17 | 0010 되돌리기, 합성 재시도, 결과 다시 받기, 프롬프트 정책 우회, H.264 헤더 일치, 클립 해시, `disclose` 강제 |
| 2차 | 11 | 예약·전송 게이트 강화 |
| 3차 | 11 | 모든 대기 장면 게이트, 요청 고정 |
| 4차 | 4 | 예약 행 승인 표지, 추가 전용 0011 |
| 5차 | 4 | 0011 재실행 안전, 월 경계, 사라진 클립 |
| 6차 | 8 | 읽을 수 없는 클립, 유료 결과 버리기 확인, 대본 반영, 통화 혼합 |
| 7차 | 8 | 결과 불명 재전송 키 유지, 오래된 화면 승인, 계속 읽을 수 없는 클립의 무료 다시 받기 |
| 8차 | 5 | 한 키는 한 요청 내용에만, 읽을 수 없는 클립 다시 받기 실패 시 원래 클립 복원, Windows 폴더 판정 |
| 9차 | 4 | 결과 없음(`result_gone`) 기록 유지, 화면에 있는 버튼만 안내 |
| 10차 | 2 | 다시 받기를 다 쓴 장면 안내 |
| 11차(전수 대조) | 6 | 섞인 거부 문장 통합, 결과 불명·비용 화면·합성 후 대본 변경 안내 |
| 12차(재대조) | 4 | 공급사 꺼짐, 상태 응답 오류, 남은 디스크 안내 |
| 13차(확인) | 0 (+경고 정리 2) | 12차 수정 확인과 상태 전수 재대조(2142개 조합)에서 기준(결과·비용 손실, 확인 우회, 키 오용, 진행 불가)에 해당하는 결함 없음. 자동 분석 경고 중 공급사 꺼짐 때 다시 받기 안내, 생성 중 장면의 취소 언급을 정리(경고 112→110건, 남은 것은 다른 진행 경로가 화면에 있는 문구 수준) |

결함이 아니라고 판정한 항목과 이유는 분석 보고서 §4.6~§4.9에 남겼습니다.

## 13. 미구현·미검증 (NOT VERIFIED)

- 실제 Higgsfield 서버 동작(인증 형식, 모델별 허용 길이·해상도, 상태 전이, 결과 주소 형식·보관 기간, 요청 한도, Idempotency-Key 지원, 오류 코드 의미), 가격·크레딧·환불, 이용 약관·상업 이용: NOT VERIFIED. 첫 실제 호출 전 사용자가 확인할 목록은 [검증 보고서 §4](phase5d_higgsfield_api_verification.md).
- 생성 영상의 품질·뉴스 내용과의 어울림: 사람이 봐야 함(NOT VERIFIED).
- 자동 제작(Autopilot)에는 AI 영상을 넣지 않았습니다(설계 결정: 장면별 사람 선택과 두 번의 명시적 승인 필요).
- `migrate_data`는 `ai-clips` 폴더와 `video-ai-key.dpapi`를 복사하지 않습니다(사용 안내에 명시). 오래된 클립 자동 삭제 정책 없음.
- 월 한도는 UTC 월 기준(KST 매월 1일 09:00 초기화)이며 화면에 안내합니다.
- 사용자 Windows 11 PC 수동 운영: NOT VERIFIED ([체크리스트 §12](../windows_user_verification_checklist.md)).

## 14. 실제 외부 호출과 비용

Higgsfield API·MCP 호출 0건, 키 발급 0건, 유료 생성 0건, 비용 0. 테스트·CI·브라우저 검증은 주입한 Fake 공급자만 썼고 브라우저 검증은 127.0.0.1 밖 요청 0건을 확인했습니다. OpenAI 호출도 0건입니다.

## 15. Draft PR·최종 SHA·Windows Actions URL

- Draft PR: [jsbae1979-prog/JSBAE#12](https://github.com/jsbae1979-prog/JSBAE/pull/12) (head `feat/newsflow-phase5d` → base `feat/newsflow-phase5c1`).
- 커밋: `3f13c93` Phase 5D optional AI video mode with a vendor-neutral provider · `91d0d29` Phase 5D AI video browser validation and Windows workflow · `ba24a97` Phase 5D analysis, Higgsfield API verification, design and guide · `8c6b29b` Phase 5D review fixes for cost, duplicate and recovery gates · `65a470c` Phase 5D review round 3 - gate every waiting scene, pin requests · `a61e947` Phase 5D review round 4 - per-reservation approval, migration 0011 · `08123d0` Phase 5D review round 5 - upgradable 0011, month boundary, lost clips · `8a91919` Phase 5D review round 6 - paid clip protection, script rebase, currency · `9b18b5e` Phase 5D review round 7 - resend key, safe approval, unreadable clips · `b626faa` treat a directory at the clip path as lost on Windows · `71c9425` Phase 5D review round 8 - one key per body, restore unreadable clips, Windows dirs · `a503b11` Merge remote-tracking branch 'origin/feat/newsflow-phase5d' into feat/newsflow-phase5d · `1c339c4` Phase 5D review round 9 - remember result_gone, say the real next step · `30d9cd6` Phase 5D review round 10 - no refetch guidance when none is left · `c18b075` Phase 5D review round 11 - every instruction names a step the page offers · `9a1903e` Phase 5D review round 12 - paused provider, unreadable status, stale disk guidance · `8ff00d0` Phase 5D review round 13 - refetch with provider off, no cancel hint while generating · `698508e` Phase 5D round 13 follow-up - provider-off refetch refusal names no button (코드 커밋 18개, 병합 커밋 1개 포함). 이후 증거·보고서 문서 커밋만 추가
- **최종 검증 SHA `698508e4e85d7f16caebabdeaecf50cb8469e490`**, Windows 실행 15 [38814293774](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38814293774) **success**. 이후 커밋은 이 보고서·증거만 추가하며 워크플로 `paths` 필터에 해당하지 않아 Windows 실행을 다시 시작하지 않습니다.
- 기존 PR #1~#11과 `main`은 변경하지 않았습니다. 강제 푸시·기존 커밋 재작성 없음.

## 16. 증거 목록

| 증거 | 위치 | 비고 |
| --- | --- | --- |
| Cloud pytest | [cloud-pytest.txt](phase5d_evidence/cloud-pytest.txt), [cloud-pytest.xml](phase5d_evidence/cloud-pytest.xml) | `698508e`, 2200 passed / 7 skipped / 0 failed |
| Cloud AI 영상 브라우저 검증 | [cloud/ai-video-validation.json](phase5d_evidence/cloud/ai-video-validation.json), 스크린샷 10장 | 최종 MP4는 크기 때문에 해시만 기록 |
| Cloud 문서 링크 검사 | [cloud/docs-links.json](phase5d_evidence/cloud/docs-links.json) | |
| Windows 최종 실행 annotation 사본 | [windows/windows-actions-evidence.json](phase5d_evidence/windows/windows-actions-evidence.json) | 실행 15, 41건 |
| Windows 아티팩트 접근 | [github-access.json](phase5d_evidence/github-access.json) | ZIP 다운로드 BLOCKED(프록시), annotation으로 대체 |
| 변경 파일 목록 | [changed-files.txt](phase5d_evidence/changed-files.txt) | `git diff --name-status 8301178..698508e` |
| manifest.sha256 | `phase5d_evidence/manifest.sha256` | 증거 파일 해시 |

## 17. 인계

추가 개발을 중단하고 ChatGPT의 ACCEPTED / CONDITIONAL / REJECTED 판정을 기다립니다. 실제 Higgsfield 유료 호출은 사용자 승인 전까지 하지 않습니다.
