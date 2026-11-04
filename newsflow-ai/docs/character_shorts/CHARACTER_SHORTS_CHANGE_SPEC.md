# NewsFlow AI 캐릭터 쇼츠 자동화 지시서 (최종)

Oct 30, 2026 · @토린

## 목적과 확정 사항

NewsFlow AI에 이미 있는 "캐릭터 쇼츠" 기능을 아래 방향으로 변경한다. 캐릭터를 등록해 두고 주제를 고르면, Claude가 대본을 쓰고 Higgsfield가 영상을 만들고 ffmpeg가 편집해 유튜브 쇼츠 파일을 출력한다. 업로드는 사람이 검수 후 직접 한다.

이 문서가 최신본이다. 앞서 작성된 캐릭터 쇼츠 지시서, 모델 선택 UI 지시서, 통합 지시서와 다른 부분은 이 문서를 따른다.

| 항목 | 확정 내용 |
| --- | --- |
| 플랫폼 | 유튜브 쇼츠, 1080×1920 (9:16 고정) |
| 장르 | 캐릭터 코미디, 빠른 전개 |
| 표현 | 대사 없음. 표정·행동·효과음·자막으로만 전달 |
| 길이 | 사용자가 편마다 선택 (기존과 같이 15\~60초, 5초 단위). 선택한 길이 하나로 대본을 쓰고 출력 |
| 캐릭터 | 등록제. 캐릭터마다 특징 파일을 두고 모든 단계가 이 파일을 기준으로 동작. 첫 캐릭터는 "느긋해 대리" |
| 주제 | 캐릭터 특징에 맞춰 자동 생성, 또는 직접 입력 |
| 화면 효과 | 줌·흔들림·카메라 움직임은 영상 생성 단계에서 프롬프트로 포함 |
| 소리 | 현장 소리는 영상 생성 단계(소리 생성 기본 켜기), 코미디 효과음은 편집 단계 |
| 편집 | ffmpeg. 장면 단위로 연결·빠르게 감기·정지·코미디 효과음·자막만 처리 |
| 영상 모델 | 사용자가 편마다 선택. 모델 목록은 설정 파일(모델 카탈로그)에서 관리하고 코드에 고정하지 않음. 초기 등록 예: Kling 3.0, Kling 3.0 Turbo |
| 승인 | 비용이 드는 영상 생성 전에 사람이 대본 승인 |
| 업로드 | 자동화하지 않음 |

**사용자가 선택하는 항목**: 캐릭터, 주제, 길이(15\~60초, 5초 단위), AI API(Claude 또는 OpenAI), 영상 모델, 화질, 소리 생성 켜기·끄기. **고정**: 9:16 비율, 캐릭터 스타일. 선택 항목의 목록과 기본값은 모두 설정으로 관리하고 코드에 고정하지 않는다.

**첫 버전에서 제외**: 유튜브 자동 업로드, 생성 영상을 분석해 컷을 정밀하게 자르는 편집, 등록 캐릭터 여러 명 동시 등장(조연은 글 설명으로만 등장, 장면마다 모습이 달라져도 허용), 유료 편집 서비스.

## 현재 구현 상태와 변경 요약

캐릭터 쇼츠는 이미 구현되어 있다. 이 문서는 새로 만드는 지시가 아니라 **기존 구현을 아래처럼 변경하는 지시**다. 기준은 2026-10-30에 확인한 `codex/newsflow-bat-distribution-prep` 브랜치(최신 커밋 2026-10-30 07:50)이며, 작업 전 최신 브랜치에서 다시 확인한다. 뒤 섹션의 파일 이름·폴더 구조와 다르면 **기존 코드 구조를 우선**하고, 뒤 섹션은 동작 규칙과 지시문 내용의 기준으로만 쓴다.

**실제로 쓰이는 경로**: "스튜디오" 경로(`character/service.py`의 `create_studio`, `studio_story.py`, `compose_studio.py`, `kling.py`, `video_models/catalog.py`, `config/character_studio.yaml`, `config/video_models.yaml`). `schema.py`의 `CHARACTER_SCRIPT_INSTRUCTION`과 `compose.py`는 이전(30초 카피바라 고정) 경로로, 저장된 이전 작업 호환용으로만 남겨두고 새 작업에는 쓰지 않는다.

**유지할 것 (이미 지시서 방향과 같음)**

- 영상 모델 카탈로그와 선택 (`config/video_models.yaml`, `param_map`, 모델별 길이·소리·단가 정보)
- 길이 선택(15\~60초), 화질·출력 크기, 소리 켜기·끄기, 9:16·스타일 고정
- 참조 이미지 업로드(`higgsfield_client.upload_reference`), 견적·예산 한도, 승인 후 생성, 장면 재시도, 다운로드 복구
- 대본 단계에서 캐릭터 외모를 지어내지 않고 참조 이미지로 외모를 유지하는 구조, 장면 간 연속성 규칙(최근 커밋)

**변경할 것**

