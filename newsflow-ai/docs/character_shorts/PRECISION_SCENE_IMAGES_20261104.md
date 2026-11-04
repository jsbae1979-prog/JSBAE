# 캐릭터 장면 이미지 정밀 제작 — 개발 검증 보고

2026-11-04. 최종 판정: **CONDITIONAL**. 개발 기능과 아래 Fake·로컬 검증은 완료했다. 운영 반영, 실제 공급사 성공·청구·이미지 품질 및 장면 연속성의 사용자 인수는 수행하지 않았다.

## 개발 기준과 재사용

- 기존 개발 체크아웃의 `codex/newsflow-character-shorts-automation-20261030`, 기준 SHA `603c87648e4fee2a97bb0b8f28c1d468a7c5e412`에서 별도 브랜치 `codex/newsflow-character-scene-images-20261104`로 개발했다. 새 worktree는 만들지 않았다. 원격 최신화·CI·운영 배포 결과를 주장하지 않는다.
- `AGENTS.md`를 읽고 외부 호출은 Fake, 데이터는 별도 임시 프로필을 사용했다. 최신 사용자 지시에 따라 변경 영향 범위만 검사하고 전체 회귀는 반복하지 않았다.
- 기존 CharacterRegistry, AuthoringAI의 Claude/OpenAI 선택·예산 보호, ImageStudio 자산/초안/출력, ImageGenerationService/OpenAIImageAdapter, 영상 카탈로그·Kling 요청 매핑, CharacterService/EpisodeFlow, FFmpeg 편집·자막·효과음/오디오 연결을 재사용했다.
- 기존 API는 단일 참조 이미지 중심이므로 기존 Image Adapter를 여러 참조 입력까지 확장했다. 별도 이미지 생성 엔진이나 복제 제작실을 만들지 않았다.
- 기존 빠른 제작의 총 길이는 5초 단위였으므로 정밀 제작의 26초를 새로운 설정 스냅샷 버전에서만 허용했다. 기존 작업의 저장값·마이그레이션·빠른 제작 규칙은 변경하지 않았다.

## 구현한 기능

1. 기존 빠른 제작을 유지하고 ‘정밀 제작 — 장면 이미지 먼저 만들기’ 모드를 추가했다.
2. 저장된 캐릭터 1~4개를 선택하고 이름·종류·외형·성격·의상·대표 이미지·해시·버전을 작품에 고정한다. 기존 등록 UI/자산을 재사용하며 원본을 덮어쓰지 않는다.
3. 작품명·주제·관계·장르·세계관·배경·소품·스타일·금지 조건·길이·장면 수·모델·화질·이미지/영상 예산을 저장한다.
4. 기존 AuthoringAI로 구조화된 시나리오를 작성한다. Claude와 OpenAI 모두 Fake 응답으로 검증했으며 스토리 요청에는 참조 이미지 바이트를 보내지 않는다. 사용자가 직접 작성하거나 보관된 후보를 무료 편집할 수도 있다.
5. 장면별 설명·등장인물·배경·자세·표정·구도·소품·연속성·자막·길이·영상 동작·환경음·로컬 효과음을 편집한다. 이미지용 순간 묘사와 영상용 시간에 따른 동작은 별도 프롬프트로 저장한다. 자막은 이미지 프롬프트에서 제외한다.
6. 전체 미생성 장면/선택 장면을 구분해 비용을 계산하고, 참조 전송 및 유료 생성 동의 후 장면별로 순차 요청한다. 장면별 진행·완료/실패/불명 상태와 검토 카드를 표시한다.
7. 선택 장면만 재생성하고 버전을 추가한다. 현재 장면 내용에 맞는 이전 버전을 다시 확정할 수 있다. 다른 장면의 결과·승인과 원본은 유지한다.
8. 모든 장면이 확정된 후에만 기존 영상 제작 작업으로 전달한다. 해당 장면의 확정 이미지를 사용하고 선택 모델·환경음·길이·프롬프트를 유지한다. 영상 재생성 견적도 선택 장면의 이미지를 사용한다.
9. 기존 FFmpeg로 자막·선택 로컬 효과음·장면 연결·최종 MP4를 합성한다. 이미지 생성과 영상 견적/생성은 별도 승인이다. 전달 버튼 자체는 외부 요청을 하지 않는다.
10. 중단 후 ‘저장된 결과 확인 · 무료’로 로컬 완료 기록만 복구한다. 응답 없는 요청은 결과 불명으로 보존하고 자동 재전송하지 않는다. 실행 중에는 파일 잠금과 요청 식별자로 중복 실행을 막는다.

