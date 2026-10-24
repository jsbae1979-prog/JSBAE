# 여섯 작업실 외형 보완 및 검증

기준: 2026-10-19 KST. 비교 기준 `f9442b36256dbc48ba4544cc0c60e327aaf7b9c5`.
검증 코드: `03abeadfae9bc95fbc46a33c20dd0e983f7e5aad`.
브랜치: `codex/newsflow-ux-video-app`. 원격 push·PR #35 변경·main 병합 없음.

## 판정 범위

**여섯 화면의 시각 구성 보완을 구현했다. 원본 목업의 모든 요소를 완전히 충족했다고 판정하지 않는다.**
기능·브라우저 통과와 외형 일치도는 다른 항목이다. 아래 전후 자료는 실제 앱 캡처이며, 목업을 앱 화면 위에 덮어 씌운 결과가 아니다.

- [전후 비교 보기 — 원본 크기 링크 포함](evidence/studio-fidelity/review.html)
- [브라우저 감사 결과](evidence/studio-fidelity/browser-audit.json)
- [SHA·환경·스크린샷 해시](evidence/studio-fidelity/manifest.json)

원본 참고 이미지는 채팅에 첨부된 6화면 합성 이미지로 육안 참조했다. 원본 UI의 폰트·아이콘 소스·영상 자산 및 원본 화면별 1920×1080 파일은 이 저장소에 없다. 픽셀 diff나 정량 유사도 점수는 측정하지 않았고 임의 점수를 만들지 않았다.

## 화면별 변경과 남은 차이

|화면|이번 구현|목업과 남은 차이|
|---|---|---|
|뉴스 수집|분야 탭, 접히는 상세 검색, 출처 타일, 좁은 기사 행, 네트워크 지도, 우측 수집 상태|등록된 실제 출처만 표시. 목업의 매체 로고·실시간 트렌드 순위를 임의로 채우지 않음|
|AI 대본|자료/요약·대본 편집·장면 구성 3열, 단계 표시, 선택 동기화, 현재 내레이션 복사, 스크롤 편집 영역과 저장 버튼|목업의 톤·스타일 목록을 실제 지원 없이 추가하지 않음. 장면별 편집 폼이므로 목업의 연속 대본과 구성 차이 있음|
|영상 제작|좌측 음성·소재, 중앙 실제 MP4·3개 타임라인, 우측 장면·내보내기, 설명 접기|실제 저장된 9:16 영상 사용. 목업의 앵커 영상, BGM/효과 트랙, 아바타 음성 목록과 동일하지 않음|
|게시 허브|4개 플랫폼별 아이콘·색상, 썸네일 행, 검토 상태, 게시 준비, 달력·추천 경로|승인 전 상태 유지. 목업처럼 실제 연결·업로드 성공·예약 실행 중으로 표시하지 않음|
|성과 분석|콤마 숫자, compact KPI, 날짜 축을 포함한 선/영역 차트, 추천 패널과 성과 기록|실제 지표 모델을 사용. 목업의 카테고리 막대·수익 성장률·확정 수익과 동일하지 않음|
|설정·자동화|한 탭만 노출, 선택/모델과 연결 준비 상태를 2열 분리, 저장 경로 보존|허구의 사용자 프로필·Pro 구독 요금·모든 서비스 키 등록 상태를 표시하지 않음|

색상·사이드바·번호 제목·밀도·패널 테두리·모서리·아이콘·입력란 높이를 공통 스타일로 맞췄다. 사용자 승인된 대시보드는 변경하지 않았다.
서비스 엔진·DB·migration·API 인증/비용/승인 정책은 변경하지 않았다. 일부 설명은 관련 details 안으로 옮겼으며 필수 동의 입력과 서버 검사는 유지했다.

## 실제 화면

|화면|1920×1080|1366×768|390×844|
|---|---|---|---|
|뉴스|[보기](evidence/studio-fidelity/news-1920.png)|[보기](evidence/studio-fidelity/news-1366.png)|[보기](evidence/studio-fidelity/news-390.png)|
|대본|[보기](evidence/studio-fidelity/script-1920.png)|[보기](evidence/studio-fidelity/script-1366.png)|[보기](evidence/studio-fidelity/script-390.png)|
|영상|[보기](evidence/studio-fidelity/video-1920.png)|[보기](evidence/studio-fidelity/video-1366.png)|[보기](evidence/studio-fidelity/video-390.png)|
|게시|[보기](evidence/studio-fidelity/publish-1920.png)|[보기](evidence/studio-fidelity/publish-1366.png)|[보기](evidence/studio-fidelity/publish-390.png)|
|성과|[보기](evidence/studio-fidelity/analytics-1920.png)|[보기](evidence/studio-fidelity/analytics-1366.png)|[보기](evidence/studio-fidelity/analytics-390.png)|
|설정|[보기](evidence/studio-fidelity/settings-1920.png)|[보기](evidence/studio-fidelity/settings-1366.png)|[보기](evidence/studio-fidelity/settings-390.png)|