| 항목 | 현재 구현 | 변경 | 관련 섹션 |
| --- | --- | --- | --- |
| 캐릭터 | 작업마다 참조 이미지를 올리거나 라이브러리에 저장(이미지와 파일 이름만). 특징은 없고 외모 문구는 공용 "참조 이미지를 유지하라" 한 줄 | 라이브러리 이미지에 특징(이름, 종류, 외모, 성격, 웃음 공식 등)을 붙여 캐릭터로 등록·수정·삭제. AI 이미지 분석으로 초안 작성 | A |
| 주제 | 사용자가 직접 입력만 가능 | 캐릭터 웃음 공식 기반 주제 자동 생성과 사용 기록 추가 | B |
| 대본 입력 | 주제만 받음(캐릭터 정보 없음), "고정 마스코트·직장 플롯 금지" | 선택한 캐릭터의 성격·웃음 공식(외모 제외)을 함께 넘겨 캐릭터다운 이야기를 쓰게 함 | C |
| 대본 내용 | 행동·자막·분위기 소리 | 카메라 연출, 장면별 속도·끝 정지, 코미디 효과음 위치, 업로드 정보 필드 추가 | C |
| 장면 구성 | 같은 길이 클립 5개 고정(길이는 5초 단위) | 클립 5개 고정을 풀고 길이·모델에 따라 장면 수·길이를 정함. 최근 커밋의 "앞 장면 결과를 이어가는" 규칙은 유지 | C, D |
| 대본 AI | Claude API 모델만 허용 | Claude·OpenAI 사용자 선택 | 확정 사항 |
| 대사 | 소리를 켜면 한국어 대사·립싱크를 넣도록 프롬프트 작성(`studio_story.prompts`) | 항상 대사 없음. 소리를 켜도 현장 소리만(no dialogue, no voices, no music) | D |
| 소리 기본값 | 끄기(`audio_default: false`) | 켜기 | D |
| 편집 | 클립 이어 붙이기만, 자막·효과음 없음(`compose_studio.py`) | 빠르게 감기, 끝 정지, 코미디 효과음, 자막, 오디오 크로스페이드 | E |

이번 확인은 코드 일부를 읽은 결과다. 개발자는 변경 전에 위 표의 "현재 구현"이 맞는지 확인하고, 다르면 이 표를 고쳐서 진행한다.

## 작업 절차와 단계별 담당

여섯 단계(A\~F)로 돌아가며, 비용 대부분은 D단계 영상 생성에서 나온다. 그래서 C단계 끝에 사람의 승인을 둔다.

| 단계 | 하는 일 | 담당 | 호출 횟수 |
| --- | --- | --- | --- |
| A. 캐릭터 등록 | 이미지 업로드 → 특징 초안 → 사용자 확인 → 저장 | Claude API(이미지 분석), Higgsfield API(참조 이미지 업로드) | 캐릭터당 1회 |
| B. 주제 정하기 | 캐릭터 웃음 공식에 맞는 주제 자동 생성, 선택 또는 직접 입력 | Claude API | 필요할 때 1회(여러 개 한꺼번에) |
| C. 대본 생성 | 장면별 내용·카메라 연출·현장 소리·속도·정지·효과음·자막 작성 → 사용자 승인 | Claude API | 편당 1회(검증 실패 시 최대 +2) |
| D. 영상 생성 | 장면별 생성 요청, 이어지는 장면 처리, 다운로드 | Higgsfield API | 편당 장면 수(4\~6) |
| E. 자동 편집 | 장면 연결, 빠르게 감기·정지, 코미디 효과음, 자막, 선택한 길이로 출력 | ffmpeg (API 없음) | - |
| F. 검수·업로드 | 체크리스트 확인, 어긋난 장면만 재생성, 유튜브 업로드 | 사람 | - |

이 문서에서 "Claude API", "Claude가"는 \*\*사용자가 고른 AI API(Claude 또는 OpenAI)\*\*를 뜻한다. 모든 지시문은 두 API에 같은 내용으로 보내고, 기존 NewsFlow AI처럼 요청 형식만 API에 맞게 다르게 만든다. 이미지 분석(A단계)은 이미지 입력을 지원하는 모델만 선택할 수 있게 한다. 영상 생성은 현재 Higgsfield API 기준이며, 모델 카탈로그에 `provider` 항목을 두어 나중에 다른 영상 API를 추가할 수 있게 한다.

**핵심 원칙**

1. 캐릭터 특징 파일이 주제·대본·영상 프롬프트 모든 단계의 기준이다. 특정 캐릭터(느긋해 대리) 내용을 코드나 지시문에 고정하지 않는다.
2. 비용이 드는 영상 생성 전에 사람이 대본을 승인한다.
3. 대사는 없다. 영상 프롬프트에 항상 "no dialogue, no voices, no music"를 넣는다.
4. 영상 생성으로 가능한 것(줌·흔들림·카메라·현장 소리)은 생성에서, 불가능한 것(빠르게 감기·정지·코미디 효과음·자막)만 편집에서 처리한다.
5. 효과 강도는 Claude가 약·중·강으로 고르고, 실제 수치는 설정 파일에서 가져온다.
6. 소리 생성을 지원하지 않는 모델은 현장 소리 없이 편집 효과음만 사용한다.

**API 키**: AI API는 기존 NewsFlow AI의 Claude·OpenAI 키 설정을 그대로 쓴다. 영상은 `HF_KEY`(Higgsfield API 키, 웹사이트 크레딧과 별개인 선불 달러 잔액)를 새로 추가한다. 선택한 API의 키가 없으면 화면에서 그 API를 고를 수 없게 한다.

## 기존 NewsFlow AI 통합과 모듈 구조

새 패키지 `newsflow/character/`를 추가하고, 기존 `intelligence/`는 공용 기능만 가져다 쓴다. 뉴스 대본 기능의 동작은 바꾸지 않는다. 기준은 PR #35 커밋(`3c5230942466a87e5bc191961538e9bbccddc90b`)이며 작업 전 최신 브랜치에서 다시 확인한다.

**재사용**

- `intelligence/api_providers.py`: Claude·OpenAI 호출 구조(사용자가 고른 API로 호출), 키 관리, 모델·토큰·온도 옵션
- `intelligence/provider.py`: `user_message()` JSON 직렬화
- `intelligence/schema.py`: Pydantic 검증 방식
- `intelligence/service.py`: 작업 실행·저장 흐름, `script_method` 기록 (캐릭터 쇼츠는 `character_v1`)

**변경 위치 (기존 코드 기준)**

아래 패키지·파일 이름, `config/`·`data/`·`assets/`·`output/` 폴더, 설정을 YAML·주제 기록을 JSON 파일로 저장하는 방식은 **예시**다. 기존 NewsFlow AI의 폴더 구조, 설정 위치, 데이터 저장 방식(파일·데이터베이스), 화면 구현 방식에 맞춰 개발자가 정한다. 지켜야 하는 것은 기능 단위의 분리(등록·주제·대본·생성·편집·실행 관리)와 캐릭터·모델·효과 강도·효과음을 코드가 아닌 설정으로 관리하는 원칙이다.

