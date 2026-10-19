# 아이콘·타이포그래피·사용성 점검 — 2026-10-19 KST

시작 `4959c40` (clean), 검증 코드 `73af5b9`. 원격 push·PR #35 변경 없음.

## 확인 및 보완

실제 Cloud 브라우저에서 홈·제작·영상 목록·대본 편집·게시 준비·설정의 6개 화면을 1366×768 / 1920×1080 / 390×844로 확인했다.

- 홈에 8~11px 출처·단계·도움말이 많고 문자 기호와 SVG 아이콘이 섞여 있었다. 주요 메뉴·작업·재생·설정 아이콘을 24-unit, 1.8 stroke의 동일한 로컬 SVG 매크로로 통일했다. 장식은 aria-hidden이며 버튼/링크 이름을 보존했다. 외부 아이콘 패키지·CDN 호출 없음.
- 안내 글씨를 12px 이상, 입력값을 14px로 조정했다. Noto Sans CJK KR을 한글 폰트 fallback에 추가했고 실제 Cloud 제목에서 사용됨을 Chromium font API로 확인했다. Windows의 맑은 고딕을 유지하며 폰트 다운로드·설치는 하지 않았다.
- 버튼·장면 탭·설정 점프는 44px 이상 높이, 주 제작 버튼은 46px로 조정했다. 키보드 포커스와 disabled 동작 유지. 사이드바는 낮은 창에서 스크롤 가능하다.
- 좁은 중앙 열·모바일에서는 음성/영상 선택란을 한 줄씩 배치했다. ElevenLabs와 Higgsfield+FFmpeg의 전체 선택 문자열이 3개 크기에서 실제 입력 폭에 맞음을 확인했다.
- 설정의 한글 단어 중간 줄바꿈과 아이콘 유무 차이를 정리했다. 의미 없는 기사 장식 순번은 제거하고 기사 category 코드는 기존 한국어 라벨로 표시했다.
- 생성 이미지, 기존 엔진·폼·승인·작업 저장·데이터는 유지했다. 새 기능·실서비스 연결 없음.

전후 DOM 검사에서 홈의 12px 미만 텍스트 후보 38개가 0개로 줄었다. 이 수치는 지정한 DOM 태그·표시 조건에 대한 측정이며 모든 픽셀이나 접근성 전체를 인증하는 수치는 아니다. 색상 표본: 주 버튼 5.17:1, 입력값 16.27:1. 보수적인 밝은 패널 배경을 사용한 label 표본은 7.32:1. 반투명 보조 버튼의 JSON 계산값은 alpha 합성을 고려하지 않은 참고값으로, 확정 대비 통과 주장에 사용하지 않는다. 이미지 위 문구까지 포함한 전체 WCAG 검증은 수행하지 않았다.

## 검증 결과

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_BLUE_STUDIO_EVIDENCE=/tmp/newsflow-ui-audit/final-browser \
.venv/bin/python -m pytest -q -rs \
 tests/test_blue_studio_browser.py tests/test_settings_streamlined_browser.py \
 tests/test_creator_scene_browser.py tests/test_single_workspace.py \
 tests/test_settings_simplification.py tests/test_creator_ui.py \
 --junitxml=/tmp/newsflow-ui-audit/final-scoped.xml
```

**55 passed / 0 failed / 0 skipped**, 39.09초. 기존 Starlette/httpx deprecation warning 1건. `git diff --check` 통과.

기존 선택·설정 저장/재진입·기본값 보존·별도 승인·보관 기사 검색·키보드 이동·장면 선택/순서·무음 재생·게시 준비 테스트를 재사용했다. 별도 화면 점검 18조합 모두 HTTP 200 / 가로 넘침 없음. 외부 브라우저 요청 0건이며 실제 공급사 API·OAuth·SNS 호출은 하지 않았다. 결과는 합성 DB/키 없는 격리환경이다.

[pytest 로그](evidence/ui-polish/final-scoped.log) · [JUnit](evidence/ui-polish/final-scoped.xml) · [전 측정](evidence/ui-polish/before-audit.json) · [후 측정](evidence/ui-polish/final-audit.json) · [폰트·대비·선택 폭](evidence/ui-polish/measurements.json)

[이전 홈](evidence/generated-earth/home-1366.png) · [현재 홈](evidence/ui-polish/home-1366.png) · [모바일 홈](evidence/ui-polish/home-390.png) · [모바일 선택값](evidence/ui-polish/mobile-production-options.png) · [설정](evidence/ui-polish/settings-1366.png) · [모바일 설정](evidence/ui-polish/settings-390.png) · [편집](evidence/ui-polish/editor-1366.png)

기존 전체 회귀 57 FAIL과 기존 별도 UI 실패 기록은 유지한다. 전체 pytest 및 기준 전체 비교를 반복하지 않았으며, 범위 결과를 전체 PASS로 확대하지 않는다. Windows 사용자 PC·Windows 배율·3.14·실제 음질·공급사 품질·실계정 동작은 NOT VERIFIED다.

## 이후 전달된 프리미엄 목업 지시

별도 디자인 목업을 이미지 생성 도구로 1회 생성했다. 이는 위에서 테스트한 실제 UI와 구별되는 디자인 제안이다. KPI·차트·트렌드·TikTok 등은 합성/컨셉 표시이며 기능 구현을 뜻하지 않는다. 앱에 새 통계·새 게시 엔진·계정 프로필을 추가하지 않았다.

- PNG 생성 원본: `/workspace/NewsFlowAI-design/NewsFlowAI-premium-original.png`, 실제 1672×941.
- 1920×1080 SVG 제안: `/workspace/NewsFlowAI-design/NewsFlowAI-premium-1920x1080.svg`. 원본 PNG를 변경 없이 포함한 독립 SVG 캔버스다. 글자를 벡터로 다시 만든 것은 아니다.
- 원본은 `/workspace/generated_images`에도 보존했다.

이미지 생성 도구 호출은 이번 별도 디자인 요청에 따른 것이다. 제품의 유료 뉴스/음성/영상 공급사 호출과 다르다. 목업을 운영 화면/실연동 증거로 보고하지 않는다.
