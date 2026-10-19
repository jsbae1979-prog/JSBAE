# 첨부 워크플로 카드 구현

2026-10-19 KST. 기준 `24b574a`, 최종 검증 코드 `044b56ed1764942bb4a0375d9b44def1f8d6ead5`.
로컬 브랜치 `codex/newsflow-ux-video-app`. 원격 push·PR #35 수정·main 병합 없음.

## 구현

첨부 카드의 5단계 원형 진행 표시, 청록색 연결선·완료 체크, 파란 현재 단계, 제목 행·파형 장식, 4개 옵션, 하단 대본 미리보기와 작업실 버튼을 HTML/CSS/SVG로 구현했다. 이미지 전체를 클릭 불가능한 배경으로 붙이지 않았다. 새 엔진·DB migration·설정 저장 경로는 만들지 않았다.

- 기존 작업·분석·대본·렌더 기록을 읽는 표시용 projection만 추가했다. 성공 기록 없는 분석은 완료 체크하지 않는다. 실패·중단 단계는 붉은 확인 표시이며, 대본 검토 대기는 대본 단계로 남긴다.
- 뉴스·대본 AI, 음성, 영상, 대본 검토는 해당 작업 기록에서 읽는다. 전역 기본값을 바꿔도 기존 작업 표시는 바뀌지 않는다. 기존 선택 기록이 없으면 미정 또는 종전 검토 정책으로 표시한다.
- 네 옵션은 **기존 작업의 읽기 전용 상세 기록**을 펼친다. 대본 검토 스위치 모양도 저장 상태를 표시하며 누르면 설명이 열린다. 기존 작업의 검토·API 승인을 바꾸는 입력이 아니다. 새 작업의 선택은 기존 제작 폼에서 그대로 변경한다.
- 펼침은 클릭·Enter, 닫기는 Escape·바깥 클릭, 한 번에 한 패널만 열리며 Escape로 해당 요약에 포커스를 돌린다.
- 작업실 버튼은 해당 대본/작업으로 연결한다. 파형은 aria-hidden 정적 장식이며 음성 생성·재생·품질·진행률을 의미하지 않는다.
- 데스크톱 옵션은 한 줄, 모바일은 가독성을 위해 두 줄이다. 첨부 이미지의 작은 글자를 그대로 고정하지 않아 픽셀 단위 동일성을 주장하지 않는다.

## 실제 브라우저 증거

아래는 합성 Claude 분석·대본 기록과 Windows 음성 **선택 기록**을 넣은 격리 DB의 실제 Chromium 화면이다. 실제 Claude 요청·Windows 음성 실행을 하지 않았다.

- [1920×1080 카드](evidence/workflow-card/workflow-1920.png)
- [1366×768 카드](evidence/workflow-card/workflow-1366.png)
- [390×844 카드](evidence/workflow-card/workflow-390.png)
- [전체 홈](evidence/workflow-card/home-1920.png)

## 검증

Cloud Linux / Python 3.12.14 / Chromium. 관련 범위 pytest 최종 결과는 [로그](evidence/workflow-card/pytest.log), [JUnit](evidence/workflow-card/pytest.xml)에 보존한다.
**최종 코드 관련 범위: 36 passed / 0 failed / 0 skipped / 1 warning (43.59초).** 기존 Starlette/httpx deprecation warning은 유지된다. 변경 Python 파일 Ruff PASS, git diff --check PASS.

```bash
# /workspace/JSBAE에서 실행
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium newsflow-ai/.venv/bin/python -m pytest -q -rs newsflow-ai/tests/test_workflow_card.py newsflow-ai/tests/test_dashboard_view.py newsflow-ai/tests/test_single_workspace.py newsflow-ai/tests/test_blue_studio_browser.py
```

세 크기에서 가로 넘침 없음·옵션 이름 전체 표시, 완료/현재 단계, 상세 패널 키보드 조작·포커스, 작업실 이동, 전역 설정 불변, 기존 대본 검토 상태 보존을 확인한다. 브라우저 상세 조작 POST 0건·외부 요청 0건을 assertion으로 확인한다. 기존 뉴스 검색·제작 폼·영상 선택/재생·편집/게시 연결 회귀도 포함한다.

실제 유료 API·OAuth·SNS 호출 0건. 운영 데이터·키·MP4·앱 재시작 없음. 테스트용 격리 서버만 사용했다. 실제 Windows/Python 3.14·음질·공급사 품질·SNS 게시 **NOT VERIFIED**. 기존 전체 회귀 **57 FAIL** 기록을 유지하며 전체 PASS로 보고하지 않는다.

초기 시각 점검에서 1366 화면의 옵션 이름 말줄임과 모바일 줄 전환 임계값 문제를 발견했다. 열 비율·아이콘 폭·모바일 전환 기준을 수정하고, 알려진 짧은 옵션 이름의 scrollWidth/clientWidth 검사를 브라우저 테스트에 추가했다.