| 기능 | 변경할 기존 코드 | 내용 |
| --- | --- | --- |
| A. 캐릭터 등록 | `creation/image_studio.py`의 `save_character`(라이브러리 저장), `gui/character_routes.py`의 `/api/studio/characters/library` | 저장된 이미지에 캐릭터 특징 프로필을 붙이고 등록·수정·삭제 추가. `character/assets/neutgeuthae.json` 형식을 프로필 형식으로 재사용하고 느긋해 대리를 기본 등록 캐릭터로 넣음 |
| B. 주제 자동 생성 | 없음 (신규) | `character` 패키지에 주제 생성·기록 모듈과 화면 추가 |
| C. 대본 생성 | `character/studio_story.py`(`StudioStoryboard`, `INSTRUCTION`, `timing_errors`), `character/claude.py` | 지시문을 이 문서 C의 `SCRIPT_INSTRUCTION` 기준으로 교체하고 캐릭터 특징을 입력에 추가, 스키마에 camera·sound·speed·freeze\_end·sfx·continuity·upload 추가 |
| 대본 AI 선택 | `character/kling.py`의 `validate`(`script_model`을 Claude API 모델로 제한), `character/claude.py` | OpenAI 모델 허용, 호출은 `intelligence/api_providers.py` 구조 재사용 |
| D. 영상 생성 | `character/service.py`의 `generation_rows`(클립 5개·같은 길이 강제), `character/studio_story.py`의 `prompts`, `video_models/catalog.py`의 `compose_prompt`, `config/character_studio.yaml` | 장면 수·길이 가변화와 continue 시작 프레임, 대사 지시 제거, 카메라·현장 소리 문구, 선택 캐릭터의 외모 문구 사용, `audio_default`를 true로 |
| E. 자동 편집 | `character/compose_studio.py` | 연결만 하던 기능에 빠르게 감기·끝 정지·코미디 효과음·자막·오디오 크로스페이드 추가. 기존 폰트 `character/assets/NotoSansKR.ttf`(OFL) 재사용 가능 |
| 화면 | `gui/character_routes.py`, 스튜디오 화면(`gui/studio_v3.py` 등) | 캐릭터 선택·등록, 주제 자동 생성, AI API 선택, 대본 미리보기 항목 추가 |
| 이전 경로 | `character/schema.py`의 `CHARACTER_SCRIPT_INSTRUCTION`·`prompts`, `character/compose.py` | 카피바라·사무실이 고정된 이전 경로. 저장된 이전 작업을 열 때만 쓰고 새 작업에는 사용하지 않음 |

**작업 폴더 (편당)**

```text
output/character/<날짜>_<캐릭터>_<주제요약>/
  job.json        # 캐릭터, 주제, 길이, 모델, 화질, 소리 설정
  script.json     # C 결과, 승인 기록 포함
  jobs.json       # D 요청 ID, 상태, 요청 본문(키 제외), 비용
  scenes/scene_01.mp4 ...
  frames/scene_01_last.png ...
  final.mp4       # 선택한 길이의 완성본
  review.json     # F 체크리스트, 총비용
```

단계마다 출력 파일이 있으면 건너뛰어, 중단된 작업을 이어서 실행할 수 있게 한다. 새 의존성은 `higgsfield-client`, `pyyaml`, 시스템 ffmpeg다.

## A. 캐릭터 등록

이미지를 올리면 Claude가 특징 초안을 만들고, 사용자가 확인·수정한 뒤 저장한다. 파일: `character/registry.py`

캐릭터는 여러 명 등록될 수 있다. 이 문서의 지시문(이미지 분석, 주제 생성, 대본 생성)은 특정 캐릭터 내용을 담지 않고 항상 선택한 캐릭터 파일(`input.character`)만 따른다. 문서에 나오는 느긋해 대리, 플라밍고 팀장, 서버 장애 주제, 50편 목록은 모두 초기 데이터와 예시이며 코드나 지시문에 넣지 않는다.

**절차**

1. 이미지 업로드 (PNG/JPG, 10MB 이하). 실존 인물 사진과 기존 유명 캐릭터 이미지는 사용하지 않는다는 안내를 표시한다.
2. Claude API에 이미지를 첨부해 분석 요청 (지시문은 아래).
3. 확인 화면: 외모·종류는 초안을 보여 주고 수정 가능, 이름·성격·웃음 공식은 후보 3개 중 선택 또는 직접 입력.
4. 저장: `config/characters/<id>.yaml` 생성, 이미지는 `assets/characters/<id>_ref.png`에 복사 후 Higgsfield에 업로드해 `public_url` 저장.
5. 수정·삭제: 모든 항목 수정 가능. 외모 문구를 고치면 이후 생성부터 반영. 참조 이미지를 바꾸면 재업로드. 삭제는 설정 파일만 제거하고 과거 작업 폴더는 유지.

**등록 항목 (`config/characters/<id>.yaml`)**

| 항목 | 필수 | 작성 | 용도 |
| --- | --- | --- | --- |
| id | ○ | 자동 (영문 소문자) | 파일·폴더 이름 |
| name\_ko | ○ | AI 후보 → 선택 | 화면 표시, 자막 |
| species | ○ | AI 초안 → 확인 | 대본·프롬프트 |
| appearance | ○ | AI 초안(영어) → 확인 | 모든 장면 프롬프트에 자동 삽입 |
| personality | ○ | AI 후보 → 선택 | 대본·주제 생성 |
| comedy\_formula.world | ○ | AI 후보 → 선택 | 주 무대 (예: 회사) |
| comedy\_formula.setup | ○ | AI 후보 → 선택 | 자주 생기는 상황 |
| comedy\_formula.reaction | ○ | AI 후보 → 선택 | 캐릭터의 반응 방식 (웃음 포인트) |
| style\_lock | ○ | 기본값 자동 (이미지 그림체에 맞춰 제안) | 모든 장면 프롬프트 |
| reference\_image | ○ | 자동 | 영상 생성 시작 이미지 |
| supporting\_cast |  | 선택 입력 | 조연 (글 설명만) |
| audience |  | 기본 general | 대본 톤 |
| made\_for\_kids | ○ | 기본 false | 검수 체크리스트 |