설정은 `#connections`, 게시 계정은 별도 `accounts-*`로 촬영했다. 모든 최종 캡처의 scrollY=0. 설정 패널의 청록색 테두리는 hash 이동 후 포커스 표시이며 키보드 접근성을 숨기지 않았다.
MP4는 기존 격리 preview 도구로 생성한 30초 1080×1920 무음 합성 자료다. 재생 후 1초 프레임을 실제 디코딩하고 일시 정지해 캡처했다. 사람의 음성 청취나 콘텐츠 품질 검증이 아니다.

## 재현 명령과 검증

Cloud Linux, Python 3.12.14, Chromium 151.0.7922.173. Windows/Chrome 실환경 또는 Windows 배율로 보고하지 않는다.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest \
 tests/test_studio_pages.py tests/test_studio_fidelity.py tests/test_social_ui.py \
 tests/test_blue_studio_browser.py tests/test_settings_streamlined_browser.py \
 tests/test_creator_scene_browser.py tests/test_single_workspace.py \
 tests/test_settings_simplification.py tests/test_creator_ui.py \
 tests/test_unified_publishing_gui.py tests/test_production_options_browser.py \
 -q -rs --junitxml=/tmp/newsflow-fidelity-03abead.xml
```

**최종 SHA 기준 99 passed / 0 failed / 0 errors / 0 skipped / 1 warning**, 128.24초. 경고는 기존 Starlette TestClient httpx 사용 중단 안내다. [JUnit 증거](evidence/studio-fidelity/pytest.xml) · [검증 요약](evidence/studio-fidelity/validation.json).

- Ruff: PASS. `ruff check src/newsflow tests/test_studio_fidelity.py tests/test_studio_pages.py tools/capture_social_ui.py`
- `pip check`: PASS, broken requirements 없음.
- `git diff --check`: PASS.
- 실제 브라우저 캡처: 7화면×3크기 = 21 PASS. 가로 넘침 0, 화면 밖 조작 요소 0, JavaScript 오류 0, 외부 요청 0, MP4 재생 오류 0.
- 기사 필터 펼치기·검색, 장면 키보드 선택, 편집 상태 복사/복사 거부 안내, 기존 작업 불변, 설정 저장·재진입·탭 이동·필수 입력, 기본 제작 선택과 별도 승인, 게시 준비 동선 포함.
- 전체 회귀는 이번 UI 변경에서 재실행하지 않았다. 기존 **57 FAIL 기록 유지**, 범위별 통과를 전체 PASS로 바꾸지 않는다.

중간 점검의 문제도 해결 후 구분했다: Cloud에 Google Chrome 배포판이 없어 3개 setup error가 발생했고, 기존 지원 환경변수로 설치된 Chromium을 지정했다. 최초 영상 필드 이동의 HTML 묶음 오류는 수정하고 실제 FormData/option 소속 검증을 추가했다. 접힌 뉴스 상세 필터는 테스트에서도 펼친 뒤 선택하도록 변경했다(기존 assertion 보존). 새 장면 테스트의 빈 fixture를 실제 합성 2장면으로 교정했다. 잘못된 테스트 파일 경로로 0건 실행된 한 명령은 검증 성공으로 포함하지 않았다.

## 보존·제한

- 실제 유료 API/OAuth/공급사 계정 조회/SNS 업로드/게시 0건. 브라우저 외부 요청도 0건.
- 기존 운영 DB·키·설정·영상 접근/변경 및 운영 앱 재시작 없음. 새 `/tmp` preview만 사용.
- 기본 음성·AI 모델의 전역 기본값/작업별 스냅샷, 대본 검토·외부 전송 동의·게시 승인은 그대로 유지.
- 원격 push·Actions 실행·PR 변경·main 변경 없음. 로컬 커밋만 보존.
- Windows 11/Python 3.14, 실제 SAPI 음질, 공급사 품질, 실계정·실제 성과·게시: NOT VERIFIED.
- 작은 화면은 단일 열, 터치 조작 크기 및 스크롤을 사용한다. 1366에서 일부 긴 우측 승인 설명은 패널 스크롤로 읽는다.
- 원본과 완전 일치 판정은 미확정이다. 남은 차이를 숨기거나 실제 서비스 성공을 조작해 목업에 맞추지 않았다.
