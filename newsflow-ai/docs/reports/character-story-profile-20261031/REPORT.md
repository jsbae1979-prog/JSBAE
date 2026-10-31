# 캐릭터 스토리 제작 복원 및 프로필·장면 역할 연결

## 실제 코드와 지시서 대조

현재 신규 React 회차는 `EpisodeFlow.write → episode_story.script_input → AuthoringAI`를 사용합니다. `CharacterWriter.write_studio`와 `StudioStoryboard`는 기존 스튜디오 작업의 작성·호환 경로입니다. 따라서 예시 파일만 바꾸지 않고 두 실제 경로의 지시를 함께 맞췄습니다. V3에는 별도 role 필드가 없어 첫/중간/마지막 순서로 setup/contrast/punchline 역할을 전달합니다. DB나 기존 저장 스키마는 바꾸지 않았습니다.

새 공통 투영은 name, personality, recurring_situation, signature_reaction, world와 필요한 조연 식별 정보를 전달합니다. 저장 구조의 name_ko 및 comedy_formula.setup/reaction/world를 각각 대응시킵니다. 기존 V3 입력 이름도 호환을 위해 유지합니다. appearance·appearance_en·style_lock·style_en·이미지·자산 경로는 스토리 입력에서 제외하며 영상 프롬프트에서만 사용합니다. 특정 캐릭터·직장·성격을 하드코딩하지 않습니다.

INSTRUCTION은 반복 상황을 주제에 맞게 변주하고 캐릭터 고유 반응으로 반전과 마지막 장면을 마무리하도록 보완했습니다. 성격은 모든 장면의 행동·표정, 세계는 기본 장소에 반영하도록 지시합니다. `No fixed mascot or workplace plot.`는 제거했으며 저작권 캐릭터·브랜드·실존 인물 금지와 대사 금지는 유지합니다. 새 작성 응답의 narration은 빈 문자열을 요구하고 로컬에서도 검사합니다. 오래된 저장 narration을 읽거나 다시 쓰지는 않습니다.

## 제작 방식 복원

사용자가 취소한 `이미지·주제 제작` 진입과 직접 견적 함수를 제거해 기존 캐릭터 선택 → 주제·스토리 → 영상 제작 화면으로 복원했습니다. 새 direct 생성 HTTP 요청은 거절합니다. 이미 생성된 직접 제작의 첫 영상·마지막 프레임·실패 기록과 읽기 호환 코드는 보존하며, 기술 실행 계획을 AI 스토리로 표시하지 않습니다. 기존 등록 캐릭터의 주제 자동 생성·기록은 유지하고, 미반영 참조 이미지 주제 생성 확장은 취소했습니다.

파일 전체 HEAD 복원과 전체 역방향 diff는 다른 변경까지 되돌릴 위험으로 자동 승인 심사에서 거절돼 수행하지 않았습니다. 대신 추가한 함수·경로·분기만 확인해 수정했습니다. agent가 만들었던 취소 기능의 새 테스트 두 파일은 명확한 별도 로컬 경로로 복구 가능하게 보관했고 삭제하지 않았습니다. 사용자 기존 미커밋 변경은 보존했습니다.

## 소리와 장면 역할

setup은 상황 확립, build/contrast는 주변과 캐릭터의 대비, punchline은 반응과 과장된 표정을 잠깐 보여 주도록 영상 프롬프트에 전달합니다. 소리 켬은 `Ambient sound effects only: ... No dialogue, no voices, no music.`로 통일합니다. 예전 저장 대사가 있어도 새 프롬프트에 읽기·한국어 대사·립싱크를 넣지 않습니다. 소리 끔은 무음 지시입니다. 기존 승인된 견적이나 전송 payload를 재작성하지 않습니다.

## 변경 파일

- `frontend/src/studio/core/CharacterStudio.tsx`: 원래 스토리 제작만 표시, 이전 직접 제작 영상 카드는 재생 호환 유지.
- `src/newsflow/gui/character_routes.py`: 새 직접 제작 HTTP 요청은 410으로 거절, 기존 스토리 요청은 유지.
- `src/newsflow/studio/read_models.py`: 과거 기술 실행 계획을 AI 스토리로 표시하지 않고 영상·상태·읽기 호환 유지.
- `src/newsflow/character/story_character.py`, `claude.py`, `episode_story.py`, `studio_story.py`, `service.py`: 텍스트 프로필 투영, 상황·반응·세계 지시, 장면 역할, 환경음 전용 프롬프트.
- `src/newsflow/character/episode_service.py`: 이전 준비본의 연속 장면 기록 형식 보완도 반영. 기존 미확정 작업은 수정하거나 재전송하지 않음.
- `src/newsflow/intelligence/provider.py`: 전체 검사에서 드러난 불필요한 원격 식별자 노출을 추가로 가림. 300자 제한·요청/키 가림 유지.
- `tests/test_character_story_direction.py`: Fake writer로 두 캐릭터 분리, 시각 정보 제외, 장면 역할, 환경음, 빈 narration 검증.
- 영향받은 기존 Python·브라우저 검사: 반복 승인 UI를 다시 추가하지 않고 현재 승인된 화면 계약과 단일 스토리 흐름을 검증.
- `tests/character_budget_override.test.mjs`, `character_story_requests.test.mjs`: 현재 함수 구조·TypeScript 구문·사전 조회/전송 분리를 실행하도록 로컬 테스트 도구 보완. 실제 전송은 Fake.

