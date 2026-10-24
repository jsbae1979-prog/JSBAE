# PR #35 UX/UI 최종 검증 보고서

보고 시각: 2026-10-19 09:05 KST. 범위는 최종 검증·지원 범위 안내·증거 정리다. 새 제작 기능·디자인 개편·백엔드 계약 확장은 없다.

## 판정과 검증 대상

- **전체 회귀: FAIL — 3503 passed / 57 failed / 0 errors / 20 skipped.** 잔존 실패를 전체 PASS로 보고하지 않는다.
- 최종 실행 코드·테스트·검토 도구 SHA: `dbd4ba446c3f13705ac207a37cddbdd5339e6baa`. 이 SHA를 커밋한 뒤 전체 회귀, UI 회귀, Cloud 브라우저 검증을 실행했다. 이후 변경은 보고서·증거뿐이다.
- 기준 SHA: `590ffd447eebf76b9429c22a3354dbfa239dec16` (PR #34 base). 새 임시 디렉터리에 `git archive`로 원본을 추출했다. 브랜치 전환·기존 작업 덮어쓰기·worktree 생성은 없다.
- 작업 브랜치 `codex/newsflow-ux-video-app`, [기존 Draft PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35) 유지. 신규 PR·main/다른 PR 수정·병합·force push 없음. 문서 최종 SHA는 제출 메시지/PR HEAD로 구분한다.

## 동일 조건의 전체 회귀 비교

| 대상 | 이번 실행 결과 | 종료 코드 |
|---|---|---|
| 기준 원본 `590ffd4` | 3483 passed / 61 failed / 0 errors / 20 skipped | 1 |
| 최종 코드 `dbd4ba4` | 3503 passed / 57 failed / 0 errors / 20 skipped | 1 |
| 최종 UI 관련 회귀 | 109 passed / 0 failed / 0 errors / 0 skipped | 0 |

최종 pytest는 종료 코드 1로 완료됐다. 이후 JUnit 파일을 TEMP로 이동하는 도구 단계에서 파일시스템 경계(EXDEV) 오류가 났으며, 원본을 안전하게 복사하고 SHA-256 일치를 확인해 증거를 회수했다. 테스트 실행 결과 변경이나 테스트 미완료가 아니다([복사 확인](evidence/ux-video-app/final-validation/artifact-transfer.json)). 전체 회귀와 UI 회귀에는 각각 기존 warning 1건이 있다. 내용은 테스트 요약 파일에 별도로 기록한다. ruff와 `git diff --check`도 통과했다.

실패 건수만 비교하지 않았다. **최종 실패 ID 57개 중 기준에서도 실패한 ID는 57개, 기준 대비 새로운 실패 ID 0개·새 오류 ID 0개**다. 기준의 추가 실패 4개와 수집된 테스트 ID의 차이도 [정확한 ID 비교 JSON](evidence/ux-video-app/final-validation/regression-comparison.json)에 전부 기록했다. 기존 보고의 57개 실패 ID와 이번 최종 실패 ID의 일치 여부는 `True`이며, 이번 결론의 근거는 같은 조건으로 새로 실행한 기준 비교다. 기준에서만 실패한 4건은 기존 UI 변경에 맞춘 화면 기대값 차이를 포함하므로 엔진 결함을 고쳤다는 뜻이 아니다. 관련 없는 엔진 결함을 수정하거나 실패 테스트를 삭제·skip하지 않았다.

이전 전체 회귀는 `42d1717`에서 실행됐고 `e401d9e` 장면 선택 수정 전이었다. 이전 원본 실행의 Chrome 미설치 오류 4건과 서로 다른 브라우저 설정은 이번 비교 근거로 사용하지 않는다. 기존 보고·증거는 역사 자료로 보존한다.

두 실행은 **같은 Python 3.12.14 실행 파일, 같은 설치 패키지 집합, 같은 pyproject.toml SHA-256, 같은 명령과 Cloud Chromium**을 사용했다. 각 소스의 `src`가 실제 import됐음도 확인했다. 공통 외부 pytest 플러그인은 원본 fixture의 `channel="chrome"`를 `/usr/bin/chromium`으로 지정하는 역할만 한다. 테스트 assertion·수집·보안 검사는 바꾸지 않는다. 최종 브랜치의 명시적 브라우저 환경변수도 같은 실행 파일을 가리킨다. 이는 Windows Chrome/PC 검증이 아니다.

```text
# 각 프로젝트 루트에서 같은 명령 (result.xml은 실행 완료 뒤 TEMP 증거로 이동)
/workspace/JSBAE/newsflow-ai/.venv/bin/python -m pytest -q -rs -p cloud_validation_browser --junitxml=result.xml
# 공통 설정: NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium
# PYTHONPATH=<공통 TEMP 플러그인 경로>:<대상 소스>/src
# NEWSFLOW_* 및 외부 AI 키·pytest 추가 옵션 제거 후 브라우저 변수만 지정
```

[실행 메타데이터·의존성·플러그인·재현 runner](evidence/ux-video-app/final-validation/)에 명령, 시작/종료 시각, 소스 SHA와 해시를 남겼다. 기준 소스와 최종 소스는 별도이며 같은 가상환경을 공유한다. 수집 ID 차이에는 화면 제목 파라미터 2건·동일 검증의 메뉴 테스트 이름 변경 1건·매 수집마다 달라지는 UUID 파라미터 1건이 포함된다. 실패 ID 비교에는 정규화나 이름 치환을 적용하지 않았다. 비교 대상별 전체 로그의 종료 수치·정확한 실패 ID를 요약 파일로 보존했다.

UI 명령:

```text
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q -rs
 tests/test_creator_ui.py tests/test_creator_preview_boundary.py tests/test_creator_scene_browser.py
 tests/test_model_picker_browser.py tests/test_single_workspace.py tests/test_topic_editor_gui.py
 tests/test_easy_ui.py tests/test_unified_publishing_gui.py tests/test_ux_navigation.py tests/test_news_usage_gui.py
python -m ruff check src tests tools
git diff --check
```

## 실제 Cloud 브라우저 동선

**PASS · 격리 합성 환경 한정.** 최종 코드의 `tools/ui_preview.py`를 새 TEMP 경로·별도 loopback 테스트 포트에서 실행했다. 운영 앱 8765 재시작·운영 DB/키/설정/영상 접근은 없다. 실제 사용자 데이터·키를 읽거나 Windows 기능을 삭제하지 않았다.

1. 홈의 **보관 기사 검색** → 검색 결과 1개 → 상세 → 기사 선택 확인 → 기존 Offline 분석 POST → 기존 대본 생성 POST.
2. 명시적 대본 검토 → 기존 `/video/render` POST → FFmpeg 무음 MP4 → 실제 Chromium 디코딩·재생 → 내 영상 목록 → 해당 초안 편집·미리보기 → 해당 영상의 게시 준비. 새 생성 API는 없다.
3. 기존 MP4가 연결된 초안에서 장면 선택·자막 변경 → 기존 revision 기반 저장 → 다시 조회한 값 확인. 기존 MP4 해시 불변. 저장 요청 대기 표시, 오래된 revision의 실제 HTTP 409·오류 포커스 확인. 자동 재전송 없음.
4. **마지막 장면 순서 수정 재검증:** 기존 보호 대본 합성 기록에서 장면 3을 2번 위치로 이동 → 장면 2 선택 탭 표시 → 동일한 읽기 전용 내레이션 유지 → 허용된 자막 선택 → 실제 POST 303 → revision 2·순서·자막 재조회 확인. 단독 DOM 테스트와 별개로 실제 앱에서 검증했다.
5. 기존 체험 Autopilot의 현재 단계 표시·VERIFIED 선택 숨김, 긴 한글, 빈 화면, 오류, 설정 대화상자 키보드 복귀 확인.
6. 플랫폼별 부분 성공·실패·결과 불명은 **조회 전용 합성 상태**다. 완료 플랫폼 재게시·불명 결과 재전송 액션이 제공되지 않음을 확인했다. 실제 SNS 성공을 DB에 기록하거나 실행하지 않았다. 계정이 없어 통합 게시 초안을 저장할 수 없는 기존 계약은 유지했다.

[브라우저 결과](evidence/ux-video-app/final-validation/browser-results.json): 10개 시나리오, 8개 화면 × 1366×768·1920×1080·390×844 = 24개 조합. 가로 스크롤 없음, 표시된 입력 이름, 건너뛰기·키보드·오류 포커스·설정 Escape 복귀, 7개 색상 대비 표본을 확인했다. 장면 재정렬 후 화면도 세 크기에서 다시 열어 버튼 bounding box의 겹침과 가로 넘침이 없음을 확인했다([장면 레이아웃](evidence/ux-video-app/final-validation/scene-layout.json)). 스크린샷을 육안 검토했으며 긴 한글은 줄바꿈된다. 전체 WCAG/스크린리더 감사나 사람 대상 사용성 조사는 아니다. CSS zoom 200%는 Cloud 레이아웃 근사 검사이며 Windows 배율·native 브라우저 확대 검증이 아니다.

## 입력란과 실제 지원 범위

홈 label은 **“보관한 기사에서 어떤 주제를 찾을까요?”**, 버튼은 **“보관 기사 검색”**이다. **이미 수집·보관한 기사만 검색하며 검색 결과에서 기사를 선택한 뒤 분석·대본 작성**을 시작한다고 명시한다. 새 기사 검색·새 URL 가져오기는 미지원이며 URL 입력 시 안내 후 이동을 막는다. 주제만 입력해 새 기사를 찾아 바로 제작한다는 계약은 없다. 일반 제작 옵션의 VERIFIED는 계속 숨기고 기존 기록·보호 규칙은 보존한다.

이번 실행 코드 변경은 홈의 지원 범위 문구와 해당 테스트, 격리 데모/브라우저 검증용 합성 fixture·동선뿐이다. 영상 제작·검색·인증·비용·게시 엔진, DB/migration, Windows BAT, 의존성 선언은 기준 대비 변경하지 않았다([보존 확인](evidence/ux-video-app/final-validation/preservation.json)).

## 화면 자료

[전후 비교 HTML](ux_video_app_review.html) · [전체 자료 ZIP](ux_video_app_review.zip). HTML은 ZIP을 풀고 열면 로컬 이미지로 동작한다. 새 캡처는 모두 최종 코드에서 촬영했다. 변경 전 자료는 기존 PR #34 원본 템플릿 캡처를 재사용하며 새 검증으로 잘못 표시하지 않는다.

| 화면 | 최종 1366px | 1920px | 좁은 화면 |
|---|---|---|---|
| 홈 | [보기](evidence/ux-video-app/final-validation/home-1366.png) | [보기](evidence/ux-video-app/final-validation/home-1920.png) | [보기](evidence/ux-video-app/final-validation/home-390.png) |
| 제작 | [보기](evidence/ux-video-app/final-validation/create-1366.png) | [보기](evidence/ux-video-app/final-validation/create-1920.png) | [보기](evidence/ux-video-app/final-validation/create-390.png) |
| 내 영상 | [보기](evidence/ux-video-app/final-validation/videos-1366.png) | [보기](evidence/ux-video-app/final-validation/videos-1920.png) | [보기](evidence/ux-video-app/final-validation/videos-390.png) |
| 편집·미리보기 | [보기](evidence/ux-video-app/final-validation/preview-1366.png) | [보기](evidence/ux-video-app/final-validation/preview-1920.png) | [보기](evidence/ux-video-app/final-validation/preview-390.png) |
| 게시 준비 | [보기](evidence/ux-video-app/final-validation/publishing-1366.png) | [보기](evidence/ux-video-app/final-validation/publishing-1920.png) | [보기](evidence/ux-video-app/final-validation/publishing-390.png) |
| 설정 | [보기](evidence/ux-video-app/final-validation/settings-1366.png) | [보기](evidence/ux-video-app/final-validation/settings-1920.png) | [보기](evidence/ux-video-app/final-validation/settings-390.png) |

[장면 재정렬·저장 후](evidence/ux-video-app/final-validation/scene-saved-1366.png) · [좁은 장면 편집](evidence/ux-video-app/final-validation/scene-saved-390.png) · [내 영상 → 편집](evidence/ux-video-app/final-validation/flow-library-to-editor.png) · [제작본 게시 준비](evidence/ux-video-app/final-validation/flow-publish-preparation.png) · [저장 충돌](evidence/ux-video-app/final-validation/error-stale-edit.png) · [실제 무음 렌더](evidence/ux-video-app/final-validation/rendered-through-ui.png).

## 검증 수준·남은 항목

- **PASS · 렌더링/재생만:** 1080×1920 H.264 / AAC 무음, 약 30.021초 MP4 생성·브라우저 재생. [ffprobe 결과](evidence/ux-video-app/final-validation/rendered-media.json). 한국어 음성 품질·음성/자막 싱크·실제 AI 기사 품질·OAuth·SNS 게시 성공의 증거로 사용하지 않는다.
- **NOT VERIFIED:** 사용자 Windows 11 실행·BAT·Chrome·DPAPI·실제 화면 배율, 한국어 음성 청취·자막 싱크·30/45/60초 사람의 완성 품질 평가, 실제 RSS/AI API·실계정 인증·업로드·게시. 이번 작업에서 Windows Actions를 실행하지 않았으며 과거 성공으로 대체하지 않았다.
- 실제 유료 API·OAuth 승인·SNS 업로드/게시 호출 **0건**. live opt-in과 키를 사용하지 않았고 데모의 외부 소켓/DNS·인증/게시 POST는 차단했다. 브라우저 외부 요청·JS 오류 0건이다. 전체 시스템 패킷 감사를 수행했다는 의미는 아니다.
- 전체 회귀의 잔존 실패는 별도 결함 정리 대상이다. 이번 UX/UI 작업에서 관련 없는 결함을 대규모 수정하거나 보안·승인·중복 방지를 완화하지 않았다.

이 보고서와 자료 제출 후 추가 개발·실제 실행·main 병합을 중단한다. 다음 검토는 잔존 회귀 실패 처리 범위와 사용자 Windows PC 수동 검증이다.
