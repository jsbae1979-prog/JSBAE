# 정밀 캐릭터 쇼츠: 승인된 장소 이미지 재사용 검증 (2026-11-05)

## 판정과 적용 범위

CONDITIONAL: 개발 및 모의 검증 완료. 실제 공급사 출력 품질과 운영 반영은 이번 작업에서 검증/실행하지 않았다.
기준 커밋: a3eeb74d38dca3fa8dee9893f0aa61c05d1e23b8.
브랜치: codex/newsflow-character-scene-images-20261104.
운영 프로그램, DB, API 키, 미디어, 백업, 기존 이미지 5장에 쓰지 않았다. 운영 시작/종료, 유료 호출, SNS, 배포, 병합을 실행하지 않았다.

## 확인한 원인

기존 정밀 제작의 각 이미지 요청은 캐릭터 원본만 전송했다. 배경·소품은 텍스트로만 전달하므로 같은 주방도 독립적으로 재해석될 수 있었다.
영상의 continue 연결에는 이미 이전 클립의 검증된 마지막 프레임 전달, 부모 클립 해시·시도 번호, 다음 요청 전 사용자 검토가 있었다. 이 기존 경로를 재사용한다.
장면 이미지란 해당 행동의 시작 상태다. 이것을 앞 영상의 끝 상태 대신 강제로 삽입하면 자세가 초기화될 수 있으므로 영상 이어붙이기 방식을 임의 변경하지 않았다.

## 개선한 제작 순서

1. 스토리와 장소·배경·시작 상태를 검토한다.
2. 같은 장소의 첫 장면 이미지를 생성한다.
3. 사용자가 캐릭터 좌우, 창문·가구, 소품 모양·개수, 시작 동작을 보고 확정한다.
4. 나머지 장면은 캐릭터 원본 + 확정된 장소 이미지로 생성한다. 참조 번호별 역할을 프롬프트에서 구분하며 현재 장면의 인물·소품 상태만 사용한다.
5. 장면별 이미지 확정 후 기존 영상 제작으로 이동한다.
6. continue 장면은 앞 영상의 마지막 프레임을 사용한다. 앞 클립 검토 없이는 다음 유료 생성 요청을 보내지 않는다.
7. 장면을 모두 검토한 뒤 기존 FFmpeg로 최종 합성한다.

처음 확정한 장소 이미지와 종속 장면은 같은 재생성 요청에 섞지 않는다. 장소가 다르면 별도 기준 장면을 사용한다.
다음 제작 버튼은 접힌 설정 밖의 검토 영역에도 표시한다. 배경 기준이 달라진 이전 결과는 보존하지만 영상 전달·재확정은 차단한다. 원래 기준 버전으로 돌아가면 정확히 같은 연결의 기존 결과를 다시 사용할 수 있다.

## 저장·비용·호환성

- 새 작품과 명시적으로 만든 연결 보완 초안만 `approved-set-reference-v1` 사용. 기존 작품은 자동 마이그레이션하지 않는다.
- 요청/결과에 기준 장면 번호·버전·자산·SHA-256·계획 해시를 보관한다.
- 견적은 실제 추가 참조 이미지와 수정된 프롬프트 비용을 포함한다. 전송 직전 입력 해시를 다시 대조한다.
- 이미지 생성/재생성은 기존 비용·외부 전송 동의, 사용자별 데이터, 불명 결과 재전송 차단을 유지한다.
- 기존 OpenAI ImageStudio와 multipart Adapter, 자산 저장소, 캐릭터 영상 Adapter, FFmpeg를 재사용한다. 새로운 생성 엔진/POST 경로/마이그레이션 없음.
- 현재 앱의 참조 이미지 한도 4개를 확대하거나 초과 입력을 묵인하지 않는다. 캐릭터 참조 + 장소 참조 합계가 한도를 넘으면 전송 전에 중단한다.

## 변경 파일

- src/newsflow/character/precision_visual.py: 장소 참조 연결·프롬프트·유효성·화면용 상태.
- src/newsflow/character/precision.py: 새 작품 정책, 실제 참조 전송, 비용/해시 검증, 결과 버전, 확정/영상 전달 보호.
- src/newsflow/gui/character_precision_routes.py: 저장 기록을 변경하지 않는 화면 상태.
- frontend/src/studio/core/CharacterPrecision.tsx: 첫 장면 검토→나머지 생성, 배경 기준 표시, 오래된 기준의 결과 확인 차단.
- tests/test_precision_visual.py, tests/test_precision_visual_browser.py: 새 집중 검증.
- tests/test_character_precision.py, tests/test_character_precision_continuity.py: 이전 저장 형식 fixture 명시.
- tests/test_character_precision_browser.py: 진행 상태 selector 구분, 새 작업에 유효한 모의 시나리오.

