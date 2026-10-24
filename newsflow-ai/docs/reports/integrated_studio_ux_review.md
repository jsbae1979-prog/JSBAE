# NewsFlow AI 통합 UX/UI 검토

## 결과와 범위

뉴스 기반 쇼츠 제작 흐름을 중심으로 기존 화면의 표현과 탐색 구조를 통합했다. 엔진·API 경로·DB·마이그레이션·자격증명·영상·승인 데이터는 변경하지 않았다. 기존 기능은 삭제하지 않았다.

- 기준: `727cc14cbe681ac13f36c98fc101379ed55b99db`
- 검증 코드: `defcf6caabab202bb684f3569102a336bc983efa`
- 브랜치: `codex/newsflow-ux-video-app`
- [기존 PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35): Draft 유지. main·다른 PR 변경 없음.
- 이 보고서와 증거는 코드 커밋 다음의 자료 전용 커밋에 보존한다. 최종 자료 SHA는 PR 결과 댓글에 기록한다.

## 변경 내용

1. 공통 색상·간격·글자 크기·모서리·카드·입력·버튼·포커스·오류 표현을 `studio-system.css`로 통합했다. 기존 페이지 CSS는 편집기 구조와 표시/숨김을 계속 담당한다.
2. 기본 메뉴를 홈 / 쇼츠 만들기 / 뉴스 선택 / 작업 현황 / 내 영상 / 게시 / 설정으로 정리했다. 기존 13개 목적지 모두 유지하며 부가 제작·대본·음성·분석·예약 6개는 **도구·자동화**에서 접근한다.
3. 제작 관련 화면에 뉴스 선택 → 대본 검토 → 음성 선택 → 영상 제작 → 최종 검토 → 게시의 실제 링크를 제공한다. 이는 **단계별 화면 이동**이며 완료 상태나 진행률을 추정하지 않는다. 최종 영상의 대본 ID와 게시 화면 맥락을 유지한다. 실제 작업 상태 표시는 기존 데이터에 따른다.
4. 홈의 중복 영상 링크 구역을 미리보기 헤더에 통합하고 제작 활동 차트는 접었다. 기존 `#workspace-videos` 링크를 미리보기 구역에 보존했다. 제작 화면의 중복 제목과 설정 첫 화면의 중복 기본값 요약을 제거했다.
5. 준비 상태 버튼은 설정 헤더에 유지했다. 영상 세부 기본값이 모든 설정 탭에 노출되던 배치를 영상 탭 안으로 옮겼다. 기존 필드·저장·연결·승인 기능은 그대로다.
6. 빈 게시 달력의 반복 구역을 제거하고 오류 복구 버튼 간격을 확보했다. 검색 연결 화면의 DPAPI 구현 설명을 간결한 보관 안내로 바꿨다. 비용·외부 전송·권리·게시 승인 설명은 유지했다.
7. 기존 지구 배경은 대비를 낮추고 Storyflow SVG는 빈 영상 보관함에만 유지했다. 새 이미지·엔진·설정 체계를 추가하지 않았다. 모든 버튼·입력·상태는 HTML이다.

## 전후 화면

모두 Cloud Chromium의 실제 뷰포트 캡처다. 합성 데이터와 Fake 공급사만 사용했다. 1920px의 이전 화면도 같은 `before` 폴더에 있다. 오류 후 화면은 복구 안내를 볼 수 있도록 해당 위치로 스크롤했다. 최종 앵커 ID 보존 변경은 외형을 바꾸지 않으며 별도 10개 테스트로 확인했다.

