# NewsFlowAI — 목업 기반 실제 대시보드 구현

2026-10-19 KST. 기준 `a949468`, 검증 코드 `c634ace649ae8a3ac661347ca6a967731b742fda`.
브랜치 `codex/newsflow-ux-video-app`. 로컬 구현·검증만 수행; 원격 push 및 PR #35 변경 없음.

## 구현 결과

색상만 바꾸던 기존 홈에서 전용 대시보드 템플릿으로 변경했다. 지구 배경, 상단 검색, SVG 선형 아이콘, 4개 현황 카드, 뉴스 / 워크플로 / 영상 미리보기의 3열 구조, 실제 기록 차트를 구현했다. 1920에서는 여유 있는 3열, 1366에서는 압축된 3열, 모바일에서는 제작 중심 단일 열로 배치한다. 세로 스크롤은 유지하며 한 화면에 억지로 모든 내용을 축소하지 않는다.

- 검색은 보관 기사 범위이며, 분야 버튼은 기존 `/news`의 한국어 카테고리 계약에 연결했다.
- 7일 KST 수집·생성 차트와 작은 추이 그래프는 DB 기록을 읽는다. 미래/실패/완료시각 없는 영상은 완료 추이에 포함하지 않는다. 0건이면 0건으로 표시한다. 조회수·성장률·수익·유행도를 만들지 않는다.
- 최근 대본 일부와 실제 작업 상태를 표시하며 기존 작업실을 연다. 기존 제작 폼을 공통 partial로 추출해 재사용한다. 진행 작업이 있으면 새 제작 설정을 접으며 주 행동 버튼으로 바로 연다.
- 최근 영상 썸네일 선택은 실제 MP4 플레이어, 대본·자막 편집, 검토·다운로드·플랫폼 준비 링크를 함께 변경한다. 자동 재생·제작·승인·게시 요청은 발생하지 않는다. AI 장면/검토용 초안 안내도 선택 영상에 맞게 바뀐다.
- 기존 관리 대시보드 `/dashboard`는 그대로 유지한다. 새로운 홈은 `creator_dashboard.html`이다.
- 사용 중인 설정·승인·비용·개별 작업 값·DB schema·제작 엔진은 변경하지 않는다.

## 이미지와 시각 자료

주제 이미지 4종을 디자인 이미지 생성 도구로 생성해 로컬 정적 자산으로 포함했다. 실제 기사 사진을 다운로드하지 않았으며 화면에 **주제 이미지 · 실제 보도 사진 아님**을 표시한다. 기존 지구 배경은 재사용한다.

아래 캡처는 실제 Chromium 실행 화면이다. 숫자와 대본은 격리 DB의 합성 자료이며, 30초 1080×1920 무음 MP4 역시 디자인 데모이다. 예시 영상은 AI 주제 이미지를 로컬 FFmpeg로 합성했다. 실제 보도 영상, 유료 공급사 출력 또는 음성 품질을 의미하지 않는다. 이 fixture는 제작 엔진에 등록하지 않았다.

- [기존 화면](evidence/mockup-alignment/home-1920.png)
- [참고 목업](evidence/mockup-alignment/design-reference.png)
- [실제 새 홈 1920×1080](evidence/dashboard-implementation/home-1920.png)
- [실제 새 홈 1366×768](evidence/dashboard-implementation/home-1366.png)
- [실제 새 홈 390×844](evidence/dashboard-implementation/home-390.png)
- [홈에서 제작 설정 펼치기](evidence/dashboard-implementation/creation-open-1366.png)
- [제작 화면](evidence/dashboard-implementation/create-1366.png)
- [설정 화면](evidence/dashboard-implementation/settings-1366.png)

목업과 픽셀 단위로 같다는 판정은 하지 않는다. 가상 수치·계정·분석 기능 대신 실제 보유 기능·기록을 표시하므로 내용과 일부 비율은 다르다. 기사 제목은 좁은 카드에서 말줄임하며 기사 상세로 전체 내용을 확인한다.

## 검증

Cloud Linux / Python 3.12.14 / Chromium 151. 실제 Windows 실행이나 Windows 배율 검증이 아니다.