**예시: 느긋해 대리**

```yaml
id: neutgeuthae
name_ko: 느긋해 대리
species: capybara
appearance: >
  chubby round capybara with soft brown fur, sleepy half-closed relaxed eyes,
  tiny calm smile, small orange tangerine balanced on its head,
  white short-sleeve office shirt, loose navy necktie, employee ID badge on a lanyard
personality: 무슨 일이 터져도 세상 평온한 만사태평형
comedy_formula:
  world: 회사 사무실
  setup: 마감·장애·상사 호통 등 주변이 난리나는 상황
  reaction: 혼자 느리고 태평하게 반응하며 귤이나 차로 대응
style_lock: soft 3D animated film style, warm pastel lighting, consistent character design
reference_image:
  local_path: assets/characters/neutgeuthae_ref.png
  public_url: null
supporting_cast:
  - id: team_lead
    appearance: stressed tall flamingo manager in a gray suit
audience: adult office workers
made_for_kids: false
```

**이미지 분석 지시문**

```python
CHARACTER_ANALYSIS_INSTRUCTION = (
    "You analyze an uploaded original mascot character image for a dialogue-free comedy YouTube Shorts series. "
    "Return JSON only: species (<=40 chars), "
    "appearance (English, <=400 chars: body shape, colors, face, eyes, clothing, accessories; "
    "describe only what is visible, no personality, no background), "
    "style_suggestion (English, <=150 chars, the art style of the image), "
    "candidates (exactly 3 objects: name_ko (<=10 chars Korean), personality (<=80 chars Korean, "
    "shown through actions and expressions, not speech), comedy_formula (world, setup, reaction, each <=60 chars Korean)). "
    "Make the 3 candidates clearly different from each other. "
    "If the image shows a real person or a well-known existing character, return {\"rejected\": true, \"reason\": \"...\"} instead."
)
```

## B. 주제 자동 생성

캐릭터를 고르면 Claude가 그 캐릭터의 웃음 공식에 맞는 주제를 여러 개 만든다. 사용자는 그중 고르거나 직접 한 줄을 쓴다. 파일: `character/topics.py`

**동작**

- "주제 자동 생성" 클릭 → 기본 10개 생성 (1\~50개 선택 가능).
- 생성된 주제는 `data/topics.json`에 캐릭터별로 저장하고 상태를 관리한다: `new`(미사용), `scripted`(대본 생성됨), `produced`(영상 완성), `skipped`(보류).
- 생성 요청 때 기존 주제 전체(상태 무관)를 넘겨 중복과 비슷한 웃음 구조를 피하게 한다.
- 직접 입력한 주제도 같은 목록에 저장한다.
- 느긋해 대리용으로 작성된 50편 주제 목록을 초기 데이터로 불러올 수 있게 CSV 가져오기를 제공한다 (번호, 카테고리, 주제).

**요청**

```json
{
  "count": 10,
  "character": {"name_ko": "...", "species": "...", "personality": "...",
                "comedy_formula": {"world": "...", "setup": "...", "reaction": "..."},
                "supporting_cast": ["..."]},
  "existing_topics": ["기존 주제 전체"]
}
```

**지시문**

```python
TOPIC_INSTRUCTION = (
    "You create episode topics for a fast-paced, dialogue-free comedy YouTube Shorts series "
    "starring the character in input.character. "
    "Return JSON only: topics (exactly input.count objects with topic (<=60 chars Korean, one line: "
    "the situation and the character's reaction), category (<=10 chars Korean), "
    "joke_type (<=20 chars, a short label of the joke structure)). "
    "Every topic must fit comedy_formula: happen in or near its world, start from a setup like it, "
    "and end with the character's typical reaction. "
    "Each topic must be showable without dialogue, through actions, expressions, sound effects and short captions. "
    "Spread topics across at least 5 categories and avoid repeating a joke_type more than twice. "
    "Do not repeat or closely resemble any of input.existing_topics. "
    "Audience follows input.character.audience; do not aim content at children. "
    "No real people, companies, brands or existing characters; no violence, injury or insults."
)
```

## C. 대본 생성

대본은 장면 단위다. 장면마다 화면 내용, 카메라 연출, 현장 소리, 편집 지시(속도·정지·효과음·자막)를 담는다. 파일: `character/script.py`

**요청**

```python
# 길이별 장면 수 (코드 설정)
def base_scene_count(target_seconds):          # 15~60초, 5초 단위
    if target_seconds <= 20: return 2, 3
    if target_seconds <= 35: return 3, 4
    if target_seconds <= 50: return 4, 5
    return 4, 6

def scene_range(target_seconds, model):
    lo, hi = base_scene_count(target_seconds)
    need = math.ceil(target_seconds / model.duration_max)   # 모델 최대 길이로 채우려면 필요한 최소 장면 수
    lo = max(lo, need)
    return lo, max(hi, lo + 1)

model = catalog[job.model_id]                 # 사용자가 선택한 모델
min_scenes, max_scenes = scene_range(job.target_seconds, model)
resp = client.messages.create(
    model=options.model, max_tokens=4000, temperature=0.8,
    system=SCRIPT_INSTRUCTION,
    messages=[{"role": "user", "content": json.dumps({
        "target_seconds": job.target_seconds,     # 사용자가 선택한 길이 (15~60, 5초 단위)
        "min_scenes": min_scenes,
        "max_scenes": max_scenes,
        "topic": job.topic,                      # 예: "서버 장애로 사무실이 난리, 대리님은 귤 까는 중"
        "min_scene_seconds": model.duration_min,
        "max_scene_seconds": model.duration_max,   # 선택 모델 기준
        "native_sound": job.sound and model.audio_native,
        "character": load_character(job.character_id),  # 선택한 캐릭터 파일 (appearance 제외)
        "sfx_keys": ["ding", "whoosh", "pop", "boing", "..."],
        "recent_topics": ["최근 5편 주제와 joke_type"]
    }, ensure_ascii=False)}],
)
```

