# NewsFlow AI — 네이비·블루 제작 작업실 적용

2026-10-19 KST. 참고 이미지의 색상·브랜드·버튼·사이드바 분위기를 실제 제작 앱에 적용했다. 홈에서 새 뉴스 제작을 바로 시작하고, 세로 영상과 검토 작업에 집중하도록 정리했다.

기준: `fc4c149445a6cd5a3378510bd928741785f80e5e` → 검증 코드: **`8e53983e9706bd02276bc599d73d6c0c32e59fb0`**.
브랜치 `codex/newsflow-ux-video-app`의 로컬 커밋이다. 원격 push, PR #35 편집·상태 변경, 새 PR, main/다른 브랜치 병합은 하지 않았다. 화면 자료·이 보고서는 후속 문서 커밋으로 보존한다.

## 반영 내용

- 차콜·딥 네이비 배경, 블루 포인트, SVG 브랜드 마크와 일관된 버튼·입력란·포커스 스타일 적용. 큰 장식 배너·임의 통계·가짜 조회수·예상 진행률을 추가하지 않았다.
- 홈에서 기존 제작 폼을 바로 노출한다. 뉴스 자료·분야·기간·길이, 대본 검토, 이번 음성, 기본/AI 영상 선택을 유지한다. 뉴스·대본 AI는 저장된 선택을 표시하고 기존 설정 화면에서 변경한다.
- 보관 기사 검색은 별도 접기 영역으로 분리했다. 기존 저장 기사 GET 검색이며, 자유 주제 신규 검색/URL 직접 제작 기능을 새로 구현하거나 지원하는 것처럼 표시하지 않는다.
- 뉴스 확보·대본 상세 옵션과 준비 진단은 접었다. ElevenLabs/Higgsfield를 선택하면 해당 서비스의 별도 승인 안내만 관련 선택 옆에 표시한다. 선택은 동의나 실제 실행 기록이 아니다.
- 오른쪽에는 검증된 최근 영상의 9:16 썸네일을 표시한다. 영상이 없으면 명확한 빈 화면을 제공한다. 홈·라이브러리는 썸네일을 사용하며 모든 MP4를 미리 로드하거나 자동 재생하지 않는다.
- 영상·작업 선택 시 새 제작 폼을 접어 검토 작업에 집중하도록 했다. 기존 플레이어, 대본·자막 편집, 장면 선택, MP4 저장과 통합 게시 준비를 그대로 연결한다. 썸네일 비율도 9:16으로 맞췄다.
- 설정·게시 화면에는 같은 기본 색상을 적용했다. 기존 설정 5개 그룹, 키 관리, 서비스별 동의·비용 검사와 작업별 선택 고정은 변경하지 않았다.

변경 파일: `base.html`, `easy_home.html`, `creator.css`, `home_production.js`, 신규 `test_blue_studio_browser.py`, 홈에서 바로 시작하도록 동선을 조정한 기존 `test_cloud_workspace_flow.py`.
백엔드·API 계약·검색/대본/TTS/FFmpeg/게시 엔진·마이그레이션·의존성·저장 기본값은 변경하지 않았다.

## Cloud 최종 검증

실제 Linux Cloud Python 3.12.14 / Chromium 151 / FFmpeg·ffprobe 7.1.5에서 격리 DB·합성 키/자료·Fake 공급사만 사용했다. 테스트 서버는 동적 loopback 포트, 데모 화면은 새 `/tmp` 디렉터리를 사용했다. 운영 앱·데이터·키·설정·기존 MP4는 열거나 변경하지 않았다.

| 항목 | 결과 |
|---|---|
| 최종 코드 선택 회귀 | **135 passed / 1 failed / 0 skipped / 0 errors** |
| 새 실제 브라우저 테스트 | 4 passed (세 화면 크기별 홈 동선 3개 + 영상·편집·게시 동선 1개) |
| 기존 Fake API/음성/AI 영상 승인·안전 검사 | 선택 회귀에 포함, 통과 |
| Fake OpenAI·Claude → 대본 검토·편집 → 실제 FFmpeg → 재생 → Fake 통합 게시 | 기존 통합 테스트 2개 통과 |
| 변경 테스트 파일 Ruff / 변경 JavaScript 문법 / pip check | PASS |
| 기준의 실패 전체 테스트 비교 | 동일 테스트 ID·동일 첫 오류, 테스트 파일 해시도 동일 |
| 전체 회귀 | NOT RUN. 기존 **57 FAIL** 기록을 대체하거나 전체 PASS로 보고하지 않음 |
| 실제 Windows 11·Python 3.14·BAT·화면 배율 | NOT VERIFIED |
| 실제 음성/자막 싱크·AI 콘텐츠 품질·실계정 게시 | NOT VERIFIED |

135건의 통과는 전체 제품 승인이나 실제 API 성공을 뜻하지 않는다. 기존 Starlette/httpx deprecation warning 1건도 남았다. 초기 새 브라우저 도구의 중복 합성 설정 준비 문제를 수정한 뒤, 최종 코드에서 전체 선택 범위를 다시 실행했다. 테스트 삭제·추가 skip·보안 완화는 없다.

실패: `tests/test_ux_navigation.py::test_workspace_two_destinations_and_two_production_choices`.
기존 `settings-advanced-tools` dialog를 찾는 첫 검사에서 `AttributeError: 'NoneType' object has no attribute 'group'`가 발생한다. 동일 Python/의존성으로 기준 커밋의 테스트 전체를 실행해 같은 첫 실패를 재현했다. 이미 통합·정리된 설정 구조에 대한 과거 검사이며, 이를 맞추려고 중복 화면을 되살리거나 관련 없는 설정 기능을 개편하지 않았다. 첫 실패 뒤에 도달하지 않은 검사까지 비교했다고 주장하지 않는다.