## 데이터와 프롬프트 계약

사용자별 기존 데이터 루트 아래 `character-scene-images/<work_id>.json`에 원자적으로 저장한다. DB 마이그레이션은 없다.

| 저장 단위 | 주요 항목 |
|---|---|
| 작품 | ID, 공통 설정, 캐릭터 스냅샷, 이미지/영상 선택, 시나리오, revision, 승인 이벤트 |
| 캐릭터 | 기존 ID, 이름/종류/외형/성격, 의상, 스타일, 참조 자산 ID·SHA-256·버전 |
| 장면 | 번호, 등장 캐릭터 ID, 설명/장소/자세/표정/구도/소품/연속성, 자막, 목표 초, 동작/카메라/환경음, 로컬 SFX |
| 이미지 버전 | 장면 내용 해시, 요청 ID, 프롬프트와 공통 버전, 참조 ID/버전, 모델·화질·크기, 초안/실행 ID, 결과 자산·해시, 상태, 승인 견적 해시, 예약 비용, 응답 사용량 |
| 확정 | 선택 이미지 버전·해시·확정 시각. 장면 변경 시 그 장면의 확정만 해제 |
| 영상 연결 | 작품 ID, 전체 캐릭터·공통 설정, 장면별 확정 이미지 해시, 고정 motion 프롬프트, 기존 영상 작업 ID |

이미지 요청은 `공통 설정 + 해당 장면 등장 캐릭터 + 동일한 순서의 승인 참조 이미지 + 장면 순간 묘사`로 구성한다. 이미지 안의 자막·말풍선·워터마크를 금지한다. 영상 요청에는 `승인된 시작 이미지 + 동작 + 카메라 움직임 + 이어질 요소`를 넣는다. 환경음 켜짐에도 `No dialogue, no voices, no music.`을 유지한다.

## API·비용·보안

- 경로: PrecisionService → 기존 ImageStudio → ImageGenerationService → OpenAIImageAdapter. 공급사별 실제 multipart 요청은 기존 어댑터가 구성한다.
- 기존 이미지 카탈로그에서 검토된 모델에만 복수 참조를 허용한다. 앱의 상한은 4개다. 미지원 모델/초과 입력을 차단한다. 공식 참고: https://developers.openai.com/api/reference/resources/images/methods/edit
- 기존 단가 추정과 참조 이미지 패치 추정을 재사용한다. 표시값은 **USD 예상 비용/앱 예약 예산**이며 공급사의 확정 청구액이나 강제 청구 상한이 아니다. 실제 청구 검증 상태는 false로 유지한다.
- 견적은 계정 범위·작품 revision·장면·만료 시각에 연결한다. 실행 시 기존 설정 한도와 작품 한도를 다시 검사한다. 불명 요청의 예약액은 해제하거나 0으로 만들지 않는다.
- 실제 API 키를 새 저장 구조에 기록하지 않는다. 기존 DPAPI/비밀값 저장소, LocalAccess·CSRF·Origin 정책을 그대로 사용한다. 새 POST 8개는 두 action registry에 함께 등록했다.
- 사용자별 저장 루트를 분리하며 다른 루트의 작품을 조회할 수 없는 조건을 검사했다. 실제 두 번째 Windows 계정으로 DPAPI/ACL을 검증한 것은 아니다.

## 변경 파일

아래 경로는 `newsflow-ai/` 기준이다.

**신규**
- `src/newsflow/character/precision_contract.py`
- `src/newsflow/character/precision.py`
- `src/newsflow/character/precision_video.py`
- `src/newsflow/gui/character_precision_routes.py`
- `frontend/src/studio/core/CharacterPrecision.tsx`
- `frontend/src/studio/core/character-precision.css`
- `tests/test_character_precision.py`
- `tests/test_character_precision_browser.py`
- `docs/character_shorts/PRECISION_SCENE_IMAGES_20261104.md`

**기존 연결 최소 확장**
- `src/newsflow/publishing/image_reference.py`
- `src/newsflow/publishing/image_generation.py`
- `src/newsflow/creation/image_studio.py`
- `src/newsflow/character/kling.py`
- `src/newsflow/character/service.py`
- `src/newsflow/character/episode_service.py`
- `src/newsflow/character/episode_regeneration.py`
- `src/newsflow/character/compose_studio.py`
- `src/newsflow/character/editing.py`
- `src/newsflow/gui/character_routes.py`
- `src/newsflow/studio/read_models.py`
- `src/newsflow/studio/actions.json`
- `frontend/src/legacy-actions.json`
- `frontend/src/studio/core/CharacterStudio.tsx`
- `tools/studio_v3/tests/test_module_views.py`

