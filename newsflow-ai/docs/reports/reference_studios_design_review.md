# NewsFlowAI — 참고 이미지 기반 6개 작업 화면

- 보고 시각: 2026-10-19 16:21 KST
- 작업 기준: `60cc77b` / `codex/newsflow-ux-video-app`
- 검증 코드: `0fc1a12149dccd4566dc59788c5c64a2099570c0`
- 환경: Codex Cloud Linux, Python 3.12.14, Chromium 151. 최종 운영 대상은 Windows 11 그대로 유지.
- 범위: 승인된 대시보드는 보존하고, 첨부한 6패널 참고 이미지에 맞춰 기존 작업 화면을 재배치. 원격 push·PR 변경·병합·운영 반영 없음.

## 구현 및 실제 기능 연결

| 화면 | 변경 | 연결된 기존 기능 |
|---|---|---|
| 뉴스 수집 | 분야 칩, 출처 바로가기, 밀도 높은 기사 목록, 지구 브랜드 이미지, 등록/활성 출처 수 | 기존 보관 기사 GET 검색·필터, 출처/수집 관리, 기사 분석 진입. 실시간 수집·트렌드 수치를 만들어 표시하지 않음 |
| AI 대본 | 5단계 작업 순서, 자료·분석·저장 대본 3열, 선택한 대본의 원문/요약·편집기·미리보기 3열 | 기존 분석/생성 POST, revision 기반 대본 저장, 장면 선택·순서 변경, 근거·출처·검토 정책 |
| 영상 제작 | 소재/장면 패널, 가로형 모니터 안의 원래 9:16 영상, 장면 타임라인, 음성·내보내기 패널 | 기존 `/video/render`, 음성/자막/로컬 이미지 선택, 외부 음성 동의·대본 검토, 기존 MP4 저장 |
| 게시 허브 | YouTube/Instagram 카드, 초안 행 목록, 게시 전 검토 패널 | 기존 계정 관리, 통합 게시 준비, 초안 기록, 다운로드. 게시 승인 조건 유지 |
| 제작 활동 | 주간 라인/영역 그래프, 제작 건수 막대, 상태별 작업 목록 | 승인된 대시보드의 읽기 전용 KST 집계 재사용. 실제 저장된 수집/완료/초안 등록 기록이며 SNS 성과 통계가 아님 |
| 설정·자동화 | 가로 항목 메뉴, 2열 카드, 이동한 설정 항목 강조 | 기존 단일 기본값 저장, 개별 키/비용 승인, 계정/예약/운영 관리. 새 설정 저장 체계 없음 |

공통으로 차콜·네이비 패널, 얇은 파란 테두리, 번호형 제목, 선형 아이콘, 파란 주요 버튼, 기존 지구 이미지를 사용했습니다. 참고 이미지의 배치를 기존 기능에 맞춰 구현했으며, 이미지 자체를 버튼 위에 덮은 화면이 아닙니다.

영상 타임라인의 세 줄은 **대본에 저장된 영상 장면·자막·음성 대본**입니다. 클릭하면 실제 장면/로컬 소재 선택이 바뀝니다. 렌더링된 음성 파형이나 효과 편집기로 표시하지 않습니다. 이전 MP4와 편집 중 대본은 구분하며, 새 설정을 반영하려면 별도 제작이 필요합니다. 실패·미완료·파일 없는 작업에는 이전 영상 플레이어를 표시하지 않습니다.

TikTok/Facebook, AI 게시 시각/성능 예측, 수익·구독자·지역별 분석, 효과 트랙, 지원되지 않는 톤/청중/언어 설정은 새로 구현하거나 연결된 기능처럼 표시하지 않았습니다. 기존 뉴스·대본·음성·렌더링·인증·게시 엔진과 HTTP 입력 계약은 유지합니다.

## 화면 증거

실제 Cloud 브라우저 캡처입니다. 기본/키 미등록 설정, 합성 기사·대본, 30초 1080×1920 무음 MP4, 승인되지 않은 합성 게시 초안을 사용했습니다. 운영 데이터·키를 사용하지 않았습니다.

| 화면 | 1920×1080 | 1366×768 | 390×844 |
|---|---|---|---|
| 뉴스 | [보기](evidence/reference-studios/news-1920.png) | [보기](evidence/reference-studios/news-1366.png) | [보기](evidence/reference-studios/news-390.png) |
| 대본 편집 | [보기](evidence/reference-studios/editor-1920.png) | [보기](evidence/reference-studios/editor-1366.png) | [보기](evidence/reference-studios/editor-390.png) |
| 영상 구성 | [보기](evidence/reference-studios/video-1920.png) | [보기](evidence/reference-studios/video-1366.png) | [보기](evidence/reference-studios/video-390.png) |
| 게시 허브 | [보기](evidence/reference-studios/publish-1920.png) | [보기](evidence/reference-studios/publish-1366.png) | [보기](evidence/reference-studios/publish-390.png) |
| 제작 활동 | [보기](evidence/reference-studios/activity-1920.png) | [보기](evidence/reference-studios/activity-1366.png) | [보기](evidence/reference-studios/activity-390.png) |
| 설정 | [보기](evidence/reference-studios/settings-1920.png) | [보기](evidence/reference-studios/settings-1366.png) | [보기](evidence/reference-studios/settings-390.png) |