### 화면·사용 흐름 확인

1366×768 / 1920×1080 / 390×844에서 다음을 실제 브라우저로 확인했다.

- 빈 홈과 합성 영상 보유 상태, 메뉴 이동, 새 제작 폼 즉시 접근, 보관 검색의 URL 입력 오류와 저장 기사 검색.
- 분야·기간·길이·검토·음성·영상 선택 변경과 기존 FormData 계약. 화면에서 선택해도 저장 기본값은 바뀌지 않는다.
- 외부 음성/영상 선택 시 각각의 승인 안내 표시, 로컬/기본 선택 시 숨김. 기존 동의 누락·검증 실패·결과 불명·중복 방지 검사는 기존 회귀로 확인.
- 긴 한글 제목, 세로 썸네일, 실제 합성 MP4의 브라우저 재생·일시 정지, 대본 편집의 장면 선택, 게시 준비 진입.
- 가로 넘침 없음. 작은 화면은 자연스럽게 세로 스크롤하며 긴 선택값은 입력란 안에서 생략 표시한다.
- 키보드 skip link → 본문 포커스, 검색 오류 후 입력란 포커스, 라벨·버튼. 기존 모달 테스트도 통과.
- 측정한 대비: 주요 버튼 5.17:1, hover 4.85:1, 입력 글자 16.27:1, 입력 경계/패널 3.53:1. 일부 요소의 측정이며 전체 WCAG 인증이 아니다.

뷰포트 검사는 Windows OS 배율 검증이 아니다. 무음 합성 MP4 재생은 렌더링·재생 확인이며 사람의 청취·자막 음성 싱크 품질 검증이 아니다. 실제 사용자 사용성 과제 평가는 별도다.

### 실행 명령

프로젝트의 기존 `.venv`에서 다음을 실행했다.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_BLUE_STUDIO_EVIDENCE=/tmp/newsflow-blue-studio/final-browser \
NEWSFLOW_VALIDATION_OUTPUT=/tmp/newsflow-blue-studio/final-flow \
.venv/bin/python -m pytest -q -rs \
  tests/test_single_workspace.py tests/test_production_choices.py \
  tests/test_settings_simplification.py tests/test_creator_ui.py tests/test_ux_navigation.py \
  tests/test_all_scene_browser.py tests/test_all_scene_safety.py \
  tests/test_production_options_browser.py tests/test_model_picker_browser.py \
  tests/test_settings_streamlined_browser.py tests/test_blue_studio_browser.py \
  tests/test_cloud_workspace_flow.py tests/test_creator_scene_browser.py \
  --junitxml=/tmp/newsflow-blue-studio/final.xml

.venv/bin/python -m ruff check tests/test_blue_studio_browser.py tests/test_cloud_workspace_flow.py
node --check src/newsflow/static/js/home_production.js
.venv/bin/python -m pip check
```

기준 실패 비교는 기준 소스 archive 디렉터리에서 같은 `.venv/bin/python`, 해당 소스의 `PYTHONPATH`, 같은 node ID와 pytest 옵션으로 실행했다. 로그·XML·해시 비교는 아래 증거에 보존했다.

## 화면 자료

모두 실제 앱/템플릿의 Cloud 브라우저 캡처다. 데모 배너와 합성/무음 자료를 사용하며 실제 서비스 연결을 뜻하지 않는다. 전후 캡처의 저장된 AI 선택·콘텐츠 상태가 일부 다르므로 순수 픽셀 비교로 해석하지 않는다. 재생 화면의 모션은 캡처 안정성을 위해 줄였으며 Windows 배율 검증이 아니다.

| 화면 | 이전 | 적용 후 |
|---|---|---|
| 홈 | [기존 홈](evidence/blue-studio/before-home-1366.png) | [1366](evidence/blue-studio/home-1366.png) · [1920](evidence/blue-studio/home-1920.png) · [빈 화면](evidence/blue-studio/home-empty-1366.png) · [모바일](evidence/blue-studio/home-mobile.png) |
| 제작 | [기존 제작](evidence/blue-studio/before-create-1366.png) | [제작](evidence/blue-studio/create-1366.png) |
| 설정 | [기존 설정](evidence/blue-studio/before-settings-1366.png) | [설정](evidence/blue-studio/settings-1366.png) · [모바일](evidence/blue-studio/settings-mobile.png) |
| 영상 | — | [라이브러리](evidence/blue-studio/library-1366.png) · [미리보기](evidence/blue-studio/preview-1366.png) · [장면 편집](evidence/blue-studio/editor-1366.png) |
| 게시 | — | [게시 준비](evidence/blue-studio/publishing-1366.png) |

[테스트 XML](evidence/blue-studio/tests.xml) · [로그](evidence/blue-studio/tests.log) · [기준 XML](evidence/blue-studio/baseline-navigation.xml) · [검증 요약](evidence/blue-studio/validation-summary.json) · [대비 측정](evidence/blue-studio/contrast.json).

## 보존 및 남은 확인

실제 유료 API·공급사 계정 조회/인증·OAuth·SNS 전송/게시 **0건**. CSRF/CSP/SSRF/TLS·비용·외부 전송 승인·작업별 설정 고정·결과 불명 중단·최종 영상 검토·별도 게시 승인 경계를 유지한다.

Windows 사용자 PC에서 저장된 실제 설정으로 화면·배율·키보드·음성과 재생을 확인해야 한다. Windows Actions나 원격 코드 변경으로 검증 환경 부재를 우회하지 않았다. 추가 엔진 개발·운영 반영 없이 로컬 결과를 보존하고 종료한다.
