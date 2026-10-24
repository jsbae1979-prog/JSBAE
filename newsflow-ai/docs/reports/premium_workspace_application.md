# NewsFlowAI 프리미엄 UI 실제 적용

- 기록: 2026-10-19 KST
- 적용 코드: `7b2c2949008fa6b2b04deef75c09f46498262e98`
- 시작 HEAD: `10162bc` / 브랜치: `codex/newsflow-ux-video-app`
- 범위: 기존 앱의 로컬 UI 구현·검증. 원격 push, PR #35 변경, 병합, 배포 없음.

## 적용 결과

생성한 디자인 시안의 색상·빛 효과·카드·아이콘·버튼을 실제 Jinja 화면에 적용했다. 시안 이미지를 화면 전체에 붙인 것이 아니라 기존 입력·저장·검토·편집 동작이 유지되는 HTML/CSS다.

- 딥 네이비 배경, 반투명 카드, 16px 모서리, 블루/시안 포인트와 절제된 그림자.
- 48px 아이콘 컨테이너, 일관된 SVG 선형 아이콘, 읽기 쉬운 한글 글꼴과 입력 컨트롤.
- 기존 생성 지구 이미지를 작업 헤더 배경으로 재사용. 사이드바의 중복 홍보 이미지 삭제.
- 상단 검색을 실제 **보관 기사 검색** 폼으로 통합. 신규 뉴스 검색으로 표시하지 않는다.
- 보관 뉴스 / 제작 폼과 진행 작업 / 세로 미리보기로 홈 구성. 작업 목록을 공통 템플릿으로 추출해 홈과 상세 화면에서 재사용한다.
- 최신 영상에 기존 대본·자막 수정, 영상 검토, 게시 준비 경로를 연결했다. 링크만으로 승인·생성·게시를 실행하지 않는다.
- 설정·영상 목록·편집·게시 화면에도 공통 카드·버튼·포커스 스타일을 적용했다.
- 감소된 모션 선호를 존중하고 모바일에서는 단일 열과 기존 5개 메뉴를 유지한다.

시안의 임의 매출·조회수·트렌드·증감률·차트·프로필·TikTok 기능은 추가하지 않았다. 카드 수치는 기존 DB 조회 결과다. 증거 화면의 기사와 숫자는 격리된 데모 자료이며 운영 데이터가 아니다.

백엔드 엔진, API 계약, DB migration, 설정 기본값, 작업별 설정 고정, 서비스별 동의·비용 검사, 대본/영상 검토 및 게시 승인은 변경하지 않았다.

## 화면 증거

아래 PNG는 실제 Cloud Chromium 화면의 원래 뷰포트 크기다. 전체 페이지를 작은 한 장으로 축소하지 않았다.

| 화면 | 이전 | 적용 후 |
| --- | --- | --- |
| 홈 1366×768 | [이전](evidence/ui-polish/home-1366.png) | [적용 후](evidence/premium-workspace/home-1366.png) |
| 홈 1920×1080 | 이전 자료 재사용 | [적용 후](evidence/premium-workspace/home-1920.png) |
| 모바일 홈 390×844 | [이전](evidence/ui-polish/home-390.png) | [적용 후](evidence/premium-workspace/home-390.png) |
| 설정 1366×768 | [이전](evidence/ui-polish/settings-1366.png) | [적용 후](evidence/premium-workspace/settings-1366.png) |
| 모바일 설정 390×844 | [이전](evidence/ui-polish/settings-390.png) | [적용 후](evidence/premium-workspace/settings-390.png) |
| 미리보기·편집 | [이전](evidence/ui-polish/editor-1366.png) | [적용 후](evidence/premium-workspace/editor-1366.png) |

추가: [제작](evidence/premium-workspace/create-1366.png), [내 영상](evidence/premium-workspace/library-1366.png), [게시 준비](evidence/premium-workspace/publish-1366.png).

## 검증

환경: Cloud Linux, Python 3.12.14, Chromium 151, 실제 로컬 FFmpeg/ffprobe. 운영 대상은 여전히 Windows 11이다.