**지시문 전문**

```python
SCRIPT_INSTRUCTION = (
    "You write fast-paced, dialogue-free comedy YouTube Shorts scripts starring the character in input.character. "
    "Never change the character; follow its personality and comedy_formula. "
    "Return JSON only with keys in this order: plan, title, hook_caption, scenes, end_caption, upload. "
    "plan (write first, build the script from it): situation, escalation, reaction, punchline (each <=150 chars). "
    "scenes: input.min_scenes to input.max_scenes objects with no (integer from 1), "
    "seconds (integer, input.min_scene_seconds to input.max_scene_seconds), "
    "continuity (cut or continue), from (earlier scene number, only when continue), "
    "action (English <=300 chars: setting, what happens, exaggerated expressions; one continuous shot; "
    "never describe the main character's appearance, the system adds it), "
    "camera (English <=120 chars: camera movement such as quick zoom in, slow push in, shaky handheld, whip pan, static wide), "
    "sound (English <=100 chars: on-screen sounds only, used when input.native_sound is true, else empty), "
    "speed (normal or fast), fast_intensity (weak, medium, strong; only when speed is fast), "
    "freeze_end (none, weak, medium, strong: hold the last frame), "
    "sfx (list of {at: start or end, key: one of input.sfx_keys}; comedic stings only, max 2), "
    "caption (<=20 chars Korean situation label, or empty). "
    "Use continue only when the scene is the same place and moment right after the earlier scene. "
    "Pacing follows input.character.comedy_formula: scenes that build the setup or chaos use fast speed and energetic camera; scenes showing the character's signature reaction use the speed and camera that best sell that reaction (by default normal speed with a push in or quick zoom on the face)"
    "; the last scene is the punchline with freeze_end medium or strong. "
    "For short lengths, keep only the setup, one chaos beat and the punchline. "
    "Playback length of a scene is seconds / speed factor (normal 1.0; fast weak 1.25, medium 1.5, strong 2.0) "
    "plus freeze seconds (weak 0.5, medium 1.0, strong 1.5). "
    "Total playback of all scenes must be between input.target_seconds - 2 and input.target_seconds. "
    "No spoken dialogue anywhere; captions label situations, never speech. "
    "hook_caption (<=20 chars Korean) for the first 2 seconds; end_caption (<=20 chars Korean) invites sharing or following. "
    "upload: title (<=60 chars Korean), description (<=200 chars Korean), hashtags (3-6). "
    "Avoid the joke structures of input.recent_topics. "
    "No real people, companies, brands, logos or existing characters; no violence, injury or insults; not aimed at children."
)
```

**스키마 검증 (`character/schema.py`)**

- 장면 수가 scene\_range() 범위 안(기본 20초 이하 2\~3, 35초 이하 3\~4, 50초 이하 4\~5, 그 이상 4\~6. 선택 모델의 최대 길이가 짧아 부족하면 최소 장면 수를 '선택 길이 ÷ 모델 최대 길이' 올림값으로 올리고 최대도 그에 맞춰 늘림), `no` 연속, 장면 길이 범위, `continue`의 `from`이 앞 장면
- 허용 값만: `speed`, `fast_intensity`, `freeze_end`, `sfx.key`는 `sfx_map.yaml` 키
- 마지막 장면은 `freeze_end`가 medium 또는 strong
- 재생 길이는 코드가 `edit_presets.yaml` 수치로 직접 계산해 선택 길이(목표-2초 \~ 목표) 범위를 확인 (AI 계산을 믿지 않음)
- 길이 문자 제한 초과는 거부
- 실패 시 실패 이유를 덧붙여 최대 2회 재생성, 그래도 실패하면 중단

**승인**

- 길이는 대본 생성 전에 사용자가 고른다 (15\~60초, 5초 단위). 길이를 바꾸면 대본을 다시 생성한다.
- 화면에 장면별 내용(한글 요약 포함), 카메라, 속도·정지, 효과음, 자막, 예상 재생 길이, 예상 비용을 보여 준다.
- 사용자는 승인 / 다시 생성 / 자막·효과음 직접 수정을 할 수 있다. `action`·`camera` 수정은 고급 모드에서만.
- 승인 시각과 승인된 대본을 `script.json`에 기록하고, 승인 없이는 D단계를 실행하지 않는다.

## D. 영상 생성

승인된 대본의 장면마다 Higgsfield API에 생성을 요청한다. 카메라 연출과 현장 소리는 이 단계에서 만들어진다. 파일: `character/prompts.py`, `higgsfield.py`, `generate.py`

**프롬프트 조립 (코드가 자동으로)**

```python
def scene_prompt(character, scene, native_sound):
    parts = [
        character.style_lock,
        character.appearance,
        mentioned_cast(character, scene.action),   # 언급된 조연 외모만
        scene.action,
        f"Camera: {scene.camera}.",
        "Exaggerated comedic expressions and body language.",
        "no dialogue, no voices, no music, no text on screen",
    ]
    if native_sound and scene.sound:
        parts.append(f"Sound effects only: {scene.sound}.")
    return " ".join(p for p in parts if p)
```

**요청 본문 예 (Kling 3.0)**

```json
{
  "prompt": "<scene_prompt 결과>",
  "duration": 12,
  "aspect_ratio": "9:16",
  "mode": "std",
  "sound": "on",
  "start_image": "<시작 이미지 public_url>"
}
```