기존 미커밋 Analytics/topics/character_automation_routes 및 이전 validation/캡처 자료는 본 작업의 수정·커밋 대상에서 제외했다. 홈·대시보드 구성은 수정하지 않았다.

## 검증 결과

Windows의 기존 Python **3.14.7**, 기존 Node/Chromium/FFmpeg를 사용했다. 새 런타임을 설치하지 않았다. 데이터·로그·이미지·MP4는 개발 임시 경로에만 생성했다.

| 검사 | PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|
| 정밀 제작 단위·통합 `tests/test_character_precision.py` | 20 | 0 | 0 | 0 |
| Windows Chromium 화면 `tests/test_character_precision_browser.py` | 4 | 0 | 0 | 0 |
| 관련 기존 episode schema/editing/catalog/automation, image generation | 68 | 0 | 0 | 0 |
| 기존 선택 장면 영상 재생성 | 8 | 0 | 0 | 0 |
| `tools/studio_v3/tests` | 58 | 0 | 0 | 0 |
| **합계(서로 다른 검사)** | **158** | **0** | **0** | **0** |

추가: TypeScript `tsc --noEmit`, React/Vite build, `git diff --check` 통과. 빌드는 별도 임시 frontend에 본 작업 파일만 반영해 진행했다. 기존 사용자 화면이나 운영 정적 자산은 교체하지 않았다. Python 검사에는 기존 Starlette/httpx deprecation 경고가 있으며 오류는 아니다.

실행 명령(기존 환경의 python 사용):

```text
python -m pytest -q -rs tests/test_character_precision.py
python -m pytest -q -rs tests/test_character_precision_browser.py
python -m pytest -q -rs tests/test_character_episode_schema.py tests/test_character_episode_editing.py tests/test_character_episode_catalog.py tests/test_character_episode_automation.py tests/test_image_generation.py
python -m pytest -q -rs tests/test_character_episode_regeneration.py
python -m pytest -q -rs tools/studio_v3/tests
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build --configLoader runner
```

실행 증거에는 임시 프로필·명시적 FFmpeg·시간대 자료·pytest basetemp/JUnit 옵션을 사용했다. 명령/결과 JSON, 로그, JUnit은 `C:\Codex\NewsFlowAI\precision_scene_20261104\precision-*-command.json`, `precision-*-result.json`, `precision-*.xml`에 보관했다.

EP01은 실제 원본 토토·루루나 ChatGPT의 기존 5장이라고 주장하지 않는다. 합성 캐릭터 프로필·서로 다른 색상 PNG를 사용한 **5/5/6/5/5초, 총 26초** fixture다. 참조 수 **1/2/2/1/2**가 각 요청에 연결됨을 확인했다. 이미지 5장 → 개별 확정 → Fake 영상 5개 → 실제 로컬 FFmpeg MP4까지 통과했다. 자막/SFX도 기존 합성 경로에 전달했다. 최종 길이는 허용 오차 0.12초 이내다.

검사에서 추가로 확인한 항목: 미동의 요청 차단, 예산/계정/이전 revision 변경 차단, 완료 장면 중복 생성 금지, 실패 후 나머지 자동 전송 중단, 불명 요청 재전송 차단, 기존 이미지/다른 장면 승인 보존, 이전 이미지 버전 복원, 중단된 로컬 완료 결과 복구, 장면별 영상 시작 이미지, 26초 기존 영상 화면 표시, 빠른 제작의 기존 5초 단위 제한, 두 캐릭터 정보 분리, Claude/OpenAI Fake 전송, wire schema의 미지원 제약 제거 및 로컬 검증 유지.

## 보존 및 남은 확인