- 최종 변경 범위 pytest: **PASS — 57 passed / 0 failed / 0 skipped / 1 warning**, 89.56초.
- Ruff(변경한 테스트 파일): PASS.
- `python -m pip check`: PASS, 의존성 불일치 없음. Cloud pip 캐시 경로 권한 경고는 별도로 발생했다.
- `git diff --check`: PASS.
- 6개 화면 × 3개 크기 = 18회 HTTP 200, 가로 넘침 0. 샘플링한 노출 텍스트 12px 미만 0, 버튼 44px 미만 0. [측정 JSON](evidence/premium-workspace/audit.json).
- 실제 브라우저에서 빈 화면/합성 자료, 검색 범위·URL 거부, 제작 옵션, 미등록/등록된 합성 키 상태, 설정 저장·재진입, 옛 링크 이동, 모달 포커스 복귀, 장면 선택·순서, MP4 재생, 편집·게시 준비 경로와 기존 승인 상태를 확인한다.
- Fake OpenAI/Claude 뉴스→분석·대본→검토→기존 합성→Fake 게시 서비스 연결 테스트를 재사용한다. 무음 MP4 성공은 렌더링·재생 검증이며 실제 음성·API 품질·SNS 성공을 뜻하지 않는다.
- 초기 41건 실행은 40 passed / 1 failed였으며, 실패 1건은 모바일에서 화면 아래의 지연 로딩 썸네일을 스크롤 없이 기다려 timeout이 났다. 테스트를 실제 스크롤 후 로딩 확인으로 수정했다. 이미지 확인·재생·보안 assertions를 삭제하거나 skip하지 않았다.
- 첫 범위 실행: 57 passed / 0 failed / 0 skipped / 1 기존 Starlette-httpx 경고. 최종 커밋의 재실행 결과는 아래에 별도 기록한다.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_BLUE_STUDIO_EVIDENCE=/tmp/newsflow-premium-live/final-browser \
.venv/bin/python -m pytest -q -rs \
 tests/test_blue_studio_browser.py tests/test_settings_streamlined_browser.py \
 tests/test_creator_scene_browser.py tests/test_single_workspace.py \
 tests/test_settings_simplification.py tests/test_creator_ui.py \
 tests/test_cloud_workspace_flow.py \
 --junitxml=/tmp/newsflow-premium-live/final-scoped.xml
```

브라우저 재현은 기존 `tools/ui_preview.py --data-dir <새 임시 디렉터리> --port 47943`와 [캡처 스크립트](evidence/premium-workspace/capture.py)를 사용한다. 실제 공급사 호출을 막는 기존 데모 격리를 유지한다. 캡처는 임시 디렉터리에만 저장한다.

## 범위와 제한

- 실제 유료 API/OAuth/SNS 호출: 0건. 이번 검증은 Fake 어댑터와 로컬 자료만 사용했다. 브라우저 외부 요청 0건; 외부 요청은 차단하도록 설정했다.
- 사용자 DB·키·설정·기존 영상 및 운영 앱: 접근·변경·재시작 없음.
- 기존 전체 회귀 57 FAIL 기록 유지. 전체 회귀를 다시 실행하지 않았으며 범위 테스트 성공을 전체 PASS로 표시하지 않는다. 기존 별도 UI navigation 테스트의 제거된 설정 모달 기대 불일치 기록도 유지한다.
- Windows 11 실환경, Python 3.14, Windows 화면 배율, 실제 한국어 음질, 공급사 품질, 실계정 게시: **NOT VERIFIED**.
- 모든 페이지·모든 상태의 완전한 접근성 인증은 수행하지 않았다. 주요 화면과 지정 뷰포트의 실제 동선·포커스·넘침 검사 결과다.
- 원격 PR #35와 원격 브랜치를 읽거나 변경하지 않았다. 로컬 적용을 운영 배포로 보고하지 않는다.

## 최종 코드 재검증

코드 `7b2c2949008fa6b2b04deef75c09f46498262e98`에서 **57 passed / 0 failed / 0 skipped / 1 warning**, 89.56초.

- [최종 pytest 로그](evidence/premium-workspace/final-scoped.log)
- [JUnit 결과](evidence/premium-workspace/final-scoped.xml)
- [환경·화면 메타데이터](evidence/premium-workspace/manifest.json)

검증 후에는 보고서와 증거만 추가했다. 코드 수정은 없다. 검증용 임시 서버는 종료했다. 신규 기능 개발이나 원격 반영 없이 작업을 종료한다.