- 시작 이미지: `cut` 장면은 캐릭터 참조 이미지, `continue` 장면은 `from` 장면의 마지막 프레임.
- 파라미터 이름은 2026-10-22 Higgsfield 모델 조회 기준이며, REST 경로·이미지 전달 형식은 API 문서로 확인한다. 모델별 차이는 `catalog.py`에서 변환한다.

**모델 카탈로그 (`config/video_models.yaml`)**

모델은 사용자가 고르며, 목록과 모델별 차이는 모두 설정 파일에서 관리한다. 기존 config/video\_models.yaml이 이미 이 역할을 하고 있으므로(현재 Kling 3.0 Standard, Kling O3 등록) 형식은 기존 파일을 따르고, 아래는 필요한 정보를 보여 주는 예시다. 새 모델을 쓰려면 항목만 추가하고 코드는 고치지 않는다.

```yaml
- id: kling3_0                 # 초기 등록 예시
  label: Kling 3.0
  enabled: true
  recommended: true
  api_path: "<API 문서에서 확인>"
  aspect_ratios: ["9:16", "16:9", "1:1"]
  duration: { min: 3, max: 15 }
  quality: { param: mode, options: [std, pro, 4k], default: std }
  audio: { native: true, param: sound, on: "on", off: "off" }
  start_image: { supported: true, param: start_image }
  pricing: { unit: per_second, usd: "<API 단가표>", audio_multiplier: "<단가표>" }
- id: kling3_0_turbo
  label: Kling 3.0 Turbo
  enabled: true
  api_path: "<API 문서에서 확인>"
  aspect_ratios: ["9:16", "16:9", "1:1"]
  duration: { min: 3, max: 15 }
  quality: { param: resolution, options: [720p, 1080p], default: 720p }
  audio: { native: false }
  start_image: { supported: true, param: start_image }
  pricing: { unit: per_second, usd: "<API 단가표>" }
```

- 화면의 모델 목록은 `enabled: true`이면서 `9:16`을 지원하고 `start_image.supported: true`인 모델만 보여 준다. 참조 이미지를 못 받는 모델은 캐릭터를 유지할 수 없어 제외한다.
- 모델마다 다른 파라미터 이름(화질·소리·시작 이미지)은 `catalog.py`가 이 파일을 읽어 변환한다.
- 장면 길이 범위·장면 수는 선택한 모델의 `duration`으로 계산해 대본 요청에 넘긴다. 그래서 모델은 대본 생성 전에 고르고, 대본 승인 후 모델을 바꾸면 장면 길이가 새 모델 범위에 맞는지 다시 검사해 안 맞으면 대본 재생성을 안내한다.
- 값은 2026-10-22 Higgsfield 모델 조회 기준 예시다. 경로·파라미터·단가는 구현 시점의 API 문서로 확인한다.

**실행 순서 (`generate.py`)**

1. `cut` 장면을 모두 동시에 요청한다 (키당 동시 20건 이내).
2. 완료된 장면은 즉시 다운로드한다 (결과는 최소 7일만 보관).
3. `continue` 장면은 `from` 장면이 끝나면 마지막 프레임을 추출·업로드해 요청한다. `ffmpeg -sseof -0.1 -i scene.mp4 -frames:v 1 last.png` → `POST /files/generate-upload-url` → PUT → `public_url`
4. 모든 장면이 모이면 E단계로 넘긴다.

- 상태는 `queued`, `in_progress`, `completed`, `failed`, `nsfw`, `canceled`를 구분해 처리한다.
- 요청마다 `Idempotency-Key`(`작업ID-s장면번호-t시도번호`)를 붙여 중복 과금을 막는다.
- 이미 다운로드된 장면은 다시 요청하지 않는다.

**소리 설정**

- 화면의 "소리 생성" 기본값은 켜기다. 켜면 현장 소리(발소리, 경보음 등)가 영상과 함께 생성된다.
- 끄거나 소리 미지원 모델을 고르면 `native_sound: false`로 대본을 생성하고, 최종 영상에는 코미디 효과음만 들어간다.
- 참고 비용(웹사이트 기준): Kling 3.0 std 15초 소리 켜면 30크레딧, 끄면 22.5크레딧. 60초 분량이면 약 120 / 90크레딧. API는 달러 단가표로 따로 계산한다.

## E. 자동 편집

ffmpeg가 대본의 장면별 편집 지시를 읽어 장면 단위로 처리한다. 줌·흔들림은 생성 단계에서 이미 들어갔으므로 편집에서는 다루지 않는다. 파일: `character/compose.py`

**처리 순서 (장면마다 → 전체)**

1. **규격 통일**: 1080×1920, 30fps, H.264, 오디오 AAC 48kHz. 소리 없는 장면은 무음 트랙을 추가해 연결 시 어긋나지 않게 한다.
2. **빠르게 감기** (`speed: fast`): 영상 `setpts=PTS/{배속}`. 현장 소리는 `atempo`로 같은 배속 적용(음높이 유지), strong(2배)에서 소리가 어색하면 설정으로 음량을 낮추거나 무음 처리.
3. **끝 정지** (`freeze_end`): 마지막 프레임을 설정 초만큼 유지(`tpad=stop_mode=clone`), 오디오는 같은 길이 무음 추가.
4. **연결**: 장면 순서대로 이어 붙인다. 영상은 바로 자르고(빠른 템포), 오디오만 연결 지점에 0.15초 크로스페이드를 넣어 소리가 뚝 끊기지 않게 한다.
5. **코미디 효과음**: 장면 `sfx`의 `at`(start/end) 시점에 배치(`adelay` + `amix`). `end`는 정지가 시작되는 순간에 맞춘다. 음량은 설정값으로 통일.
6. **자막**: `hook_caption` 0\~2초, 장면 `caption`은 해당 장면 구간, `end_caption` 마지막 2초. 화면 상단 25% 영역, 굵은 한글 폰트 + 외곽선. 대본에서 ASS 자막 파일을 만들어 `subtitles` 필터로 입힌다.
7. **출력**: 전체 장면을 `final.mp4` 하나로 출력한다. 선택 길이보다 짧으면 마지막 정지 시간을 늘려 정확히 맞추고, 길면 마지막 이전 장면의 끝을 잘라 맞춘다.
8. **음량 정규화**: 최종 오디오를 -14 LUFS 기준으로 맞춘다 (`loudnorm`).