- 운영 `C:\NewsFlowAI`, `D:\NewsFlowAI_Data`, 원본 DB·키·OAuth·미디어·백업을 쓰거나 이주하지 않았다. 운영 프로세스를 시작·종료·재시작하지 않았고 운영 포트를 사용하지 않았다.
- main/PR #35 병합, 실제 수집·유료 생성·SNS·외부 배포는 수행하지 않았다. GitHub CI 및 실제 공급사 성공은 **NOT VERIFIED**다.
- 기존 캐릭터 쇼츠 정책에 따라 이미지/영상은 **9:16**을 유지한다. 1~4명, 2~12장면, 총15~60초와 선택 영상 모델이 지원하는 장면 길이를 검증한다. 무제한 참조/임의 비율을 지원한다고 표시하지 않는다.
- 장면 이미지 검토 후 영상 전달 시 이미지·시나리오·설정을 고정한다. 전달된 영상 작업에서 다른 이미지나 스토리로 바꾸는 기능은 제공하지 않는다. 장면 이미지 수정·버전 선택은 전달 전에 수행한다.
- 이미지 모델이 원본과 동일 외형을 재현하는지, 여러 등장인물을 혼동하지 않는지, 영상이 자연스럽게 이어지는지는 실제 승인 테스트와 사용자 검수가 필요하다. ChatGPT 내부 모델/처리 또는 픽셀 단위 동일성을 보장하지 않는다.
- 실제 사용 전에 등록된 원본 캐릭터/사용권, 선택 모델의 계정 권한·복수 참조 지원·최신 단가, 참조 외부 전송 동의와 이미지/영상별 예산을 확인해야 한다. 이번 Fake 합격을 실제 품질 인수로 대체하지 않는다.

허용된 개발·무료 검증을 마쳤으며 운영 적용이나 실제 유료 생성은 진행하지 않는다.


## 후속 UI 간소화 — 2026-11-04

기준 커밋 `b938ca43eac8c399efc6372a05a2df4940043a86`의 정밀 제작 화면만 개선했다.

- 빠른 제작의 기존 3단계 본문은 유지한다. 정밀 제작도 캐릭터 선택 / 스토리 생성 / 영상 제작의 3열로 정리하고, 장면 이미지 검토를 추가 영역으로 제공한다.
- 등록된 캐릭터의 이미지·특징·스타일·세계관을 재사용한다. 의상 기본값은 “참조 이미지의 의상·액세서리 유지”이며 보이지 않는 의상을 추정하지 않는다. 사용자가 직접 정한 스타일·세계관은 캐릭터 선택으로 덮어쓰지 않는다.
- 작품명은 비우면 주제를 사용하며, 배경·소품·모델 세부 설정과 예산 입력은 접어서 제공한다. 예산이 없으면 설정 필요로 표시하고 무료 작품 저장 이후에도 유료 생성은 별도 동의 전 비활성 상태다.
- 새 작품 기본 길이는 기존 카탈로그의 20초를 사용한다. EP01의 26초는 검증 시나리오에만 남고 기존 저장 작품의 길이는 변경하지 않는다.
- 장면 목록은 작은 선택 카드로, 선택 장면은 큰 미리보기로 표시한다. 버전 선택과 확대 보기, 개별 검토·확정, 선택 재생성을 유지한다.
- 빠른/정밀 제작 전환 시 정밀 제작 컴포넌트를 제거하지 않아 미저장 입력이 유지된다. 작품 전환 시 이전 작품의 동의·선택 상태는 초기화한다. 새 작품을 열고 새로고침했을 때 이전 작품을 잘못 여는 주소 상태도 수정했다.
- 영상 작업에 “확정한 장면 이미지 보기” 링크를 추가했다. 전달 이후 이미지 검토는 가능하지만 기존 영상의 고정된 이미지·시나리오·승인은 수정하지 않는다.

변경 파일:

1. `frontend/src/studio/core/CharacterPrecision.tsx`
2. `frontend/src/studio/core/character-precision.css`
3. `frontend/src/studio/core/CharacterStudio.tsx`
4. `tests/test_character_precision_browser.py`
5. 본 보고서

이번 재검증: 기존 Windows Python 3.14.7 / Chromium, 임시 프로필과 합성 PNG·Fake 공급사.

| 검사 | PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|
| `python -m pytest -q -rs tests/test_character_precision_browser.py` | 5 | 0 | 0 | 0 |

1366/1920 화면에서 기본 20초, 3단계 배치, 입력 유지, 등록 프로필 재사용, 실제 저장 payload, 미동의 생성 차단, 장면 및 이전/최신 이미지 버전 전환, 확정 이미지로 돌아가기와 기록 불변을 검증했다. TypeScript 검사와 React/Vite 빌드도 통과했다. 기존 158 PASS는 이전 단계의 증거로 재사용하며 이번 수치와 합산하지 않는다. 전체 회귀는 반복하지 않았다.

