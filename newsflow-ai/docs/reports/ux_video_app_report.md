# NewsFlow AI — 영상 제작 앱 UX/UI 개선

보고 기준: 2026-10-19 KST. 최종 운영 대상 Windows 11, 이번 실행 환경 Cloud Linux / Python 3.12.14 / Chromium 151.0.7922.173.

## 기준과 범위

- 기존 Cloud 체크아웃은 `feat/newsflow-phase5f` / `37597fdd…`, 미커밋 변경 없음으로 확인했다. GitHub 원격과 열린 PR을 조회하여 최신 기능 계열인 **`codex/newsflow-core-production` / `590ffd447eebf76b9429c22a3354dbfa239dec16` (PR #34)**를 기준으로 분기했다. 이전 Phase 5F 코드를 최신 구현으로 잘못 간주하지 않았다.
- 신규 브랜치: `codex/newsflow-ux-video-app`. [Draft PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35), base `codex/newsflow-core-production`. 기존 PR과 브랜치를 수정하거나 병합하지 않았다.
- 계획: 기존 계약·전후 화면 확보 → 제작 앱 형태로 정리 → 격리 브라우저·회귀 검사 → 증거와 PR 제출.
- 검색·대본·음성·렌더링·인증·비용·게시 엔진, DB 모델·마이그레이션, `run.bat`, Windows 전용 구현을 변경하지 않았다. 운영 앱을 재시작하지 않았으며 테스트용 별도 프로세스와 새 TEMP 데이터만 사용했다.

## 화면과 실제 연결

| 화면 | 변경 | 연결 및 경계 |
|---|---|---|
| 홈 | 큰 주제 입력, 기본 AI·음성 표시와 연결 설정 링크, 진행 작업, 썸네일 중심 최근 영상 | 입력은 기존 `GET /news?q=…`로 이동. '저장된 설정으로 바로 제작'은 접어서 보존 |
| 쇼츠 만들기 | `/create`에 독립된 제작 화면, 길이와 자료 중심 입력, 상세 옵션 접기 | 기존 홈 화면 컨텍스트와 `POST /autopilot/quick-start` 재사용. AI·모델·기본 음성은 저장된 설정 유지. 음성 변경은 설정 또는 기존 영상 제작 단계에서 가능 |
| 제작 상태 | 자료 준비 → 대본 작성 → 음성·영상 제작 → 미리보기 | 실제 현재 단계에 연결. 시간 기반 예상 퍼센트를 만들지 않으며 홈 카드와 간단 진행 화면은 단계 중심. 상세 근거·로그는 접어서 보존 |
| 내 영상 | 목록에서 MP4를 모두 로드하던 방식 대신 썸네일·길이·상태·편집·게시 링크 | 기존 `/videos`, 검증된 `/video/jobs/{id}/thumbnail`·`file` 사용. 준비되지 않은 파일을 재생 가능으로 표시하지 않음 |
| 미리보기·수정 | 9:16 플레이어와 장면 선택·대본·자막 입력을 나란히 배치, 좁은 화면은 세로 배치 | `GET /ai?draft_id=…`가 기존 안전한 미디어 경계로 최근 완성본을 조회. 기존 revision 기반 `POST /ai/drafts/{id}`로 저장. 저장만으로 AI/TTS/렌더링을 호출하지 않음 |
| 게시 | YouTube·Instagram·양쪽, 계정·공통 메타데이터·플랫폼별 승인 옵션, 부분 성공·실패·결과 불명 구분 | 기존 통합 게시 계약과 승인·중복 방지 유지. 계정 미연결이면 검토 저장 차단 및 해결 안내. 완료 플랫폼은 재게시하지 않으며 불명 결과는 재전송하지 않음 |
| 설정 | AI 연결 / 음성·영상 / 게시 계정 / 저장 위치 / 고급 설정으로 이동 | 키 저장과 실제 인증·검색 성공 상태는 기존 구분 유지. 계정 초기 설정은 접고, 기존 고급 도구는 보존. 추정 사전 예약·요청별 금액 한도는 추가하지 않음 |

편집에서는 저장하지 않은 변경을 알리고 페이지 이탈 확인을 제공한다. 다른 장면의 입력 오류가 있으면 해당 장면을 열어 포커스할 수 있다. 실패 응답의 안내 영역으로 포커스를 옮기며 자동 재전송하지 않는다. 기존 로컬 주제 대본의 읽기 전용 필드·허용된 문장 선택·출처·미확인 표시도 유지한다.

### 별도 백엔드 승인이 필요한 사항

1. **자유 주제나 새 기사 URL을 직접 생성에 전달하는 계약은 없다.** 현재 검색 엔진의 입력은 분야·기간·확보 정책이고, 자유 입력은 보관 기사 검색으로 연결했다. 새 URL 가져오기는 화면에서 미지원으로 안내한다. 이 입력을 조용히 무시하거나 새 스크래핑·검색 엔진을 추가하지 않았다. 직접 제작을 지원하려면 입력 검증·획득 정책·동의·작업 중복 식별자까지 별도 계약 검토가 필요하다.
2. **통합 게시 초안 저장은 연결된 계정을 요구한다.** 계정 없이 제목·설명을 영속 저장하는 신규 계약을 만들지 않았다. 연결 전에는 저장되지 않음을 표시하고 이탈 확인을 제공한다. MP4 다운로드는 사용할 수 있다.
3. **초안 변경은 이미 만든 MP4를 바꾸지 않는다.** 편집기에는 편집 전 제작본을 표시하고 재제작 필요를 안내한다. 기존 Video Studio의 음성·길이·자막·소재 설정과 검토 후 명시적 제작 실행으로 연결한다. 편집 저장과 제작·유료 실행을 합치지 않았다.
4. 지원하지 않는 VERIFIED는 신규 제작 선택에서 숨겼다. 과거 흐름·작업 기록의 VERIFIED 값과 기존 차단 검증은 보존했다.

## 변경 전후 화면

동일한 합성 자료·무음 MP4로 촬영했다. 변경 전은 PR #34의 원본 Jinja 템플릿을 별도 읽기 전용 디렉터리에서 사용했다. 원래 별도 제작 화면이 없었으므로 '제작 전'은 당시 홈의 제작 입력 화면이다. 데모 화면·플랫폼 결과는 실제 기사 품질이나 게시 성공 증거가 아니다.

| 화면 | 변경 전 | 변경 후 · 1366px |
|---|---|---|
| 홈 | [전](evidence/ux-video-app/before/home.png) | [후](evidence/ux-video-app/after/home-1366.png) |
| 제작 | [전](evidence/ux-video-app/before/create.png) | [후](evidence/ux-video-app/after/create-1366.png) |
| 내 영상 | [전](evidence/ux-video-app/before/videos.png) | [후](evidence/ux-video-app/after/videos-1366.png) |
| 미리보기·편집 | [전](evidence/ux-video-app/before/preview.png) | [후](evidence/ux-video-app/after/preview-1366.png) |
| 설정 | [전](evidence/ux-video-app/before/settings.png) | [후](evidence/ux-video-app/after/settings-1366.png) |
| 게시 | [전](evidence/ux-video-app/before/publishing.png) | [후](evidence/ux-video-app/after/publishing-1366.png) |

[보고서·화면 ZIP](ux_video_app_review.zip) · [화면 비교 HTML](ux_video_app_review.html) · [브라우저 결과 JSON](evidence/ux-video-app/after/browser-results.json). 각 화면의 `-1920.png`, `-390.png`도 증거 디렉터리에 있다. 실제 작업의 [진행](evidence/ux-video-app/after/creation-progress.png), [실패](evidence/ux-video-app/after/creation-failure.png), [수정 충돌](evidence/ux-video-app/after/error-stale-edit.png), [저장 중](evidence/ux-video-app/after/loading-save.png), [긴 한글](evidence/ux-video-app/after/long-korean-editor.png), [플랫폼 부분 성공](evidence/ux-video-app/after/publishing-partial.png), [결과 불명](evidence/ux-video-app/after/publishing-unknown.png), [빈 홈](evidence/ux-video-app/after/empty-home.png)을 별도 캡처했다.

## Cloud 데모와 검증 방법

[실제 렌더링 미디어 확인](evidence/ux-video-app/rendered-media.json): 1080×1920, 30.021초, 무음, 실제 브라우저 디코딩 확인. 이는 한국어 음질·내용 품질 평가가 아니다.

`tools/ui_preview.py`는 운영 `run.bat`와 분리된 개발·검토 전용 진입점이다. 새 절대 TEMP 디렉터리만 허용하며, 기존 디렉터리이면 DB를 열기 전에 거부한다. 별도 SQLite·합성 기사·Fake Provider·로컬 도형의 무음 MP4를 사용한다. 화면에는 데모임을 계속 표시한다.

- 기존 사용자 데이터·키를 읽지 않는다. NEWSFLOW 키·설정 환경변수를 제거하며 외부 DNS·소켓과 인증/OS 프로세스 실행을 차단한다.
- 인증·키 연결 점검·게시 요청을 데모 미들웨어에서 차단한다. Offline 분석·대본, 명시적 검토 후 로컬 무음 렌더링, 편집, 체험 제작만 검사한다. 실제 게시 결과를 DB에 성공으로 쓰지 않는다.
- 부분 성공·결과 불명은 **합성 조회 결과 주입**으로 표시한다. 기존 통합 게시 엔진의 중복·승인·결과 불명 동작은 별도 회귀 테스트로 검증한다.
- 이는 Linux 운영 지원을 추가한 것이 아니다. Windows SAPI·DPAPI·BAT와 기존 실행 경로는 유지한다.

Cloud 재현 명령 (각 실행에 **존재하지 않는 새 TEMP 폴더** 사용):

```bash
cd /workspace/JSBAE/newsflow-ai
.venv/bin/python tools/ui_preview.py --data-dir /tmp/newsflow-ui-review-NEW --port 8888
# 다른 터미널. 브라우저 검사는 해당 데모에만 실행한다.
.venv/bin/python tools/ui_browser_check.py --base http://127.0.0.1:8888 --output /tmp/newsflow-ui-browser-evidence
```

운영 앱의 8765 포트를 사용하거나 운영 데이터 경로를 입력하지 않는다. 테스트 서버는 자체 실행 창에서 Ctrl+C로 종료한다. 일반 Windows 사용자는 기존 `run.bat`를 그대로 사용한다. 원격 공개 URL·영상 외부 전송은 만들지 않았다.

## 검증 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| 관련 UI·보안 회귀 | PASS | **109 passed / 0 failed**, 기존 warning 1건. 신규 UI 13건·데모 안전 경계 2건·장면 정렬 브라우저 1건 및 모델 선택 브라우저 4건 포함 |
| ruff / diff whitespace | PASS | `python -m ruff check src tests tools`, `git diff --check` |
| 실제 Chromium 동선 | PASS | 9개 시나리오. 검색→기사 선택→기존 Offline 분석·대본 POST, 편집 저장·충돌 409, 기존 MP4 해시 보존, 체험 Autopilot 시작, 실제 기존 렌더링 POST → 1080×1920 무음 MP4 생성·재생 |
| 반응형 | PASS | 8개 화면 × 1366×768·1920×1080·390×844 = 24개 조합, 가로 스크롤 없음·표시된 입력란 이름 확인. 주요 화면 직접 캡처 검토 |
| 확대 | PASS · Cloud 범위 | 8개 화면 CSS zoom 200%. 편집기 가로 넘침을 발견해 컨테이너 폭 기준 세로 전환으로 수정. Windows 배율·브라우저 메뉴 확대 검증을 대신하지 않음 |
| 접근성 표본 | PASS · 표본 | 본문 건너뛰기·포커스 표시·장면 버튼·오류 포커스·모달 Escape/복귀. 주요 색상 7개 표본 대비 7.99~16.43:1. 전체 WCAG 감사·스크린리더 검증은 미실행 |
| 빈 화면·로딩·긴 한글·실패 | PASS | 별도 빈 DB·98자 제목·390자 내레이션·보류된 실제 저장 요청·기존 충돌 응답·합성 실패 |
| 게시 부분 성공·결과 불명 | PASS · 합성 | 플랫폼별 결과 표시, 완료 재게시/불명 재전송 버튼 없음. 실제 SNS 결과가 아님 |
| 데모 인증·게시·API 점검 차단 | PASS | [보호 경로 4개 로컬 POST 403](evidence/ux-video-app/demo-boundary.json), 외부 실행 전 차단 |
| 원본 전체 회귀 | FAIL | PR #34 원본 아카이브에서 **3479 passed / 61 failed / 4 errors / 20 skipped**. 작업 브랜치와 별도 소스로 재현 |
| 최종 전체 회귀 | **FAIL · 원본에서 재현된 실패 잔존** | **3502 passed / 57 failed / 0 errors / 20 skipped**, 기존 warning 1건. 원본 대비 신규 실패·오류 0건. 후속 UI 전용 109건은 별도 전부 통과 |
| Windows PC·BAT·Chrome·DPAPI·실제 배율 | NOT VERIFIED | 사용자 PC 연결 없음. 과거 CI 성공으로 이번 UI 검증을 대체하지 않음 |

기존 엔진 동작 변경과 맞지 않는 테스트 기대값, Chrome 전용 테스트 fixture의 브라우저 미설치 오류 등이 원본에서도 발생했다. Cloud에 설치된 Chromium 경로를 테스트 전용 환경변수로 명시할 수 있게 했고 해당 모델 선택 브라우저 4건은 통과했다. Windows의 기본 Chrome 실행은 유지한다. 모든 잔존 실패를 단순한 구식 테스트로 단정하지 않는다. 이번 범위에서는 원본 재현과 변경 영향 비교까지만 수행했다. 전체 회귀를 PASS로 보고하지 않는다. 무API 콘텐츠 품질·기존 엔진을 변경해서 테스트를 맞추지 않았다. 신규 UI의 메뉴·화면 이동·단계 표시·VERIFIED 선택 기대값만 새 UX에 맞게 갱신하고 보안·출처·동의·revision·미디어 보존 assertion은 유지했다. 상세 실패 목록·비교는 `evidence/ux-video-app/regression-comparison.json`에 기록한다.

실행한 관련 회귀:

```text
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q
  tests/test_creator_ui.py tests/test_creator_preview_boundary.py
  tests/test_creator_scene_browser.py tests/test_model_picker_browser.py
  tests/test_single_workspace.py tests/test_topic_editor_gui.py tests/test_easy_ui.py
  tests/test_unified_publishing_gui.py tests/test_ux_navigation.py tests/test_news_usage_gui.py
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q -rs
python -m ruff check src tests tools
```

## 변경 파일과 보존 확인

- `gui/templates/`: 앱 셸, 홈, 제작 상태, 영상 목록, 미리보기/기존 대본 편집 partial, 게시, 뉴스에서 제작 진입, 설정·계정 초기 설정 접기.
- `static/css/creator.css`, `static/js/creator.js`: 시각 체계·반응형·컨테이너 확대 대응·키보드/장면 선택·저장 전 이탈 안내.
- `static/js/app.js`, `publish_workspace.js`: 오류 포커스, 계정 미연결 시 저장 차단·안내·저장 전 이탈 안내.
- `gui/autopilot_routes.py`: 기존 홈 컨텍스트를 재사용하는 GET `/create` 별칭.
- `gui/intelligence_routes.py`: 편집기의 안전한 기존 영상 조회 컨텍스트 추가. POST 계약·엔진 변경 없음.
- `tests/test_creator_ui.py`, `test_creator_preview_boundary.py`, `test_creator_scene_browser.py`, 테스트용 Chromium 경로 선택, 관련 UI 기대값과 새 브라우저 검증 도구·격리 데모·본 보고서/스크린샷.
- DB·migration·엔진·비용 정책·실제 OAuth·게시 로직·Windows BAT와 다른 프로젝트의 변경 없음. main·기존 PR·다른 작업 브랜치 변경/병합/force push 없음.

## 실제 실행과 미검증

실제 유료 AI·OAuth 승인·SNS 업로드/게시·운영 OS 작업 등록은 **0건**이다. 이 수치는 새 TEMP 데이터·키 미사용·외부 요청 차단·로컬 보호 경로 검사에 근거한다. 브라우저의 외부 요청 및 JS 오류도 0건이다. 합성 미디어는 TEMP에만 두고 Git/PR에 MP4를 업로드하지 않는다.

Windows에서 추가로 확인할 항목은 일반 권한 `run.bat`, 한국어 글꼴·SAPI 노출과 청취 품질, 실제 Chrome 재생·125/150/200% 배율, DPAPI 키 상태의 표시, 운영 데이터 보존 및 원문 검토다. 실제 API·계정 검증은 이번 승인에 포함하지 않는다. UI 변경은 테스트 데이터에서 검증했으며, 운영 배포·실제 사용자 사용성·기사/음성/영상 품질의 PASS를 의미하지 않는다.

## Git 및 다음 단계

실행 UI 코드: `ae20b76…`. 전체 회귀 실행 기준은 `42d1717`이며 이 커밋에서 전체 pytest를 실행했다. 후속 `e401d9e`에서는 읽기 전용 과거 대본의 장면 순서를 바꿀 때 선택 탭이 따라가지 않는 UI 문제를 수정하고 별도 실제 브라우저 회귀 및 관련 UI 109건으로 검증했다. 이후 문서·화면 증거만 추가한다. `8e3f897`·`39ef178`은 검토용 도구 보완, `42d1717`은 Cloud 테스트 브라우저 선택 보완이다. 최종 제출 SHA는 PR HEAD와 제출 메시지에서 확인한다. 문서·화면 증거 커밋을 실행 코드 테스트 커밋과 혼동하지 않는다.

다음 검토는 PR #35의 화면·제한 안내를 확인하고, 기존 전체 회귀 실패의 별도 정리 범위를 결정하는 것이다. 자유 주제/URL 직접 제작·계정 없는 게시 초안 저장이 필요하면 별도 계약 승인을 받는다. 이번 작업 완료 후 신규 개발·유료 실행·실계정 연결·게시·main 병합을 진행하지 않는다.