**효과 강도 설정 (`config/edit_presets.yaml`)**

Claude는 약·중·강만 고르고, 실제 수치는 이 파일에서 가져온다. 값을 바꾸면 이후 모든 편에 반영된다.

```yaml
fast:   { weak: 1.25, medium: 1.5, strong: 2.0 }   # 배속
freeze: { weak: 0.5,  medium: 1.0, strong: 1.5 }   # 정지 초
sfx_volume_db: -6
scene_audio_crossfade: 0.15
fast_strong_audio: duck      # keep | duck | mute
caption:
  font: assets/fonts/<굵은한글폰트>.ttf
  size: 72
  outline: 6
  top_margin_ratio: 0.12
```

**코미디 효과음 (`config/sfx_map.yaml`)**

현장 소리는 영상 생성에서 나오므로, 여기에는 웃음을 강조하는 효과음 10개 안팎만 둔다. 모두 상업 이용이 허용된 소스만 사용한다.

```yaml
ding: assets/sfx/ding.mp3        # 정지·반전 순간
whoosh: assets/sfx/whoosh.mp3    # 빠른 전환
pop: assets/sfx/pop.mp3          # 깜짝 등장
boing: assets/sfx/boing.mp3      # 엉뚱한 동작
record_scratch: assets/sfx/record_scratch.mp3   # 멈춰!
cricket: assets/sfx/cricket.mp3  # 어색한 침묵
sparkle: assets/sfx/sparkle.mp3  # 평화로운 순간
drum_hit: assets/sfx/drum_hit.mp3  # 펀치라인
```

## 화면, 예산·재시도, 보안

**화면 구성** (기존 시안의 3단 구성 유지)

| 영역 | 내용 |
| --- | --- |
| 1. 캐릭터 | 등록된 캐릭터 선택, 새 캐릭터 등록(A단계 확인 화면), 수정·삭제 |
| 2. 주제·대본 | AI API 선택(Claude/OpenAI, 키가 있는 것만), 주제 자동 생성 목록(상태 표시), 직접 입력, 대본 생성 → 장면별 미리보기 → 승인 / 다시 생성 / 자막·효과음 수정 |
| 3. 영상 | 모델, 화질, 소리 생성 토글, 길이 선택(15\~60초, 5초 단위, 대본 생성 전), 예상 비용, 생성 버튼, 장면별 진행 상태, 완성본 미리보기·다운로드 |

- 비율은 "9:16 (쇼츠)", 스타일은 "캐릭터 고정"으로 잠금 표시한다.
- 모델을 바꾸면 화질 선택지와 소리 토글을 카탈로그 기준으로 다시 계산한다. 지원되는 값은 유지, 아니면 가장 가까운 값으로 바꾸고 한 줄로 알린다. 소리를 지원하지 않는 모델을 고르면 소리 토글이 꺼지고 비활성화된다. 모델을 바꾸면 장면 길이 범위가 달라질 수 있으므로 모델은 대본 생성 전에 고른다.
- 소리 설정을 바꾸면 대본의 `sound` 필드가 달라지므로, 승인 전이면 대본을 다시 생성하거나 `sound`를 무시하고 생성한다(사용자 선택).
- 모델 최대 길이가 대본 장면 길이와 맞지 않으면 생성을 막고 대본 재생성을 안내한다.
- 일괄 모드: 주제 여러 개를 골라 대본만 한꺼번에 생성 → 각각 승인 → 승인된 것만 순서대로 영상 생성(대기열).

**예산**

- `CHARACTER_MAX_USD_PER_EPISODE`(편당), `CHARACTER_MAX_USD_PER_DAY`(일일). 예상 비용이 넘으면 생성 버튼 비활성 + 이유 표시.
- 예상 비용 = 장면 초 합계 × 모델 단가(화질·소리 반영). API 단가표를 카탈로그에 넣고, 비용 계산 API가 있으면 그것을 우선한다.
- 재시도 비용도 편당 상한에 포함하고, 실제 차감액을 기록해 월별 합계를 보여 준다.

**재시도**

| 상황 | 처리 |
| --- | --- |
| Claude 응답 검증 실패 | 실패 이유를 덧붙여 최대 2회 재생성 |
| Claude·Higgsfield 일시 오류(용량 초과 등) | 30초·60초 후 재시도, 계속되면 "잠시 후 또는 다른 모델" 안내 (자동 전환 없음) |
| 영상 `failed` | 같은 요청 최대 2회 재요청 (실패는 미과금) |
| 영상 `nsfw` | 재시도 안 함, 해당 장면 사람 검토 표시 |
| 요청 타임아웃 | 같은 `Idempotency-Key`로 상태 확인 후 필요할 때만 재전송 |
| 검수에서 장면 재생성 | 그 장면과, 그 장면에서 이어지는(`continue`) 장면만 다시 생성 후 E단계 재실행 |

**보안**

- AI API 키(Claude·OpenAI)와 `HF_KEY`는 기존 NewsFlow AI 방식대로 환경변수 등에서만 읽고, 코드·설정 파일·로그·작업 기록에 남기지 않는다.
- 파일 업로드용 presigned URL에는 인증 헤더를 보내지 않는다.
- 사용자가 입력한 주제·캐릭터 텍스트는 사용자 메시지의 데이터 필드로만 전달하고 시스템 프롬프트에 이어 붙이지 않는다.

## 구현 전 확인 목록

아래는 이 문서 작성 시점에 확인하지 못했거나 웹사이트 기준으로만 확인한 항목이다. 개발자가 구현 전에 확인하고, 다르면 실제 값을 따른다.