추가: [기사 선택·분석 시작](evidence/reference-studios/script-1920.png), [내 영상](evidence/reference-studios/library-1920.png), [예약 제작](evidence/reference-studios/schedule-1920.png).

변경 전 증거는 기존 [6화면 보고서](studio_pages_design_review.md) 및 [뉴스](evidence/studio-pages/news-1366.png), [대본 편집](evidence/studio-pages/editor-1366.png), [게시](evidence/studio-pages/publish-1366.png), [활동](evidence/studio-pages/activity-1366.png), [설정](evidence/studio-pages/settings-1366.png)에 보존되어 있습니다. 이전 영상 캡처는 `/videos` 보관함으로, 이번 `/video?draft_id=1` 작업실과 동일 화면의 비교 자료는 아닙니다.

## 검증

최종 결과는 아래 실행 로그 및 브라우저 관찰 파일을 기준으로 기록합니다.

- Cloud 관련 회귀: **109 passed / 0 failed / 0 skipped / 1 warning**, 129.82초. [실행 로그](evidence/reference-studios/pytest.log) · [JUnit](evidence/reference-studios/pytest.xml). 경고는 기존 Starlette/httpx 사용 중단 안내입니다.
- Ruff(변경 Python 3개): PASS. [로그](evidence/reference-studios/ruff.log)
- pip check: PASS. [로그](evidence/reference-studios/pip-check.log)
- 실제 브라우저: 9개 화면 × 3개 크기 = **27/27** HTTP 200, 문서 가로 넘침/오른쪽 이탈 입력·버튼 0, JavaScript 오류 0, 외부 요청 0. [관찰 결과](evidence/reference-studios/audit.json)
- 합성 MP4: 기존 격리 fixture의 FFmpeg 무음 영상을 실제 Chromium에서 재생·일시정지. 영상 구성 화면에서 1080×1920 디코딩 확인. 사람의 음질·완성 콘텐츠 평가가 아님.
- 사용자 흐름: 분야 클릭→실제 저장 기사 필터링, 키보드 타임라인→장면/소재 선택, 숨긴 장면의 입력도 기존 렌더 폼에 보존, 대본 장면 선택, 작업 상태/날짜 그래프 조회, 설정 저장→재진입·모델/비용 대화상자 포커스, Fake API→영상→게시 준비, 기존 통합 게시 승인 보호를 관련 테스트로 확인.
- 읽기/보기 조작은 POST 또는 외부 호출을 만들지 않음. 설정/대본 저장·제작은 기존 CSRF·동의·검토 계약으로만 실행.

개발 중 발견한 모바일 영상 패널 넘침, 세로 미디어가 가로 모니터의 높이를 넘어 잘리는 문제를 수정했습니다. 확대 회귀의 첫 실행은 빈 미리보기 안내 문구 변경 때문에 3 failed / 106 passed였고, 기존 안내 문구를 복원했습니다. 최종 실행 결과는 위와 로그에 별도로 기록합니다. 실패 테스트를 삭제하거나 skip하지 않았습니다.

검증 명령:

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs \
 tests/test_single_workspace.py tests/test_creator_ui.py tests/test_settings_simplification.py \
 tests/test_sources_gui.py tests/test_scheduler_gui.py tests/test_studio_pages.py \
 tests/test_settings_streamlined_browser.py tests/test_creator_scene_browser.py \
 tests/test_gui.py::test_add_toggle_collect_filters_detail tests/test_blue_studio_browser.py \
 tests/test_workflow_card.py tests/test_dashboard_view.py tests/test_cloud_workspace_flow.py \
 tests/test_unified_publishing_gui.py --junitxml=/tmp/workstation-verified.xml
```

## 보존 및 검증 한계

- 기존 전체 회귀 **57 FAIL** 기록 유지. 이번에는 변경 범위 테스트만 실행했으며 전체 PASS를 주장하지 않습니다.
- 실제 유료 AI/RSS/OAuth/SNS 호출 0건. 테스트는 Fake 및 격리된 합성 데이터만 사용했습니다.
- 기존 DB/migration/키/저장 설정/과거 작업/운영 MP4와 운영 앱은 변경하지 않았습니다.
- Windows 사용자 PC, Windows Python 3.12/3.14 및 화면 배율, 실제 한국어 음성/자막 싱크/공급사 품질/SNS 게시: **NOT VERIFIED**. 이번 작업에서 원격 변경이나 Actions 실행 없음.
- 디자인 유사성은 위 실제 화면으로 검토할 수 있습니다. 첨부 목업의 가상 인물·언론사 사진·없는 서비스 지표를 앱의 실제 자료로 만들지 않았습니다.
- PR #35 및 원격 상태는 변경하지 않았습니다. 로컬 코드 커밋과 이 보고서/증거만 보존합니다.
