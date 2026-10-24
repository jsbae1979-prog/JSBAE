# PR #35 · Storyflow SVG 최소 적용 검토

## 기준 및 결론

요청 근거: [PR 댓글 #6377644799](https://github.com/jsbae1979-prog/JSBAE/pull/35#issuecomment-6377644799).
기준 PR HEAD `c988fa2dfe42d2a54f67207a2f608bcb15ca8237`, 검증 코드
`cf1899c440d1fcff16b72faa8b95abe8f9449836`.

새 SVG는 **뉴스 영상 보관(`/videos`)의 빈 목록 한 곳**에만 적용했다.
변경 전의 텍스트·점선 패널에 비해 뉴스 → 세로 영상 → 음성이라는 용도를 알아보기 쉽고,
데스크톱의 빈 공간을 활용한다. 모바일에서는 설명과 제작 버튼이 이미지보다 먼저 나온다.
실제 영상이 생기면 이 패널과 이미지는 렌더링되지 않는다.
새 메뉴·기능·추가 설명·가짜 뉴스·성과 수치를 만들지 않았다.

Cloud의 이전 `d4dc20f`와 원격 PR은 후속 개발로 이력이 갈라져 있었다.
기존 Cloud 이력은 로컬 `archive/cloud-d4dc20f-before-design-20261024`에 보존하고,
요청한 브랜치를 최신 원격 HEAD에서 이어갔다. 병합·커밋 재작성·force push 없음.
이전 Cloud 기능을 원격에 다시 덮어씌우지 않았다.

## 자산 비교 및 변경 범위

- 기존 지구 배너, `news-topic-atlas.png`, 뉴스 지도, AI 대본의 `script-workflow.svg`,
  영상 구성의 `video-canvas.svg`는 해당 용도대로 유지한다. 대시보드/대본/편집 화면은 바꾸지 않았다.
- 전달된 `newsflow-storyflow-illustration.svg` 원본은 **5,057 bytes**, 수정 없음.
  스크립트·외부 리소스·이벤트 속성·애니메이션 없음. PNG 시안은 수신하거나 적용하지 않았다.
- 변경한 실행 파일은 `gui/templates/video_library.html`, `static/css/premium.css` 두 개.
- 제목·본문·`/create` 링크는 기존 HTML 그대로 유지한다. 이미지는 `alt=""`, `aria-hidden="true"`,
  `pointer-events:none`; 버튼이나 플레이어 역할을 하지 않는다.
- `object-fit:contain`과 고유 크기로 비율 유지. 데스크톱 최대 440px / 모바일 최대 240px.
  기존 전역 디자인을 바꾸지 않고 `.library-empty` 안에서만 스타일을 적용했다.

## 전후 화면

아래는 전체 페이지 축소가 아닌 실제 뷰포트 캡처다. 비어 있는 임시 DB와 합성 기록만 사용했다.

| 화면 크기 | 변경 전 (`c988fa2`) | 변경 후 (`cf1899c`) |
|---|---|---|
| 1366×768 | [이전](evidence/storyflow-library/before/empty-1366.png) | [최종](evidence/storyflow-library/after/empty-1366.png) |
| 1920×1080 | [이전](evidence/storyflow-library/before/empty-1920.png) | [최종](evidence/storyflow-library/after/empty-1920.png) |
| 390×844 | [이전](evidence/storyflow-library/before/empty-390.png) | [최종](evidence/storyflow-library/after/empty-390.png) |
| 제작물 있는 목록 1366×768 | [이전](evidence/storyflow-library/before/populated-1366.png) | [최종](evidence/storyflow-library/after/populated-1366.png) |

[모바일 키보드 포커스](evidence/storyflow-library/after/empty-390-focus.png) ·
[파일 해시 및 촬영 기준](evidence/storyflow-library/manifest.json).
합성 제작물은 UI 검사용 바이트이며 이번 검증은 MP4 생성·재생 검증이 아니다.

## 검증 결과

환경: **Cloud Linux, Python 3.12.14, Chromium 151.0.7922.173**.

| 항목 | 결과 | 근거 |
|---|---|---|
| 적용 전 브라우저 기준 | PASS | 2 passed / 0 failed / 0 skipped / 1 warning |
| 최종 브라우저 검증 | PASS | 2 passed / 0 failed / 0 skipped / 1 warning |
| 관련 기존 회귀 | PASS | 19 passed / 0 failed / 0 skipped / 1 warning |
| 가로 넘침·이미지 로딩·비율 | PASS | 세 뷰포트, 빈 목록 및 합성 제작물 있는 목록 |
| 키보드 사용 | PASS | 첫 영상 만들기 포커스, Shift+Tab/Tab 복귀, Enter로 기존 제작 폼 진입 |
| 색상 대비 | PASS (검사 영역 한정) | 제목 17.03:1, 본문 10.45:1, 버튼 5.06:1, 포커스/패널 10.02:1 |
| 데이터·외부 요청 | PASS | 각 브라우저 감사 전후 임시 DB bytes 동일, 외부 요청 0 / POST 0 / JS 오류 0 |
| Ruff / pip check / diff check | PASS | 관련 Python 검사, 의존성 호환, 공백 검사 |
| Windows 3.12/3.14 Actions | NOT VERIFIED / 미실행 | 표현만 변경. 댓글의 기능 영향 시 실행 기준에 따라 새 Windows CI 불필요 판정 |
| 사용자 Windows PC·배율·음질 | NOT VERIFIED | 접근·실행하지 않음 |

각 테스트의 경고 1건은 기존 FastAPI TestClient의 httpx 사용 중단 예정 경고다.
전체 회귀는 재실행하지 않았으며 기존 **57 FAIL 기록을 PASS로 변경하지 않는다.**
최종 범위 결과는 합계 **21 PASS**이며 제품 전체 또는 사람의 사용성 평가 통과를 뜻하지 않는다.
기존 영상/소스 보존, 삭제·복원 및 게시 연관 영상 삭제 차단, 최종 정보 모달도 관련 회귀로 확인했다.

## 재현 명령과 로그

프로젝트 폴더에서 기존 개발 의존성과 Playwright/Chromium을 사용한다.
감사 스크립트는 임시 DB만 생성하며 실제 API 키를 요구하지 않는다.

```bash
PYTHONPATH=tests NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
STORYFLOW_PHASE=after STORYFLOW_EVIDENCE=/tmp/newsflow-storyflow-evidence \
.venv/bin/python -m pytest -q -rs docs/reports/evidence/storyflow-library/test_storyflow_review.py

NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs \
 tests/test_creator_ui.py::test_navigation_and_read_only_views_preserve_settings_and_security \
 tests/test_creator_ui.py::test_library_loads_thumbnails_instead_of_all_media \
 tests/test_studio_pages.py::test_suite_empty_routes_and_security \
 tests/test_workspace_cleanup.py::test_video_delete_and_restore_preserve_bytes_and_sources \
 tests/test_workspace_cleanup.py::test_publish_link_blocks_video_removal \
 tests/test_workspace_cleanup.py::test_restore_rejects_tampered_mp4 \
 tests/test_video_review_dialog.py
```

[적용 전 로그](evidence/storyflow-library/before.log) ·
[최종 브라우저 로그](evidence/storyflow-library/after.log) ·
[기존 회귀 로그](evidence/storyflow-library/regression.log) ·
[최종 UI 감사](evidence/storyflow-library/after/empty-audit.json) ·
[대비·SVG 검사](evidence/storyflow-library/after/contrast-and-svg.json).

## 보존 및 종료

DB migration, API 계약, 뉴스·대본·음성·영상·게시 엔진, 승인·비용 정책 변경 없음.
운영 데이터·키·기존 MP4 접근/변경, 운영 앱 재시작, 유료 API·OAuth·SNS 호출 **0건**.
실행 코드와 증거는 기존 PR #35 브랜치에 보존하고 Draft 유지.
표현 변경/보고 커밋에 `[skip ci]` 사용; 기능과 무관한 전체 Windows 회귀를 재실행하지 않는다.
main/다른 PR 변경·병합·운영 배포 없이 검토를 기다린다.