| 화면 | 1366×768 | 1920×1080 | 390×844 |
|---|---|---|---|
| 홈 | [전](evidence/integrated-studio/before/home-1366.png) · [후](evidence/integrated-studio/after/home-1366.png) | [후](evidence/integrated-studio/after/home-1920.png) | [전](evidence/integrated-studio/before/home-390.png) · [후](evidence/integrated-studio/after/home-390.png) |
| 제작 | [전](evidence/integrated-studio/before/create-1366.png) · [후](evidence/integrated-studio/after/create-1366.png) | [후](evidence/integrated-studio/after/create-1920.png) | [전](evidence/integrated-studio/before/create-390.png) · [후](evidence/integrated-studio/after/create-390.png) |
| 작업 현황 | [전](evidence/integrated-studio/before/tasks-1366.png) · [후](evidence/integrated-studio/after/tasks-1366.png) | [후](evidence/integrated-studio/after/tasks-1920.png) | [전](evidence/integrated-studio/before/tasks-390.png) · [후](evidence/integrated-studio/after/tasks-390.png) |
| 대본 | [전](evidence/integrated-studio/before/script-1366.png) · [후](evidence/integrated-studio/after/script-1366.png) | [후](evidence/integrated-studio/after/script-1920.png) | [전](evidence/integrated-studio/before/script-390.png) · [후](evidence/integrated-studio/after/script-390.png) |
| 영상 구성 | [전](evidence/integrated-studio/before/video-1366.png) · [후](evidence/integrated-studio/after/video-1366.png) | [후](evidence/integrated-studio/after/video-1920.png) | [전](evidence/integrated-studio/before/video-390.png) · [후](evidence/integrated-studio/after/video-390.png) |
| 내 영상 | [전](evidence/integrated-studio/before/library-1366.png) · [후](evidence/integrated-studio/after/library-1366.png) | [후](evidence/integrated-studio/after/library-1920.png) | [전](evidence/integrated-studio/before/library-390.png) · [후](evidence/integrated-studio/after/library-390.png) |
| 설정 | [전](evidence/integrated-studio/before/settings-1366.png) · [후](evidence/integrated-studio/after/settings-1366.png) | [후](evidence/integrated-studio/after/settings-1920.png) | [전](evidence/integrated-studio/before/settings-390.png) · [후](evidence/integrated-studio/after/settings-390.png) |
| 최종 검토·게시 | [전](evidence/integrated-studio/before/publish-1366.png) · [후](evidence/integrated-studio/after/publish-1366.png) | [후](evidence/integrated-studio/after/publish-1920.png) | [전](evidence/integrated-studio/before/publish-390.png) · [후](evidence/integrated-studio/after/publish-390.png) |
| 게시 대기함 | [전](evidence/integrated-studio/before/queue-1366.png) · [후](evidence/integrated-studio/after/queue-1366.png) | [후](evidence/integrated-studio/after/queue-1920.png) | [전](evidence/integrated-studio/before/queue-390.png) · [후](evidence/integrated-studio/after/queue-390.png) |
| 실패 안내 | [전](evidence/integrated-studio/before/error-1366.png) · [후](evidence/integrated-studio/after/error-1366.png) | [후](evidence/integrated-studio/after/error-1920.png) | [전](evidence/integrated-studio/before/error-390.png) · [후](evidence/integrated-studio/after/error-390.png) |
| 운영 관리 | [전](evidence/integrated-studio/before/operations-1366.png) · [후](evidence/integrated-studio/after/operations-1366.png) | [후](evidence/integrated-studio/after/operations-1920.png) | [전](evidence/integrated-studio/before/operations-390.png) · [후](evidence/integrated-studio/after/operations-390.png) |

- 빈 보관함: [데스크톱](evidence/integrated-studio/after/empty-library-1366.png) · [모바일](evidence/integrated-studio/after/empty-library-390.png)
- 빈 게시 대기함: [모바일](evidence/integrated-studio/after/empty-queue-390.png)
- 설정 저장 버튼: [모바일](evidence/integrated-studio/after/settings-save-390.png)

## 검증

| 항목 | 결과 | 근거·제한 |
|---|---|---|
| 변경 범위 회귀 | **PASS: 93 passed, 0 failed, 0 skipped, 1 warning** | [로그](evidence/integrated-studio/scoped-regression.txt); 아래 명령 |
| 별도 실제 서버/브라우저 감사 | **PASS: 2 passed, 0 failed, 1 warning** | [로그](evidence/integrated-studio/final-browser.txt), [33 화면 감사](evidence/integrated-studio/after/audit.json) |
| 최종 앵커·단계 링크 | **PASS: 10 passed, 0 failed, 1 warning** | [로그](evidence/integrated-studio/anchor-navigation.txt); 93개 중 10개를 최종 앵커 보존 후 재확인, 별도 신규 10개로 합산하지 않음 |
| 기준 화면 감사 | PASS: 1 passed, 1 warning | [기준 로그](evidence/integrated-studio/baseline-browser.txt), 기준 SHA에서 같은 화면·크기 캡처 |
| Ruff / JS 구문 / diff 검사 | PASS | 변경 테스트 4개 ruff, `node --check`, `git diff --check` |
| 의존성 | PASS | Python 3.12.14 `pip check`: No broken requirements found; 캐시 디렉터리 권한 경고로 캐시 비활성화 |
| Windows·Windows Actions | **NOT VERIFIED** | 실제 Windows 환경 미접속. UI 범위 Cloud 검증만 수행했고 광범위 기존 Windows 회귀를 반복하지 않도록 `[skip ci]` 사용. Windows PASS로 대체하지 않음 |
| 기존 전체 회귀 | **기존 57 FAIL 기록 유지** | 전체 회귀 재실행·실패 삭제·임의 skip 없음. 범위 테스트 통과를 전체 PASS로 확대하지 않음 |