첫 제한 실행은 Playwright 초기화의 Windows 로컬 socketpair에서 정지해 앱 검사에 도달하지 못했다. 그 검사 프로세스만 종료하고 허용된 로컬 실행으로 검사했다. 초기 브라우저 결과 4 PASS / 1 FAIL은 테스트가 캐릭터 목록 순서를 가정한 문제였다. 이름으로 명시 선택하도록 고친 뒤 최종 5 PASS를 확인했다. 기존 Starlette/httpx deprecation 경고 1건은 유지된다.

최종 로그/JUnit: `C:\Codex\NewsFlowAI\precision_scene_20261104\precision-browser.log`, `precision-browser.xml`.
화면 증거는 같은 임시 폴더의 `ui-refinement-evidence`에 보관했다. 캐릭터와 장면 이미지는 실제 사용자 자산이 아닌 색상 PNG다.

운영 앱·DB·키·미디어·백업 접근/변경, 앱 재시작, 외부 API, GitHub push, 운영 반영은 수행하지 않았다. 개발 UI 집중 검증은 ACCEPTED, 실제 운영 화면 및 공급사 이미지·영상 품질은 미검증이다.


## 후속 간소화 2 — 선택과 다음 행동 중심

기준 `ddcef292c9e33c5fc5994f3d3491efdefab6bee5`. 운영 적용 없이 개발 브랜치에서 수행했다.

- 두 개의 제작 방식 버튼을 “장면 이미지를 먼저 검토” 체크 옵션으로 교체했다. 미선택 시 기존 빠른 제작이며, 양쪽 화면의 미저장 상태는 유지된다.
- 별도 작품명 입력과 작품 저장 버튼을 제거했다. 스토리 만들기에서 유료 요청 내용을 확인하면 무료 작품 저장 후 승인된 스토리 요청을 한 번 실행한다. 관리용 제목은 주제에서 최대 100자로 정하고 전체 주제는 별도 필드로 보존한다. 직접 작성도 첫 클릭에 무료 초안을 저장하고 편집 창으로 연결한다.
- 캐릭터 카드에는 이미지·이름을 중심으로 보여 주고 특징·의상은 접었다. 기본 설정은 20초를 유지한다.
- 새 작품은 최근 정밀 작품의 모델·화질·예산 선택값을 재사용한다. 이미지 예산은 현재 설정된 이미지 상한보다 커지지 않도록 제한한다. 승낙·견적·요청·비용 사용 내역은 승계하지 않는다. 기존 기록은 읽기만 한다.
- 단계별 주요 행동은 스토리 만들기 / 장면 이미지 만들기 / 이 이미지 사용 / 영상 제작으로 이동 중 필요한 것만 강조한다. 생성 결과가 없는 단계에서 영상 이동 버튼은 노출하지 않는다.
- 선택 장면 옆에는 “다시 만들기”, “이 이미지 사용”을 배치했다. 버전·프롬프트와 여러 장면 재생성은 접었다. 이미 확정한 버전은 “사용 중인 이미지”로 표시하며 중복 확정 버튼은 비활성화한다.
- 이미지 예산 확인과 참조 이미지 외부 전송 승인은 한 팝업에서 한 번의 명시적 승인으로 처리한다. 팝업을 닫으면 생성하지 않는다. 생성 건수·모델·예상 비용·예약 금액과 실제 청구액의 차이는 그대로 표시한다.
- 모든 장면을 확정하면 한 번의 클릭으로 기존 영상 작업을 준비하고 영상 제작 화면으로 이동한다. 이 이동 자체는 유료 영상 요청이 아니다.

변경 파일: `CharacterPrecision.tsx`, `CharacterStudio.tsx`, `character-precision.css`, `character/precision.py`, `gui/character_precision_routes.py`, `tests/test_character_precision.py`, `tests/test_character_precision_browser.py`, 본 문서. 새 POST 경로와 DB migration은 추가하지 않았다.

검증 환경: 기존 Windows Python 3.14.7, 별도 임시 DB·로컬 이미지·Fake 이미지/영상/스토리 공급사, Windows Chromium 1366/1920. 기존 운영 Chrome에는 연결하지 않았다.

| 집중 검사 | PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|
| 정밀 제작 단위·통합 + 최근 설정 재사용 | 21 | 0 | 0 | 0 |
| 브라우저 화면·작업 동선 | 8 | 0 | 0 | 0 |
| 서로 다른 검사 합계 | 29 | 0 | 0 | 0 |

실행 명령:

```text
python -m pytest -q -rs tests/test_character_precision.py
python -m pytest -q -rs tests/test_character_precision.py::test_precision_catalog_reuses_only_latest_choices_not_approval
python -m pytest -q -rs tests/test_character_precision_browser.py
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build --configLoader runner
```

최초 브라우저 검사의 새 작품 3건은 이전 영상 snapshot 메타데이터를 신규 입력으로 전달해 실패했다. 기존 `kling.check`를 사용해 검증된 선택값만 추출하도록 수정했다. 단위 검사 21건 통과 후 이 변경에 직접 관련된 1건을 다시 실행해 통과했으며 중복 집계하지 않았다. 다음 브라우저 검사 1건은 캐릭터 목록이 로드되기 전에 테스트가 전체 선택을 시도한 문제여서 로딩 완료를 기다리도록 수정했다. 최종 브라우저 8건 전부 통과했다. TypeScript와 React/Vite 빌드, diff 공백 검사도 통과했다. 기존 Starlette/httpx 경고 1종은 유지된다.

중점 확인: 확인 취소 시 생성 0회 / 연속 클릭 시 무료 저장·스토리 호출 각 1회 / 새로고침 및 실패·불명 후 자동 재호출 0회 / 장면·버전 전환 시 다른 결과 불변 / 기존 26초 작업 보존 / 확정 이미지에서 영상 화면 이동 시 새 영상 생성 0회 / 최근 모델·예산만 재사용하고 이전 승인 기록은 원본 그대로 보존.

증거: `C:\Codex\NewsFlowAI\precision_scene_20261104\simplified-evidence`의 로그·JUnit·합성 화면 이미지. 이전 158 PASS 및 1차 UI 5 PASS는 과거 증거이며 이번 합계에 더하지 않았다. 전면 회귀, 실제 API, 운영 반영, 앱 재시작, SNS, 사용자 데이터 변경, GitHub push는 하지 않았다.

판정: 개발·Fake 검증 ACCEPTED. 실제 운영 적용 및 공급사 출력 품질은 이번 범위에서 미검증.

## 2026-11-04: one-scene review workflow refinement

Base: `4fd3f56ea0debbbb8e8f99e297fcca833113289e`. Development only; no operating deployment or restart.

- Collapse completed character/story/settings context when scene images become available and scroll to review. Original settings remain accessible.
- Confirm the visible image and advance to the next unconfirmed scene in one explicit click. Five-scene review takes five confirmation clicks instead of fourteen confirmation/navigation clicks. No popup, automatic confirmation, or automatic paid request is introduced.
- Keep the current scene on confirmation failure. Ignore the second click of a double-click so it cannot confirm the next image accidentally.
- Open only the selected scene in the editor; retain all scene data while switching the scene selector. Show essential fields first and place camera/continuity/caption/sound details in an expandable area.
- Automatically expand budget inputs for first use when required budgets are missing. Positive-budget, story approval, reference-transfer consent and backend enforcement remain unchanged.

Changed implementation: `frontend/src/studio/core/CharacterPrecision.tsx`, `frontend/src/studio/core/character-precision.css`.
Tests: `tests/test_character_precision_browser.py` (eight existing cases adapted/reused plus five focused browser cases).

Windows Python 3.14.7 / isolated Chromium / temporary profiles / Fake providers:
`python -m pytest -q -rs tests/test_character_precision_browser.py` with the existing isolated environment and a temporary React build: **13 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
`tsc --noEmit`: PASS. `vite build --configLoader runner`: PASS.
An initial new editor test used exact label text including a textarea value and could not locate the control. The test now uses its actual accessible textbox role/name; no assertion was removed. Final browser run passed.
Existing unrelated Starlette/httpx deprecation warning remains. Prior backend/FFmpeg evidence reused; no broad regression repeated because backend behavior and provider adapters were not changed.

Checks cover visible first-use budget controls and blocking at zero, five explicit scene confirmations and free handoff, selected-scene editing with other scenes/history unchanged, failed confirmation without navigation/retry, double-click suppression, original mode preservation, image versions, and paid-approval boundaries using Fake providers.

Evidence: `C:\Codex\NewsFlowAI\precision_scene_20261104\review-flow-evidence` (logs, command/result metadata, screenshots). Screenshots use synthetic colored assets, not real user characters or generated artwork.

Operating app/data/keys/media/backups untouched. No paid API, SNS call, user Chrome automation, push, merge, or operating deployment performed. Actual vendor output quality remains unverified. Development UI scope: ACCEPTED.
