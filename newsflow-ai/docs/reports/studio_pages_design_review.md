# NewsFlowAI — 여섯 제작 화면 디자인 통일

2026-10-19 KST. 기준 `1a45737`, 로컬 브랜치 `codex/newsflow-ux-video-app`.
검증 코드: `e3a858edd8a4bb5bcd5e9b123e938de00e1e4c1e`.

기존 대시보드의 네이비·블루·시안, 선형 아이콘, 카드 테두리와 여백을 뉴스 수집 / AI 대본 / 영상 제작 / 게시 허브 / 제작 활동 / 설정·자동화에 적용했다. 기존 엔진·저장 구조·승인 체계는 재사용한다.

## 화면별 변경

| 화면 | 구현 내용 | 연결된 기존 기능 |
|---|---|---|
| 뉴스 수집 | 검색·정렬과 접힌 출처·기간 필터, 주제 이미지 기사 목록, RSS 출처 영역 | `/news` 검색 계약, 기사 상세, `/sources` 등록·수집, `/ai` |
| AI 대본 | 단계 안내, 기사 선택 영역과 저장된 대본 목록, 영상 미리보기·장면 편집 스타일 | 분석·대본 폼과 동의, 기존 장면 편집·저장·검토 |
| 영상 제작 | 세로 썸네일 라이브러리, 상태·편집·게시 준비·파일 저장 액션 | 실제 로컬 MP4/thumbnail 라우트, 기존 `/video` 구성 |
| 게시 허브 | YouTube/Instagram 준비 영역, 초안·검토 체크와 MP4만 저장 경로 | 계정 관리·기존 게시 화면·검토 기록. 연결 성공을 임의로 표시하지 않음 |
| 제작 활동 | 독립적인 전체 기록 화면, 검토 대기·확인 필요·완료 필터 | 기존 `/?show=tasks`의 최대 100개 작업. 서버 재실행 없는 클라이언트 필터 |
| 설정·자동화 | 단일 항목 목차, 기본 AI·음성·영상·비용·계정 관리, 예약 화면 통일 | 기존 설정 저장·키 dialog·비용 승인·예약 CRUD |

제작 활동의 메뉴를 홈 그래프 앵커에서 기존 전체 작업 기록 경로로 연결했다. 새 API/스케줄러/통계 엔진을 만들지 않았다. `show=tasks`와 특정 작업·영상 선택이 함께 주어지면 기존 작업 상세 화면이 우선한다.

설정의 기존 가로 이동 메뉴와 새 목차가 중복되는 것을 제거했다. 모바일에서는 메뉴에서 모든 영역으로 이동할 수 있다. 키 입력·실제 연결 확인·비용 동의는 기존 구조를 유지하며 설정 저장을 실행 승인으로 취급하지 않는다. 제목이 긴 영상은 3줄로 표시하되 전체 텍스트와 상세 링크를 유지한다.

## 화면 증거

실제 Cloud Chromium 캡처다. 편집 화면은 격리 MP4를 명시적으로 재생·일시정지한 뒤 캡처했다. 격리된 합성 기사·대본·무음 MP4를 사용했다. 주제 이미지는 이전 디자인 작업의 로컬 자산을 재사용하며 실제 보도 사진이 아니라고 화면에 표시한다. 공급사 API나 사람의 콘텐츠 품질 검증 자료가 아니다.

| 화면 | 데스크톱 1366×768 | 모바일 390×844 |
|---|---|---|
| 뉴스 수집 | [열기](evidence/studio-pages/news-1366.png) | [열기](evidence/studio-pages/news-390.png) |
| AI 대본 | [열기](evidence/studio-pages/script-1366.png) | [열기](evidence/studio-pages/script-390.png) |
| 영상 제작 | [열기](evidence/studio-pages/video-1366.png) | [열기](evidence/studio-pages/video-390.png) |
| 게시 허브 | [열기](evidence/studio-pages/publish-1366.png) | [열기](evidence/studio-pages/publish-390.png) |
| 제작 활동 | [열기](evidence/studio-pages/activity-1366.png) | [열기](evidence/studio-pages/activity-390.png) |
| 설정·자동화 | [열기](evidence/studio-pages/settings-1366.png) | [열기](evidence/studio-pages/settings-390.png) |

