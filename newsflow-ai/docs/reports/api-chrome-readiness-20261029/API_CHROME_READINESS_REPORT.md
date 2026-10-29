# 실제 API 준비 및 Chrome GUI 검증

**최종 판정: CONDITIONAL.** 읽기 전용 준비 확인은 완료했다. 현재 Chrome 제작 동선과 실제 유료 API 진입은 BLOCKED이며, 공급사별 현재 계정 권한은 NOT VERIFIED다. 실제 공급사 인증·생성·참조 PNG 업로드는 수행하지 않았다.

## 1. 기준과 실행 범위

- 브랜치: `codex/newsflow-bat-distribution-prep`
- 시작 HEAD: `ec9c609e923f36369c000dbe1e7bd3616eeaf039`
- 운영 설치/주소/PID: `C:/NewsFlowAI` / `127.0.0.1:18768` / `23240`
- 실제 설치본의 `app/product/newsflow` 코드를 읽었다. React 선택 로직은 기존 인수 소스·증거와 연결했다.
- 기존 BAT·React·FFmpeg·저장·재실행, 집중 CI59 PASS, 합성 브라우저42 PASS 및 이전 실제 GUI 증거를 재사용했다. 과거 결과를 새 실행 결과로 합산하지 않는다.
- 제품 코드·운영 설정·Guard·V3 변경, 앱 재실행, 패키징·전체 회귀·디자인 검증은 하지 않았다.

현재 운영 모드는 `restored-local-operation`, `readOnly=false`다. 로컬 저장은 가능하지만 `decryptCredentials=false`, `externalExecutionEnabled=false`, `automaticJobsEnabled=false`를 유지한다. 기존 승인 절차와 이 실행 경계를 우회하지 않았다.

## 2. Chrome 결과

사용자가 열어 둔 Chrome 운영 탭을 정상적으로 제어했다. `/`는 기존 요청 경계가 거절해 `Restored profile: read-only validation.`을 표시했다. 정식 React 경로 `/studio/dashboard`로 이동하자 **`Local Windows session authentication required.`**가 표시됐다. 첫 문구를 실제 프로필 전체가 읽기 전용이라는 뜻으로 해석하지 않는다.

Chrome 제어 자체는 가능하지만 현재 Chrome에 이 앱의 인증 세션이 없다. 실행 시 사용한 Edge 세션과는 별개다. LocalAccess는 실행 때 발급한 bootstrap을120초 이내 한 번만 받으며, 세션 유효기간은12시간이다. Edge 쿠키·토큰 복사, 소비되거나 만료된 bootstrap 재사용, 새 인증 우회 경로 추가는 하지 않았다. 운영 PID 유지 조건 때문에 재시작으로 새 인증을 발급하지도 않았다.

따라서 **이번 운영 Chrome의 로그인 후 제작실 클릭·모델 변경·생성 동선은 BLOCKED**다. 이전 GUI 성공을 이번 Chrome 성공으로 표시하지 않는다. 차단 화면은 로컬 `api-chrome-readiness-20261029/chrome-auth-required.png`에 보존했다. 사용자 탭은 정식 React 경로에 그대로 뒀다.

## 3. 공급사별 준비 상태

| 공급사 | 현재 확인한 등록·선택 상태 | 이번 계정 권한 검증 |
|---|---|---|
| Claude | 제품이 참조하는 DPAPI 암호문 있음. Sonnet4.6 선택. 과거 인증·검증 모델 기록 있음 | NOT VERIFIED |
| ElevenLabs | DPAPI 암호문 있음. Multilingual v2와 음성 선택값 있음 | 음성 권한·플랜·잔여량 미조회 |
| OpenAI | **제품이 참조하는 `ai-key.dpapi` 없음** | 키 등록 및 계정 권한 확인 필요 |
| Higgsfield | DPAPI 암호문 있음. 공급사 설정과 과거 승인값 있음 | 키 형식·잔액·모델 권한 미검증 |

키 파일의 존재만 확인했다. DPAPI 복호화·실제 키 형식 검사·공급사 모델 조회를 수행하지 않았다. OpenAI 판정은 해당 제품 저장 경로 기준이며, PC 어디에도 키가 없다는 뜻은 아니다. launcher는 NEWSFLOW_* 등 공급사 환경변수를 시작 시 지운다. 환경변수 비밀값을 별도로 열지 않았다.

개인 예산·실제 음성ID·설정 원문은 비공개 작업자료에만 두고 Git에는 올리지 않는다. 과거 Claude 인증 기록도 현재 사용 권한으로 승격하지 않는다.

## 4. 모델과 요청 계약

