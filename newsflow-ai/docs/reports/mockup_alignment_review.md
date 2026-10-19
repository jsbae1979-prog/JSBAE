# 목업과 실제 화면의 레이아웃 차이 보정

2026-10-19 KST. 코드: `be0707a97edcd4a919fd7c1303a3964f3972eaef`.
기준: `49ce76b` / `codex/newsflow-ux-video-app`. 로컬 변경만 수행.

## 차이와 수정

앞선 구현은 색상·카드 스타일 위주였으며, 목업에 비해 배너 높이와 긴 폼의 비중이 컸다. 중앙 작업 현황과 오른쪽 미리보기·게시 준비가 아래로 밀려 목업의 주요 배치와 달랐다.

이번에는 상단 헤더를 낮추고, 데스크톱 사이드바·4개 현황 카드·3열 본문의 비율을 조정했다. 뉴스 / 작업 상태 / 영상 미리보기가 나란히 보인다. 카드 테두리·아이콘 크기·브랜드 표기와 태그라인도 정리했다.

- 진행 중인 작업이 있으면 중앙에서 실제 상태와 다음 행동을 먼저 표시한다.
- 새 제작 설정은 같은 화면의 펼침 영역으로 제공한다. 상단 ‘지금 영상 만들기’는 해당 영역을 펼치고 제목으로 키보드 포커스를 옮긴다. 생성 요청을 전송하지 않는다.
- 진행 작업이 없는 처음 사용 화면과 `/create`에서는 기존 폼이 바로 보인다.
- 영상 미리보기는 넓은 프레임 안에 원래 9:16 비율로 표시한다. 배경은 같은 썸네일의 흐림 표시이며 실제 영상 파일을 수정하지 않는다.
- 실제 완료 영상 3개의 썸네일 링크와 기존 편집·검토·게시 준비 링크를 근처에 배치했다. 사진·영상 자료를 외부에서 다운로드하지 않는다.
- 홈 작업 카드의 내부 Provider 상세 문구는 숨겼다. 기존 상세 화면·실행 기록에는 유지된다.
- 모바일은 기존 5개 메뉴와 단일 열을 유지한다.

엔진·API·DB·기본값·작업별 설정·유료 사용 동의·검토·게시 승인에는 변경이 없다. 임의 통계·차트나 TikTok 메뉴를 작동하는 기능으로 만들지 않았다.

## 시각 비교

- [디자인 목업 원본](evidence/mockup-alignment/design-reference.png) — 생성한 컨셉 이미지, 앱 실행 화면 아님.
- [보정 전 실제 화면](evidence/premium-workspace/home-1920.png)
- [보정 후 1920×1080](evidence/mockup-alignment/home-1920.png)
- [보정 후 1366×768](evidence/mockup-alignment/home-1366.png)
- [보정 후 모바일 390×844](evidence/mockup-alignment/home-390.png)

남는 차이: 목업의 예시 뉴스 사진·도시 영상·가상 차트는 실제 데이터가 아니다. 앱 화면에는 보유한 기사·실제 작업 상태·합성 무음 MP4가 보인다. 제작물 품질이나 전체 목업과의 시각적 동일성을 검증한 것으로 보고하지 않는다.

## 검증

Cloud Linux, Python 3.12.14, Chromium 151, 기존 격리된 UI demo와 Fake 어댑터. 사용자 운영 데이터를 사용하지 않았다.

- 중간 범위 실행: 41 passed / 0 failed / 0 skipped / 1 기존 Starlette-httpx 경고.
- 최종 코드 범위 실행: **57 passed / 0 failed / 0 skipped / 1 기존 Starlette-httpx 경고**, 101.37초. [pytest 로그](evidence/mockup-alignment/final-scoped.log), [JUnit 결과](evidence/mockup-alignment/final-scoped.xml).
- Ruff(변경 테스트) 및 `git diff --check`: PASS.
- 6개 주요 화면 × 3개 크기 = 18회 HTTP 200, 가로 넘침 0, 측정한 버튼 높이 44px 미만 0. [측정 결과](evidence/mockup-alignment/audit.json).
- 진행 작업이 있는 홈의 제작 설정 펼침·접힘, 상단 진입 후 키보드 포커스, 빈 홈의 즉시 제작 폼, 검색, 설정 저장·재진입, 장면 선택/순서, 실제 로컬 무음 MP4 재생, 기존 검토·게시 경로를 검사한다.
- 기존 Fake OpenAI/Claude→대본→검토→합성→Fake 게시 서비스 연결 검증을 재사용한다.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_BLUE_STUDIO_EVIDENCE=/tmp/newsflow-mockup-match/final-browser \
.venv/bin/python -m pytest -q -rs \
 tests/test_blue_studio_browser.py tests/test_settings_streamlined_browser.py \
 tests/test_creator_scene_browser.py tests/test_single_workspace.py \
 tests/test_settings_simplification.py tests/test_creator_ui.py \
 tests/test_cloud_workspace_flow.py \
 --junitxml=/tmp/newsflow-mockup-match/final-scoped.xml
```

범위 테스트 결과는 기존 전체 회귀의 57 FAIL과 별개다. 전체 회귀·기준 실패 비교를 다시 실행하지 않았다. 기존 실패 기록을 삭제하거나 테스트를 skip하지 않았다.

## 보존·미검증

실제 유료 API·OAuth·SNS 호출 0건. 브라우저 외부 요청 0건. DB·키·운영 설정·기존 영상 및 운영 앱은 변경하지 않았다. 테스트용 임시 서버만 실행·종료했다.

Windows PC·Python 3.14·Windows 배율·실제 음성 품질·공급사 품질·SNS 게시: **NOT VERIFIED**. 이번 변경은 로컬 코드와 검증 자료에만 보존했다. 원격 push, PR #35 변경, main/다른 브랜치 병합 및 운영 배포는 수행하지 않았다.