## 검증

Windows Python 3.14.7, 기존 Node, FFmpeg/FFprobe. 개발용 임시 DB/파일, 합성 이미지, Fake image/video provider만 사용.
PYTHONPATH는 현재 checkout의 src;tools, NEWSFLOW_FFMPEG/FFPROBE는 기존 검증 바이너리, EDITORIAL_TEST_DIST는 개발 frontend/dist를 지정했다.

| 범위 | 최종 PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|
| 신규 장소 참조 계약·두 영상 모델·FFmpeg | 15 | 0 | 0 | 0 |
| 기존 precision/continuity/causal 관련 계약 | 67 | 0 | 0 | 0 |
| 신규/기존 임시 Chrome 화면 | 23 | 0 | 0 | 0 |
| tools/studio_v3/tests | 58 | 0 | 0 | 0 |

합계 163개(중복 재실행 제외). 신규 검사는 위 표 중 계약 15개와 화면 2개, 합계 17개다.
Kling 3.0 Standard와 Kling O3 각각 Fake 5장면→검토→마지막 프레임 연결→FFmpeg MP4가 완료됐고 최종 길이 26초 ±0.2초를 확인한다. 이것은 실제 공급사 품질/청구 성공 증거가 아니다.
React 타입 검사·Vite build 성공. 기존 font 런타임 경로/번들 크기/lucide directive 경고는 남음.

실행 명령:
```
python -m pytest -q -rs tests/test_precision_visual.py tests/test_character_precision.py tests/test_character_precision_continuity.py tests/test_precision_causal.py
python -m pytest -q -rs tests/test_precision_visual.py tests/test_precision_causal.py::test_operating_wrapper_allows_only_local_review_with_csrf
python -m pytest -q -rs tests/test_precision_visual.py --junitxml=visual-contract.xml
python -m pytest -q -rs tests/test_precision_visual_browser.py tests/test_character_precision_browser.py tests/test_precision_causal_browser.py --junitxml=visual-browser.xml
python -m pytest -q -rs tools/studio_v3/tests
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
```

초기 검사 오류를 숨기지 않는다: 기존 venv가 다른 checkout을 참조하여 수집 ERROR 4건 → PYTHONPATH 지정. 서로 다른 conftest를 한 번에 수집해 ERROR 3건 → 두 폴더 별도 실행. 첫 계약 검사는 78 PASS/3 FAIL: 저장 자산 보호 예외에 맞춘 테스트, 참조 입력 예외의 안전한 안내 처리, tools 경로 지정 후 해당 검사를 통과했다. 첫 화면 검사는 16 PASS/7 FAIL: 복수 status 요소 selector, 새 규칙에 맞지 않는 오래된 Fake 시나리오, 변경 안내를 수정하고 23 PASS를 확인했다. 추가 두 모델 테스트의 26초 정밀 플래그·모델별 화질·probe import fixture를 바로잡아 최종 15 PASS를 기록했다. assertion 삭제/skip/실제 보안 완화 없음.

## 공식 문서 대조

- OpenAI Image prompting: 복수 참조의 역할과 유지할 배경·구도를 명확히 지정하는 접근을 적용. 모델 자동 전환이나 새 미지원 파라미터는 추가하지 않았다.
  https://developers.openai.com/api/docs/guides/image-prompting
- OpenAI Image generation: 일관성과 정확한 배치에는 한계가 있어 인간의 최종 검토가 필요하다.
  https://developers.openai.com/api/docs/guides/image-generation
- Higgsfield Kling 3.0 Standard: image_url과 3~15초 duration, sound, multi_shots, optional last_image_url의 실제 API 스키마 확인. 이미지용 시작 상태를 종료 상태로 오용하지 않고 기존 시작 프레임 연결을 재사용.
  https://open.higgsfield.ai/models/kling-video/v3.0/std/image-to-video/api-reference

## 남은 확인

운영 반영은 미실행. 기존 5장은 자동 개선/재생성하지 않았다. 새 방식의 실제 이미지 결과, 좌우·손·소품·배경 유지, 실제 영상 품질은 사용자 승인 후 별도 검토해야 한다. 자연스러운 연결이나 동일한 외형을 100% 보장한다고 주장하지 않는다. 실패·불명 결과 자동 재시도도 하지 않는다.