[뉴스 1920×1080](evidence/studio-pages/news-1920.png) · [설정 1920×1080](evidence/studio-pages/settings-1920.png) · [대본 편집](evidence/studio-pages/editor-1366.png) · [예약 제작](evidence/studio-pages/schedule-1366.png).

이전 설정 화면은 [이전 검증 자료](evidence/dashboard-implementation/settings-1366.png)에 보존되어 있다. 승인된 홈 카드의 구조와 자산은 변경하지 않았다.

## 검증 범위

**최종 코드 `e3a858e`: 104 passed / 0 failed / 0 skipped / 1 warning.** [pytest 로그](evidence/studio-pages/pytest.log) · [JUnit](evidence/studio-pages/pytest.xml) · [Ruff](evidence/studio-pages/ruff.log) · [pip check](evidence/studio-pages/pip-check.log).

Cloud Linux / Python 3.12.14 / Chromium 151. 변경 Python 범위 Ruff와 pip check 통과. 기존 Starlette/httpx deprecation warning은 남아 있다. 8개 화면 × 3크기(1366×768, 1920×1080, 390×844) = 24개 조합에서 HTTP 200, 가로 넘침·페이지 밖 입력/버튼·JS 오류·외부 브라우저 요청 없음. [측정 기록](evidence/studio-pages/audit.json).

기능 검증: 빈 화면, 긴 한글, 기존 기사 검색·분류·날짜·출처, 자료 선택, 설정 저장 후 재진입, 모델/키 비노출, 대본·장면 편집, 영상 재생, 제작 활동 키보드 상태 필터·빈 결과·작업 이동, 실패/검토 기록 보존, Fake 게시 회귀를 수행한다. 제작 활동을 눌러도 작업 상태·승인이 바뀌지 않는 것을 확인한다.

초기 범위 테스트의 1건 실패는 제작 활동 메뉴를 새로 연결한 URL과 이전 기대값 차이였다. 기대값을 의도한 경로로 갱신하고 전체 기록 화면·단일 활성 메뉴·읽기 전용 동작을 추가 검증했다. 테스트 삭제나 skip은 하지 않았다.

확장한 통합 실행 1회에서는 OpenAI Fake 경로의 게시 준비 이동 시 `net::ERR_ABORTED`가 발생했다. 서버 완료를 기다린 뒤에도 폼의 브라우저 redirect/reload가 진행 중일 수 있어 직접 `goto`와 경합하는 지점이었다. 완료된 작업 DOM 상태를 먼저 기다리는 assertion을 추가했다. POST 재전송·오류 무시·skip은 추가하지 않았다. 이것을 기준 코드에서 확인된 기존 실패라고 분류하지 않는다.

## 제한과 보존

- 실제 유료 API·RSS 외부 수집·OAuth·SNS 호출 0건. 앱에 등록된 공급사 엔진을 수정하지 않았다.
- 실제 사용자 데이터·키·설정·MP4·운영 앱은 건드리지 않았다. 임시 디렉터리에서 자체 테스트 서버만 실행했다.
- 원격 push, PR #35 본문·상태 변경, 새 PR, main/다른 브랜치 병합 없음.
- Windows 11 사용자 PC / Python 3.14 / 실제 음질·API 콘텐츠 품질·실계정 게시 / Windows 배율은 **NOT VERIFIED**. 새로운 Windows Actions 실행 없음.
- 기존 전체 회귀 **57 FAIL** 기록 유지. 이번 변경 범위 결과를 전체 PASS로 확대하지 않는다.

## 재현 명령

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs tests/test_single_workspace.py tests/test_creator_ui.py tests/test_settings_simplification.py tests/test_sources_gui.py tests/test_scheduler_gui.py tests/test_studio_pages.py tests/test_settings_streamlined_browser.py tests/test_creator_scene_browser.py tests/test_gui.py::test_add_toggle_collect_filters_detail tests/test_blue_studio_browser.py tests/test_workflow_card.py tests/test_dashboard_view.py tests/test_cloud_workspace_flow.py tests/test_unified_publishing_gui.py
```

스크린샷은 이전에 보존한 `docs/reports/evidence/dashboard-implementation/preview_fixture.py`를 새로운 `/tmp` 디렉터리에서 실행한 뒤 캡처했다. 해당 도구의 외부 네트워크·인증·게시 차단을 재사용한다.