Cloud Linux는 개발/격리 테스트만 사용했다. Python 3.14와 Windows 화면 배율·OS 기능은 이번에 실행하지 않았다. 테스트의 1 warning은 기존 Starlette TestClient/httpx deprecation이다. 의존성을 임의 변경하지 않았다.

기본 메뉴·접힌 도구 키보드 이동, 현재 단계, 모바일 메뉴, 설정 저장→이동→재진입, 제작 기본값, 탭별 노출, 키 비노출, 대본→영상 구성, 장면 선택/키보드 조작, MP4 저장 링크, 통합 게시 폼·CSRF·플랫폼별 별도 승인 경계를 검증했다. 로컬 브라우저의 모든 외부 요청과 승인 없는 POST를 가드했다. 설정 테스트의 POST는 임시 데이터에만 수행했다.

실제 서버 감사는 11개 화면×3개 크기에서 HTTP 200·JS 오류 없음·문서 가로 넘침 없음과 합성 작업/대본/설정 레코드 및 합성 파일 해시 보존을 확인했다. 추가 6개 빈 화면을 캡처하고 빈 화면의 다음 행동을 키보드로 실행했다. 390px 오류 버튼의 비겹침도 확인했다. 모든 상태·페이지에 대한 접근성 인증이나 WCAG 완전 준수 판정은 아니다.

### 재현 명령

프로젝트 루트의 격리 개발 환경에서 실행한다. 운영 앱이나 사용자 데이터로 실행하지 않는다.