| 공급사 | 코드의 모델·요청 | 제한과 확인 범위 |
|---|---|---|
| Claude | `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, `claude-opus-4-6`. `POST /v1/messages`; model/system/messages/max_tokens/JSON schema | TOP3 대본2200토큰·60초, 캐릭터3000토큰·300초. 저장된 평가 모델과 선택 모델이 다르면 거절. 단일 POST·결과 불명 보존 |
| ElevenLabs | `eleven_multilingual_v2`, `eleven_flash_v2_5`, `eleven_v3`. 현재 v2. `POST /v1/text-to-speech/{voice_id}/with-timestamps?output_format=pcm_24000` | text/model_id/voice_settings.speed. PCM·정렬·길이·응답 사용량 검사. 음성ID 저장과 실제 사용 권한은 구분 |
| OpenAI | `gpt-image-2.5-flare-2026-09-08`, `gpt-image-2.5-sunburst-2026-09-08`. `POST /v1/images/generations` | 기본n1/1024x1280/medium/JPEG/opaque, timeout180초. 선택값 스냅샷 고정. legacy response_format을 전송하지 않음 |
| Higgsfield | `bytedance/seedance-2.0/reference-to-video` | PNG128~4096px/10MiB이하 → presigned 업로드 → image_urls. 코드4~10초/720p/9:16/무음. 견적·승인·request_id·상태 조회·다운로드·검토·FFmpeg |

공개 문서에서 기존 모델을 확인했으며 새 모델로 자동 교체하지 않았다. 공식 Seedance는4~15초와 추가 해상도를 허용하지만 코드 범위를 자동 확대하지 않았다. 실제 계정의 TPM/IPM·동시처리·잔여 크레딧은 모두 미검증이다. 로컬 한도값을 공급사 계정 한도라고 표시하지 않는다.

출처: [Claude 모델/모델API](https://platform.claude.com/docs/en/models/overview), [Claude 기존 모델 가격](https://platform.claude.com/docs/en/about-claude/pricing), [ElevenLabs 모델](https://elevenlabs.io/docs/overview/models), [timestamp TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps), [OpenAI 생성 규격](https://developers.openai.com/api/reference/resources/images/methods/generate), [Flare 모델](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare), [Seedance 규격](https://docs.higgsfield.ai/docs/models/seedance-2/reference-to-video), [Higgsfield 업로드](https://docs.higgsfield.ai/docs/concepts/file-uploads), [Higgsfield 계정별 한도](https://docs.higgsfield.ai/docs/concepts/rate-limits).

## 5. 제작실별 연결 결과

### 뉴스 쇼츠

완료된 **TOP3 분석#42 / claude_api / claude-sonnet-4-6 / rank1·2·3**이 DB에 있다. 새 유료 분석 없이 재사용할 대상이 확보돼 있다.

수동 React는 rank 기본값1이며 뉴스 카드 클릭으로 원하는 순위를 선택한다. 대본 요청은 analysis_id/rank/duration과 당시 공급사·모델을 검증한다. Revision·저장·중복 요청 보호, ElevenLabs 음성 어댑터와 FFmpeg 경로를 재사용한다. React 음성의 초기값은 `offline-silence`이므로 ElevenLabs가 자동 선택됐다고 주장하지 않는다.

**자동화 판정: PARTIAL.** UI의 기본 rank1과 '자동화가 저장된 TOP3의1위를 반드시 선택'은 다른 계약이다. 기존 Autopilot은 recommended_article_id 또는 후보 첫 건을 선택하는 경로가 있다. 분석#42의 rank1과 동일한 선택을 보장하는 운영 E2E는 미검증이다. 스케줄러는 비활성 상태로 유지했다.

### Instagram 피드 이미지

A는 프롬프트·모델·크기·품질 → 로컬 초안 → 견적·승인 → n1 이미지 어댑터 → 보관·검토 경로가 있다. 현재 OpenAI 키와 운영 외부 실행 조건이 충족되지 않았다.

B의 내부 계약은 TOP3의 기사·기존 대본 또는 요약·출처를 사용한다. 현재 React 뉴스 탭은 승인된 TOP3 전용이다. 과거 단일 뉴스 제작 모드 선택 UI를 다시 추가하지 않았다. TOP3 작업은 source3건과 순위별 status/history/generation_id를 보존하며 max_generations=3, 중복 사건·claim 차단을 갖는다. 부분 실패·unknown을 보존하고 일괄 자동 재전송하지 않는다. 이번 Chrome의 실제 B 선택·생성 버튼 검증은 BLOCKED다. 기존 Fake·CI 증거를 재사용한다.

### 캐릭터 쇼츠

참조 PNG·주제·캐릭터 설정 → Claude writer → 장면 견적·승인 → Seedance → 검토 → FFmpeg → 저장·미리보기 연결이 있다. Wan/Kling의 호환성을 추가로 검증했다고 표시하지 않는다.

**장면 수 판정: PARTIAL.** 현재 Storyboard와 지시문은 **3~5장면, 장면4~10초, 합계30초**를 허용한다. 사용자가 요청한 '3장면 고정'이 보장되는 코드라고 표시하지 않는다. 기존 3장면 Fake 성공은 해당 fixture의 성공이며 모든 실제 Claude 출력의 장면 수를 보증하지 않는다. 실제 생성 전에 정확히3장면을 적용할 정책·검토를 확정해야 한다. 이번에는 프롬프트·schema·제품 코드를 수정하지 않았다.

## 6. 예상 비용과 최소 호출 계획

다음은 **아직 승인·실행되지 않은 계획**이다. 2026-10-29 공개 표준가격을 대조했다. 현 계정 할인·음성 가산·세금·실제 토큰량은 미조회다. 추정치를 실제 청구액이나 강제 지출 상한으로 표시하지 않는다.

| 공급사 | 최소 유료 smoke 계획 | 비용 근거 |
|---|---|---|
| Claude | 기존#42의1위로 대본1회. 웹 검색·재분석0 | Sonnet4.6 입력$3/MTok·출력$15/MTok. 입력2000·출력2200토큰 가정이면$0.039. 캐릭터 스토리3000출력은 별도1회로 같은 입력 가정 시$0.051 |
| ElevenLabs | 권한이 확인된 음성으로100자 이하1회 | Multilingualv2 기본$0.08/1000자이면100자$0.008. Flash 기본$0.04/1000자. 플랜·음성 가산은 별도 확인 |
| OpenAI | 키·권한 확인 후 명시 모델·크기·low 품질 n1/POST1회 | Flare 표준 텍스트 입력$5/MTok, 이미지 입력$8/MTok, 이미지 출력$30/MTok. 이미지 토큰량을 몰라 장당 금액은 미확정 |
| Higgsfield | 권리 확인된 PNG1개로4초720p/9:16/무음 장면1회 | 동일 payload의 인증된 /estimate 결과 필요. 현재 금액 미확정. 전체3장면30초는 별도 전체 견적·승인 대상 |

[Claude 요금](https://platform.claude.com/docs/en/about-claude/pricing), [ElevenLabs 요금](https://elevenlabs.io/pricing/api), [OpenAI 요금](https://developers.openai.com/api/docs/pricing), [Higgsfield 견적·청구](https://docs.higgsfield.ai/docs/concepts/billing-and-retention).

OpenAI 공식 안내상 기존 GPT Image2 계산기는 GPT Image2.5의 토큰 소비를 예측하지 못한다. 다른 모델의 장당 가격으로 대체하지 않는다. Higgsfield 문서의 예시USD도 이 계정 견적으로 사용하지 않는다.

호출 수는 generation POST와 메타데이터·견적·업로드·status GET을 나누어 승인해야 한다. 특히 캐릭터 서비스가 여러 장면을 일괄 생성하는 경로에서는1회 smoke를 보장할 실행 범위를 먼저 확인해야 한다. 실패·timeout·결과 불명 상태에서 추가 유료 호출을 자동으로 실행하지 않는다.

### 다음 승인에 필요한 항목

1. **Chrome 정상 인증:** 새 bootstrap을 Chrome에서 정상 소비하는 실행 동선이 필요하다. 운영 Start/Stop이 필요하면 별도 승인을 받아야 한다. Windows 기본 브라우저를 임의 변경하거나 Edge 인증정보를 옮기지 않는다.
2. **키·계정 준비:** OpenAI 키 등록과 공급사별 비과금 모델·음성·구독·권한 조회 범위를 정한다. 현재 복호화·외부 실행 차단을 몰래 해제하지 않는다.
3. **공급사별 유료 승인:** 모델, 입력 범위, 외부로 전송할 소재, 호출 수, 지출 상한, 실패 중단 조건을 각각 명시한다. 전체 무제한 승인이 아니다.
4. **기능 차이:** 자동 TOP1 선택 계약과 캐릭터3장면 요구의 최소 보완 범위를 확정한다. 전체 TOP3 이미지3장·캐릭터3장면을 위1회 smoke로 검증 완료 처리하지 않는다.

이번에는 승인 항목만 정리했고 키 등록·정책 해제·유료 호출·운영 재시작을 수행하지 않았다.

## 7. 신규 결과와 운영 보존

**신규 읽기 전용 확인7 PASS /0 FAIL /0 ERROR**다. 운영 PID 유지,18768 연결,SQLite integrity,47개 테이블·169건 내용 무변경,예약2종0,설정·암호문·미디어36파일 hash 무변경,프로그램 layout 무변경을 확인했다. 이를 실제 API 성공7건으로 해석하지 않는다.

Chrome 인증·제작 동선은 BLOCKED, OpenAI 키 미등록은 BLOCKED, 공급사 계정 권한4종은 NOT VERIFIED다. 자동 rank1과3장면 고정은 PARTIAL이다. 실제 공급사 인증 요청·키 복호화·유료 생성·참조 업로드·SNS/OAuth·무서명 업데이트·V3 변경은 모두0이다. 공개 문서 조회는 이 수치와 별개다.

현재 C:/NewsFlowAI/PID23240/18768은 계속 실행 중이다. 원본·A/B에는 쓰지 않았고 기존 백업 보존 증거를 재사용했다. 새 사용자 데이터·테스트 레코드0, main·PR35 변경/병합0, 외부 배포0이다.

Git에는 이 보고서와 비민감 집계만 보존한다. 개인 예산·실제 음성ID·설정 원문·DB·키·미디어·private baseline은 포함하지 않는다. 허용된 준비 확인을 완료하고 결과 보고로 종료한다.
