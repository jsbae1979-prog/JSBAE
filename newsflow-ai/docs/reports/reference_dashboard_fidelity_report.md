# 참고 이미지 기반 화면 구성 적용

- 기록: 2026-10-19 KST
- 시작 HEAD: `93d41caa18ed2e9824d8b13c3cede22a7eb803d4` (clean)
- 검증 코드: `f7a25a2d1e8721864b003a873d6c7eafb5e17d78`
- 브랜치: `codex/newsflow-ux-video-app`. 로컬 커밋만 생성. 원격 push·PR #35 수정·병합·운영 반영 없음.

## 적용 범위

참고 이미지의 네이비 사이드바, 검색 진입 영역, 파란 지구 배너, 4개 요약 카드와 3열 구성을 기존 작업실에 적용했다. 뉴스 목록 / 제작 설정·순서 / 세로 미리보기 순서다. 모바일에서는 제작 설정을 먼저 보여 준다. 배너의 제작 시작 버튼은 같은 화면의 기존 제작 폼으로 이동한다.

- `base.html`: 기존 5개 메뉴를 유지하고 사이드바 장식을 추가.
- `easy_home.html`: 기존 `recent_news`, `active_task_count`, `video_count`, `queue_count`, `task_count`를 표시. 신규 조회 API 없음.
- `creator.css`: 배너·카드·3열 및 좁은 화면 재배치.
- `static/images/newsflow-earth.svg`: 직접 작성한 장식용 벡터 지구. 외부 리소스·이미지 API·기사 사진 다운로드 없음. 정밀 지도가 아님.
- `test_blue_studio_browser.py`: 빈/합성 기록의 실제 표시, 시작 앵커, 기존 선택·승인·편집·재생 경계 검증 보강.

참고 그림의 조회수·상승률·트렌드·가짜 업로드 성공·진행률은 복제하지 않았다. 요약 카드는 **진행·확인할 작업, 제작된 영상, 게시 초안, 전체 작업 기록**이다. 게시 초안 개수는 게시 성공 횟수가 아니다. 뉴스는 최근 보관 기록이며 최신 발행 기사라고 단정하지 않는다. 기사 사진 대신 장식 아이콘을 사용한다. 미리보기는 실제 검증된 영상의 9:16 썸네일과 기존 플레이어 연결을 사용한다.

폼 action/필드, CSRF, 설정 저장 구조, 작업별 선택 고정, 서비스별 외부 전송·유료 승인, AI 장면 검토, 영상 검토 및 게시 승인은 유지했다. 백엔드·DB·마이그레이션·엔진·의존성 변경 없음.

## 화면 증거

모두 **Cloud Chromium / 합성 DB·뉴스 / 무음 MP4 / 실연결 차단** 상태다. 운영 데이터와 사용자 키는 사용하지 않았다. 그림의 시각적 유사성과 사람의 사용성 평가를 정량 PASS로 주장하지 않는다.

| 화면 | 증거 |
|---|---|
| 변경 전 홈 · 1366×768 | [이전 화면](evidence/blue-studio/home-1366.png) |
| 변경 후 홈 · 1366×768 | [현재 화면](evidence/reference-dashboard/home-1366.png) |
| 변경 후 홈 · 1920×1080 | [현재 화면](evidence/reference-dashboard/home-1920.png) |
| 모바일 홈 · 390×844 | [현재 화면](evidence/reference-dashboard/home-390.png) |
| 모바일 제작 영역 · 390×844 | [현재 화면](evidence/reference-dashboard/home-mobile-production.png) |
| 제작 · 1366×768 | [현재 화면](evidence/reference-dashboard/create-1366.png) |
| 설정 · 1366×768 | [현재 화면](evidence/reference-dashboard/settings-1366.png) |

이전/현재 캡처는 격리된 합성 데이터의 설정값이 일부 달라 순수 픽셀 차이 비교 자료는 아니다. 모바일 캡처는 브라우저 뷰포트이며 Windows 화면 배율 검증이 아니다.

## 최종 코드 검증

Cloud Python 3.12, 설치된 `/usr/bin/chromium`을 사용했다.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_BLUE_STUDIO_EVIDENCE=/tmp/newsflow-reference/final-browser \
NEWSFLOW_VALIDATION_OUTPUT=/tmp/newsflow-reference/flow \
.venv/bin/python -m pytest -q -rs \
 tests/test_blue_studio_browser.py tests/test_single_workspace.py \
 tests/test_production_choices.py tests/test_settings_simplification.py \
 tests/test_creator_ui.py tests/test_all_scene_browser.py \
 tests/test_all_scene_safety.py tests/test_production_options_browser.py \
 tests/test_settings_streamlined_browser.py tests/test_cloud_workspace_flow.py \
 tests/test_creator_scene_browser.py \
 --junitxml=/tmp/newsflow-reference/scoped.xml
```

**PASS: 130 passed / 0 failed / 0 errors / 0 skipped**, 209.72초. Starlette/httpx 기존 deprecation 경고 1건.

- 기존 Fake API 분석·대본 → 검토 → 로컬 합성·재생 → Fake 게시 동선, 제작 선택·승인, 설정, 전체 AI 장면 보호, 장면 순서/선택·편집 테스트 포함.
- 빈 상태 및 합성 기록 상태에서 1366×768 / 1920×1080 / 390×844 실제 브라우저 동선 확인. 추가 홈·제작·설정 9개 GET 조합 HTTP 200, 가로 넘침 없음. [별도 레이아웃 기록](evidence/reference-dashboard/layout.json).
- 외부 브라우저 요청 차단, 서버 Fake/외부 호출 차단 유지. 실제 유료 공급사·계정 조회·OAuth·SNS 호출 0건.
- 변경 테스트 Ruff, `pip check`, `git diff --check`: PASS. pip cache 쓰기 권한 안내 1건, 의존성 오류 없음.
- [pytest 원본](evidence/reference-dashboard/scoped.log), [JUnit](evidence/reference-dashboard/scoped.xml), [SHA/파일 해시](evidence/reference-dashboard/manifest.json).

초기 실행에서 Chrome 기본 경로가 없어 브라우저 setup 4 errors가 발생했다. 설치된 Chromium을 명시해 해결했다. 이어 이전 테스트의 문자열 `wait_for_function`이 CSP의 eval 금지에 걸려 3 passed / 1 failed였다. 두 대기식을 함수 표현식으로 수정했으며 CSP나 브라우저 보안 설정은 완화하지 않았다. 최종 위 130개 테스트는 수정된 정확한 코드에서 통과했다.

## 판정 범위와 남은 항목

이번 결과는 변경 범위 검증이다. **기존 전체 회귀 57 FAIL 기록은 유지**하며, 전체 pytest/동일 기준 재비교를 반복하지 않았다. 앞선 UI 범위의 `test_workspace_two_destinations_and_two_production_choices` 기존 실패도 수정·삭제·skip하지 않았으며 이번 실행 대상에 포함하지 않았다. 범위 테스트 통과를 전체 PASS나 전체 신규 실패 비교 완료로 확대하지 않는다.

Windows PC·Windows Python 3.12/3.14·BAT·배율·SAPI 음질·실제 API 콘텐츠 품질·OAuth·SNS 실게시: **NOT VERIFIED**. 이번에 Windows Actions를 실행하지 않았다. 무음 MP4 성공은 합성·재생 검증에 한정한다.

실사용 환경, DB·키·설정·기존 MP4에 접근/변경하거나 운영 앱을 재시작하지 않았다. 테스트용 서버만 종료한다. 별도 개발·실호출·원격 반영 없이 이 작업을 종료한다.