```sh
NEWSFLOW_TEST_B| 홈 | [전](evidence/integrated-studio/before/home-1366.png) · [후](evidence/integrated-studio/after/home-1366.png) | [후](evidence/integrated-studio/after/home-1920.png) | [전](evidence/integrated-studio/before/home-390.png) · [후](evidence/integrated-studio/after/home-390.png) |
| 제작 | [전](evidence/integrated-studio/before/create-1366.png) · [후](evidence/integrated-studio/after/create-1366.png) | [후](evidence/integrated-studio/after/create-1920.png) | [전](evidence/integrated-studio/before/create-390.png) · [후](evidence/integrated-studio/after/create-390.png) |
| 작업 현황 | [전](evidence/integrated-studio/before/tasks-1366.png) · [후](evidence/integrated-studio/after/tasks-1366.png) | [후](evidence/integrated-studio/after/tasks-1920.png) | [전](evidence/integrated-studio/before/tasks-390.png) · [후](evidence/integrated-studio/after/tasks-390.png) |
| 대본 | [전](evidence/integrated-studio/before/script-1366.png) · [후](evidence/integrated-studio/after/script-1366.png) | [후](evidence/integrated-studio/after/script-1920.png) | [전](evidence/integrated-studio/before/script-390.png) · [후](evidence/integrated-studio/after/script-390.png) |
| 영상 구성 | [전](evidence/integrated-studio/before/video-1366.png) · [후](evidence/integrated-studio/after/video-1366.png) | [후](evidence/integrated-studio/after/video-1920.png) | [전](evidence/integrated-studio/before/video-390.png) · [후](evidence/integrated-studio/after/video-390.png) |
| 내 영상 | [전](evidence/integrated-studio/before/library-1366.png) · [후](evidence/integrated-studio/after/library-1366.png) | [후](evidence/integrated-studio/after/library-1920.png) | [전](evidence/integrated-studio/before/library-390.png) · [후](evidence/integrated-studio/after/library-390.png) |
| 설정 | [전](evidence/integrated-studio/before/settings-1366.png) · [후](evidence/integrated-studio/after/settings-1366.png) | [후](evidence/integrated-studio/after/settings-1920.png) | [전](evidence/integrated-studio/before/settings-390.png) · [후](evidence/integrated-studio/after/settings-390.png) |
| 최종 검토·게시 | [전](evidence/integrated-studio/before/publish-1366.png) · [후](evidence/integrated-studio/after/publish-1366.png) | [후](evidence/integrated-studio/after/publish-1920.png) | [전](evidence/integrated-studio/before/publish-390.png) · [후](evidence/integrated-studio/after/publish-390.png) |
| 게시 대기함 | [전](evidence/integrated-studio/before/queue-1366.png) · [후](evidence/integrated-studio/after/queue-1366.png) | [후](evidence/integrated-studio/after/queue-1920.png) | [전](evidence/integrated-studio/before/queue-390.png) · [후](evidence/integrated-studio/after/queue-390.png) |
| 실패 안내 | [전](evidence/integrated-studio/before/error-1366.png) · [후](evidence/integrated-studio/after/error-1366.png) | [후](evidence/integrated-studio/after/error-1920.png) | [전](evidence/integrated-studio/before/error-390.png) · [후](evidence/integrated-studio/after/error-390.png) |
| 운영 관리 | [전](evidence/integrated-studio/before/operations-1366.png) · [후](evidence/integrated-studio/after/operations-1366.png) | [후](evidence/integrated-studio/after/operations-1920.png) | [전](evidence/integrated-studio/before/operations-390.png) · [후](evidence/integrated-studio/after/operations-390.png) |ER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs \
 tests/test_studio_design_system.py tests/test_studio_structure.py tests/test_studio_structure_browser.py \
 tests/test_workspace_access.py tests/test_workspace_access_browser.py \
 tests/test_settings_simplification.py tests/test_settings_streamlined_browser.py \
 tests/test_publish_save_browser.py tests/test_studio_dashboard_polish.py \
 tests/test_unified_publishing_gui.py \
 tests/test_creator_ui.py::test_navigation_and_read_only_views_preserve_settings_and_security \
 tests/test_creator_ui.py::test_library_loads_thumbnails_instead_of_all_media

PYTHONPATH=tests NEWSFLOW_TEST_B| 홈 | [전](evidence/integrated-studio/before/home-1366.png) · [후](evidence/integrated-studio/after/home-1366.png) | [후](evidence/integrated-studio/after/home-1920.png) | [전](evidence/integrated-studio/before/home-390.png) · [후](evidence/integrated-studio/after/home-390.png) |
| 제작 | [전](evidence/integrated-studio/before/create-1366.png) · [후](evidence/integrated-studio/after/create-1366.png) | [후](evidence/integrated-studio/after/create-1920.png) | [전](evidence/integrated-studio/before/create-390.png) · [후](evidence/integrated-studio/after/create-390.png) |
| 작업 현황 | [전](evidence/integrated-studio/before/tasks-1366.png) · [후](evidence/integrated-studio/after/tasks-1366.png) | [후](evidence/integrated-studio/after/tasks-1920.png) | [전](evidence/integrated-studio/before/tasks-390.png) · [후](evidence/integrated-studio/after/tasks-390.png) |
| 대본 | [전](evidence/integrated-studio/before/script-1366.png) · [후](evidence/integrated-studio/after/script-1366.png) | [후](evidence/integrated-studio/after/script-1920.png) | [전](evidence/integrated-studio/before/script-390.png) · [후](evidence/integrated-studio/after/script-390.png) |
| 영상 구성 | [전](evidence/integrated-studio/before/video-1366.png) · [후](evidence/integrated-studio/after/video-1366.png) | [후](evidence/integrated-studio/after/video-1920.png) | [전](evidence/integrated-studio/before/video-390.png) · [후](evidence/integrated-studio/after/video-390.png) |
| 내 영상 | [전](evidence/integrated-studio/before/library-1366.png) · [후](evidence/integrated-studio/after/library-1366.png) | [후](evidence/integrated-studio/after/library-1920.png) | [전](evidence/integrated-studio/before/library-390.png) · [후](evidence/integrated-studio/after/library-390.png) |
| 설정 | [전](evidence/integrated-studio/before/settings-1366.png) · [후](evidence/integrated-studio/after/settings-1366.png) | [후](evidence/integrated-studio/after/settings-1920.png) | [전](evidence/integrated-studio/before/settings-390.png) · [후](evidence/integrated-studio/after/settings-390.png) |
| 최종 검토·게시 | [전](evidence/integrated-studio/before/publish-1366.png) · [후](evidence/integrated-studio/after/publish-1366.png) | [후](evidence/integrated-studio/after/publish-1920.png) | [전](evidence/integrated-studio/before/publish-390.png) · [후](evidence/integrated-studio/after/publish-390.png) |
| 게시 대기함 | [전](evidence/integrated-studio/before/queue-1366.png) · [후](evidence/integrated-studio/after/queue-1366.png) | [후](evidence/integrated-studio/after/queue-1920.png) | [전](evidence/integrated-studio/before/queue-390.png) · [후](evidence/integrated-studio/after/queue-390.png) |
| 실패 안내 | [전](evidence/integrated-studio/before/error-1366.png) · [후](evidence/integrated-studio/after/error-1366.png) | [후](evidence/integrated-studio/after/error-1920.png) | [전](evidence/integrated-studio/before/error-390.png) · [후](evidence/integrated-studio/after/error-390.png) |
| 운영 관리 | [전](evidence/integrated-studio/before/operations-1366.png) · [후](evidence/integrated-studio/after/operations-1366.png) | [후](evidence/integrated-studio/after/operations-1920.png) | [전](evidence/integrated-studio/before/operations-390.png) · [후](evidence/integrated-studio/after/operations-390.png) |ER_EXECUTABLE=/usr/bin/chromium \
 UX_PHASE=after UX_EVIDENCE=/tmp/newsflow-unified-recheck \
 .venv/bin/python -m pytest -q -rs docs/reports/evidence/integrated-studio/test_visual_audit.py
```