최종 코드 범위 회귀: **62 passed / 0 failed / 0 skipped / 1 warning**. 변경 Python 파일 Ruff PASS, pip check PASS. 기존 Starlette/httpx deprecation warning 1건은 남아 있다.

[pytest 로그](evidence/dashboard-implementation/pytest.log) · [JUnit](evidence/dashboard-implementation/pytest.xml) · [Ruff](evidence/dashboard-implementation/ruff.log) · [pip check](evidence/dashboard-implementation/pip-check.log)

브라우저 확인: 홈·제작·설정·영상 목록·편집·게시 준비 × 1366×768, 1920×1080, 390×844 = 18개 화면 모두 HTTP 200, 가로 넘침 없음. 검사 대상의 보이는 말단 텍스트 중 12px 미만 없음. 키보드 제작 폼 열기/닫기·포커스, 차트 날짜 선택, 영상 전환·재생과 편집/게시 대상 연결을 테스트한다. 모든 요소의 접근성 인증이나 실제 사용자 평가를 완료했다는 뜻은 아니다.

[브라우저 측정 기록](evidence/dashboard-implementation/audit.json)

## 수정한 결함과 검증 과정

- 뉴스 분야 링크가 내부 제작 코드(it/world 등)를 쓰면 기존 검색 라우트가 422를 반환했다. 기존 한국어 분류 계약에 맞췄다.
- 기존 관리 대시보드와 새 홈 템플릿 이름 충돌을 발견해 새 홈 이름을 분리하고 이전 템플릿을 원상 보존했다.
- 새 홈에서 빠졌던 AI 장면/검토용 고지 및 음성·뉴스 준비 상태 안내를 복구했다.
- 기존 CSS가 검색창을 두 줄로 배치하던 충돌, 모바일의 작은 글자/날짜 버튼 크기를 보완했다.
- 초기 범위 테스트에는 UI 변경에 따른 기대값 차이와 위 누락으로 실패가 있었다. 마지막 재실행 전 추가한 분야 테스트의 미설치 bs4 의존을 표준 라이브러리로 교체했다. 테스트를 삭제하거나 skip하지 않았다.

## 범위와 안전 경계

- 앱의 OpenAI/Claude/ElevenLabs/Higgsfield API·OAuth·SNS 실제 호출: **0건**. 디자인 이미지 도구는 **1회** 사용했으며 앱 API 실행과 구분한다.
- 격리된 기존 demo 경계가 외부 네트워크/인증/게시를 차단한다. 브라우저 외부 요청 0건. 테스트는 Fake·임시 데이터만 사용했다.
- 운영 앱·사용자 DB·DPAPI 키·기존 MP4·설정에 접근하거나 재시작하지 않았다. 자체 임시 데모 서버만 실행했다.
- 기존 전체 회귀 **57 FAIL** 기록 유지. 이번 범위 통과를 전체 회귀 PASS로 확대하지 않는다.
- Windows 11 / Python 3.14 / 실제 한국어 음질·자막 싱크 / 실제 API 콘텐츠 / 실계정 게시: **NOT VERIFIED**. Windows Actions 신규 실행도 하지 않았다.

## 재현

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs tests/test_dashboard_view.py tests/test_blue_studio_browser.py tests/test_single_workspace.py tests/test_creator_ui.py tests/test_settings_streamlined_browser.py tests/test_creator_scene_browser.py tests/test_settings_simplification.py tests/test_cloud_workspace_flow.py
```

새 비운 임시 디렉터리에서만 디자인 fixture를 실행한다. 기존 `tools/ui_preview.py`의 외부 호출 차단을 재사용한다. Cloud 브라우저 검토 도구이며 Linux 운영 배포 기능이 아니다. FFmpeg와 Noto CJK 글꼴이 필요하다.

```bash
.venv/bin/python docs/reports/evidence/dashboard-implementation/preview_fixture.py --data-dir /tmp/newsflow-design-fresh --port 47963
```

사용자가 승인한 로컬 구현 범위에서 종료한다. 원격 PR 상태를 재설정하거나 신규 기능 개발을 이어가지 않는다.