## 검증 결과

Windows 11 build 26300 / Python 3.12.10 / Node 24.19.0. TypeScript와 React 빌드 PASS. 집중 검사 98 PASS 및 최종 Node 31 PASS / 0 FAIL. 기존 직접 제작의 15초 합성 MP4를 실제 브라우저 미리보기로 재생하고 원본 작업 불변을 확인한 강화된 UI 검사 2 PASS.

요청한 단일 `python -m pytest -q -rs` 최초 실행은 **6434 PASS / 38 FAIL / 49 SKIP**입니다. 이전 수집 코드의 기대와 기존 반복 승인·화면 계약, 누락된 기준 자료·시간대 환경을 정리했습니다. 기준 프로그램 파일 5개는 이미 보관된 manifest와 해시로 확인하고 읽기 전용으로만 연결했습니다. Guard/CI 환경 위조나 전역 권한 완화는 하지 않았습니다.

최종 코드의 전체 6521개 항목을 중복 없는 4묶음으로 재실행한 원시 결과는 **6471 PASS / 1 FAIL / 49 SKIP**입니다. 수집·실행 항목 전부를 대조했습니다. 수집 시마다 새 UUID가 붙는 기존 합성 매개변수 1건만 같은 파일·함수·매개변수 위치로 대응했습니다. 누락·중복은 없습니다.

실패한 1건은 기존 뉴스 `test_step13j_user_flow`의 로컬 FFmpeg 합성입니다. 단독 재검증은 **1 PASS**였습니다. 병렬 자원 경합은 추정이며 직접 원인은 확정하지 않았습니다. 전체 시험이 한 번에 모두 통과했다고 주장하지 않습니다. 각 항목의 최신 확인 결과를 합치면 **6472 PASS / 0 FAIL / 49 SKIP**이며, 이 값은 재검증 포함 수치입니다. SKIP 사유는 SAFE_EVIDENCE.json에 구분했습니다. 실제 AI/RSS 호출 opt-in, 테스트 도구 검색 경로·폰트·심볼릭 링크·DPAPI 환경 제한 등이 포함됩니다. 핵심 Fake 제작의 15/35/60초 실제 로컬 FFmpeg 결과는 별도로 통과했습니다. Python 3.14 전체 회귀와 실제 AI 생성 품질은 이번 범위에서 미검증입니다.

## 운영 반영과 보호

이미 승인된 정상 Stop·Start **각 1회**, Stop 코드 **0**. 운영 소스 `55caa0db30dc841d8373108746bb4d2fd4328a0d`, `C:\NewsFlowAI`, loopback **18768**, 새 PID **27464**. Python 9개와 React 2개만 반영했습니다. 변경 전 일관된 DB 백업과 종료 후 프로필 174개 파일·프로그램 복구본을 로컬 비공개로 보존했습니다.

운영 **47개 테이블의 전체 내용과 기사 169건**, 기존 프로필 173개 비교 대상 파일, 원본 DB·백업 A/B·키·미디어 보존을 확인했습니다. 승인·비용·결과 불명·인증·Origin·CSRF·DPAPI·ACL·업데이트 정책은 유지했습니다. 과거 첫 영상과 실패 기록은 변경하지 않았으며 자동 재시도도 하지 않았습니다.

사용자 Chrome에서 정상 인증, 직접 제작 선택지 제거, 스토리 버튼, 기존 영상 카드, 새 작업의 참조 이미지·주제·영상 설정 복원을 확인했습니다. 실제 화면 캡처는 사용자 콘텐츠가 있어 로컬 비공개에 보관하고 GitHub에는 올리지 않았습니다. 운영 GUI 확인 후에도 DB·키·미디어·백업 불변을 재확인했습니다. 유료 AI·SNS 호출 **0**입니다.

## 최종 판정

**CONDITIONAL**. 요청한 제작 방식 복원과 프로필·상황·대비·반전 연결은 구현·집중 검증·운영 반영 완료입니다. 전체 병렬 시험의 기존 FFmpeg 1건 간헐 실패 조건은 별도로 남깁니다. 해당 항목은 단독 실행에서 통과했으며, 이번 수정과 관련한 미해결 기능 실패는 확인되지 않았습니다. 새 유료 스토리·영상 생성 없이 종료합니다. main/PR #35 병합이나 외부 배포는 하지 않았습니다.