기존 테스트의 메뉴 개수·차트 접힘·링크 범위를 실제 UI 계약에 맞췄다. 설정 브라우저 테스트의 오래된 hidden select 조작은 기존 제작 선택기의 실제 저장 동선으로 교체했다. 장면 테스트는 페이지 전환 뒤 deferred 스크립트 로드를 기다리게 수정했다. 검사·테스트 삭제나 skip 추가는 없다.

## 보존 및 한계

- 실제 유료 API·공급사 계정 조회·OAuth·SNS 업로드/게시 **0건**. Fake 네트워크 가드와 감사의 `external: []`로 확인. GitHub 코드·PR 작업은 별도다.
- 운영 DB·키·설정·기존 MP4에 접근하거나 앱을 재시작하지 않았다. 임시 DB/폴더/합성 키만 사용했다. 기존 데이터 보존은 합성 레코드·파일에 대한 자동 검증이며 사용자 PC 데이터의 실측 검증은 아니다.
- 이번 합성 미디어는 UI fixture다. 일부 화면의 플레이어 로딩 표시는 유효 MP4 품질/재생 성공 증거가 아니다. 렌더링·실제 음성/자막 싱크·콘텐츠 품질·실계정 게시 성공을 주장하지 않는다.
- 사용자 Windows PC의 Chrome, 화면 배율, 한국어 음성, 운영 DB와 MP4 재생은 **NOT VERIFIED**. PC 복귀 후 홈→제작→검토→게시 준비, 설정 저장과 기존 영상 재생을 확인해야 한다.
- 현재 표현은 전체 공통 기본 템플릿에 적용했으나 모든 세부 설정 모달·모든 실패 조합·외부 공급사 화면을 전수 시각 검증한 것은 아니다.

## 변경 파일

- `src/newsflow/gui/templates/base.html`
- `src/newsflow/gui/templates/creator_dashboard.html`
- `src/newsflow/gui/templates/easy_home.html`
- `src/newsflow/gui/templates/production_form.html`
- `src/newsflow/gui/templates/queue.html`
- `src/newsflow/gui/templates/serpapi_connection.html`
- `src/newsflow/gui/templates/simple_settings.html`
- `src/newsflow/gui/templates/studio_journey.html`
- `src/newsflow/gui/templates/video.html`
- `src/newsflow/static/css/studio-system.css`
- `src/newsflow/static/js/studio-journey.js`
- `tests/test_settings_streamlined_browser.py`
- `tests/test_studio_dashboard_polish.py`
- `tests/test_studio_design_system.py`
- `tests/test_workspace_access_browser.py`

보고서·증거는 `docs/reports/integrated_studio_ux_review.md`와 `docs/reports/evidence/integrated-studio/`에 보존한다. [manifest](evidence/integrated-studio/manifest.json)에 코드·자료 SHA-256을 기록했다. 결과 제출 후 추가 개발 없이 중단한다.