- [ ] "현재 구현 상태와 변경 요약" 표와 "변경 위치" 표가 최신 브랜치 코드와 맞는지 (일부만 읽고 작성함)
- [ ] 기존 AI API 추상화(현재 Claude·OpenAI 공용 구조)에 이미지 입력을 추가하는 방법
- [ ] Higgsfield API의 선택 모델별 REST 경로와 파라미터 이름(길이, 비율, 화질, 소리, 시작 이미지). 문서 값은 웹사이트 모델 조회 기준
- [ ] Higgsfield API 달러 단가표(모델·화질·소리별)와 비용 계산 API 존재 여부. 문서의 크레딧 수치는 웹사이트 기준
- [ ] Higgsfield 웹훅 설정 방법 (없으면 상태 조회로 구현)
- [ ] 사용할 한글 폰트와 코미디 효과음의 상업 이용 라이선스
- [ ] ffmpeg를 설치할 실행 환경(PC 또는 서버)과 버전

## F. 검수·업로드, 개발 순서, 완료 기준

**검수 체크리스트 (`review.json`, 사람이 확인)**

- [ ] 모든 장면에서 주인공 외모가 참조 이미지와 일치
- [ ] 대사·웅얼거림·음악이 섞이지 않았는지 (소리 생성 켜진 경우)
- [ ] 빠르게 감긴 장면과 느린 반응 장면의 대비가 보이는지
- [ ] 자막 오탈자, 하단 UI에 가리지 않는지
- [ ] 효과음 타이밍·음량, 장면 연결 지점 소리
- [ ] 선택한 길이와 마지막 반전 장면
- [ ] 업로드 정보(제목·설명·해시태그) 확인

어긋난 장면은 그 장면만 재생성하고 E단계를 다시 실행한다.

**업로드 (사람)**

- 대본의 `upload` 필드(제목·설명·해시태그)를 복사해 쓴다.
- AI 생성 콘텐츠 표시, 아동용 "아니요", 배경음악은 유튜브 오디오 보관함에서 선택.
- 업로드 후 화면에서 해당 주제를 `produced`로 표시한다.

**개발 순서 (비용 없는 부분부터)**

1. 설정 파일·스키마, 느긋해 대리 캐릭터 파일, 50편 주제 CSV 가져오기
2. A. 캐릭터 등록 (이미지 분석 → 확인 → 저장, Higgsfield 업로드는 마지막에)
3. B. 주제 자동 생성, C. 대본 생성·검증·승인
4. E. 자동 편집: 참조 이미지로 만든 테스트 영상(장면당 정지 영상 + 테스트 소리)으로 속도·정지·효과음·자막·두 버전 출력 완성
5. D. 영상 생성 연동 (장면 1개 → 한 편, 소액 예산)
6. 화면, 일괄 모드, 재개·예산·재시도

**단위 테스트**

- [ ] 캐릭터 파일 필수 항목 누락 시 오류, 수정 후 다음 프롬프트에 반영
- [ ] 이미지 분석 응답이 후보 3개이고, `rejected` 응답 시 등록 중단
- [ ] 주제 생성: 요청 개수, 기존 주제와 완전 중복 없음, 상태 저장
- [ ] 대본 검증: 장면 수·길이, continue 규칙, 허용 값, 마지막 장면 규칙, 길이별 장면 수, 선택 길이에 맞는 재생 길이 계산 (15·20·35·50·60초 등 경계값 포함)
- [ ] 프롬프트에 style\_lock·appearance·camera·"no dialogue, no voices, no music" 항상 포함, 소리 꺼짐이면 sound 문구 없음
- [ ] 모델 변환: 카탈로그의 파라미터 매핑대로 변환(예: Kling 3.0은 mode·sound, Turbo는 resolution만), 카탈로그에 모델을 추가하면 코드 수정 없이 선택지에 나타남, 참조 이미지 미지원 모델은 목록에서 제외
- [ ] 실행 순서: cut 동시, continue는 from 완료 후 (HTTP 모킹)
- [ ] 편집: 2배속 10초 → 5초, freeze medium +1초, 무음 장면 연결 시 오디오 어긋남 없음, 최종 길이 오차 0.1초 이내

**완료 기준**

캐릭터 2명(느긋해 대리 + 새로 등록한 캐릭터 1명)으로 각각 자동 생성 주제를 골라 총 3편을 처음부터 끝까지 실행해 아래를 만족한다.

| 항목 | 기준 |
| --- | --- |
| 캐릭터 분리 | 새 캐릭터 편의 주제·대본·프롬프트에 느긋해 대리 특징이 섞이지 않음 |
| 길이 선택 | 3편을 서로 다른 길이(예: 15·30·60초)로 만들어 각각 선택 길이대로 출력 |
| 결과물 | 편당 `final.mp4` (1080×1920, 선택 길이 오차 0.1초 이내) |
| 대사 | 음성 대사 없음 |
| 연출 | 카메라 연출이 생성 영상에 반영, 마지막 장면 정지 + 효과음 |
| 승인 | 승인 없이 영상 생성 요청이 나가지 않음 |
| 재개 | 중단 후 재실행 시 완료된 장면을 다시 요청하지 않음 |
| 비용 | 편당 실제 비용 기록, 상한 이하 |
| 기존 기능 | 뉴스 대본 기능 기존 테스트 전부 통과 |
| 보안 | 로그·출력 어디에도 API 키 없음 |

## 참고 자료

- [Higgsfield API 문서 색인](https://docs.higgsfield.ai/docs/index.md)
- [Higgsfield SDK 가이드](https://docs.higgsfield.ai/docs/how-to/sdk)
- [Higgsfield 요청 수명주기](https://docs.higgsfield.ai/docs/concepts/requests)
- [Higgsfield 파일 업로드](https://docs.higgsfield.ai/docs/concepts/file-uploads)
- [Higgsfield API 도움말 (과금 방식)](https://higgsfield.ai/creator-hub/help-center/integrations/what-is-the-higgsfield-api)
