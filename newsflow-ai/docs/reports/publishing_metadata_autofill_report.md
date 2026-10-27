# 게시 문구 자동 채움 및 완료 변경 검토

- 작성: 2026-10-20 KST
- 기준: `5981077f3c315a83eb75443f550b0fb97add661a`
- 구현·검증 코드: `ade498859e953340a4fc147cc3c92a54bd8f485c`
- 브랜치: `codex/newsflow-ux-video-app` (로컬만 변경)

## 구현 범위

통합 게시 작업실 및 기존 YouTube/Instagram 게시 양식의 새 초안에 제목·설명·해시태그를 채운다. 완성 MP4에 연결된 `VideoProject.snapshot`의 요약과 `sources`의 출처를 사용한다. 제작 후 수정한 대본을 기존 MP4의 설명으로 잘못 가져오지 않는다.

이는 기존 자료를 복사·정리하는 로컬 자동 채움이다. 새로운 AI 광고 문구 작성이나 플랫폼별 독립 AI 생성 기능이 아니다. 요약의 미확인 표현을 그대로 보존하고 초안임을 표시한다. 해시태그는 제목에 이미 있는 단어 최대 4개로 제안한다. 새로운 사실·검색량·인기 표현을 만들지 않는다.

| 대상 | 기존 게시 엔진에 반영되는 항목 |
| --- | --- |
| YouTube | 제목, 설명·출처·해시태그, tags |
| Instagram | 제목·설명·출처·해시태그를 합친 캡션 |
| TikTok | 통합 작업실의 공통 문구를 기존 캡션 경로로 전달; 실제 연결·게시 차단 유지 |

카테고리, 공개 범위, 아동용 여부, AI 표시 판단, 브랜드·음악 사용 동의, 사실·권리 검토와 최종 게시 승인은 자동 선택하지 않는다. 앞선 YouTube 14개 카테고리 선택 기능을 유지한다. 실제 계정별 카테고리 허용 여부는 미검증이다.

## 보존 및 제한

- 이미 저장한 초안은 사용자 문구를 우선한다. 사용자가 설명·태그를 비워서 저장한 경우도 자동으로 다시 채우지 않는다.
- 화면을 열거나 플랫폼을 바꾸는 것만으로 저장·전송·승인하지 않는다.
- 계정 연결 전에는 기존 정책대로 초안 저장이 제한된다. 자동 채움이 계정 연결이나 게시 준비 완료를 의미하지 않는다.
- 출처 링크는 온전한 URL 단위로 포함한다. 길이·형식 때문에 포함하지 못한 링크는 안내하고 전체 원본 출처 기록은 유지한다.
- 캡션 길이에 여유를 두되, 사용자 수정 후의 플랫폼별 최종 검사는 기존 엔진이 담당한다.
- 민감정보로 의심되는 내용은 자동 채움을 중단한다. HTML은 기존 Jinja 이스케이프를 사용한다.
- DB migration, 전역 설정, 운영 데이터·키·영상, 게시 엔진·OAuth를 변경하지 않았다.
- 실제 공급사/API/OAuth/SNS 호출 0건. Fake 계정·업로드 및 임시 DB만 사용했다. 원격 push, PR #35 변경, main 변경 없음.

## 검증

Cloud Linux / Python 3.12.14 / Chromium의 결과이며 Windows 검증이 아니다.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_METADATA_EVIDENCE=/tmp/newsflow-metadata-evidence \
.venv/bin/python -m pytest -q -rs \
  tests/test_publish_metadata.py tests/test_publish_metadata_gui.py \
  tests/test_unified_publishing.py tests/test_unified_publishing_gui.py \
  tests/test_youtube_categories.py tests/test_youtube_category_gui.py \
  tests/test_youtube_gui.py tests/test_instagram_gui.py \
  tests/test_publishing.py tests/test_social_platforms.py \
  tests/test_publish_save_browser.py tests/test_youtube_upload.py \
  tests/test_instagram_live.py tests/test_tiktok_publishing_connection.py
.venv/bin/ruff check src tests
git diff --check
```

- PASS: **306 passed / 0 failed / 0 skipped / 1 warning**, 55.08초. 경고는 기존 Starlette/httpx 사용 중단 경고.
- PASS: Ruff, diff check.
- PASS: 자동 채움 → 플랫폼 변경 → 문구 수정 → 검토 저장 → 설정 화면 이동 → 게시 작업실 재진입. 저장 문구 보존 및 게시 동의 미체크 확인.
- PASS: 1366×768, 390×844에서 실제 Cloud Chromium 확인. 가로 넘침 없음. 이 결과는 Windows 화면 배율 검증이 아니다.
- PASS: 불확실성 표현·URL 보존, 긴 한글/Unicode 캡션, 안전하지 않은 출처 제외, 민감정보 자동 채움 차단, 저장 후 빈 입력 보존, 미검토/미승인 차단, 기존 플랫폼별 중복·결과 불명 보호 관련 회귀.
- 증거: `/tmp/newsflow-metadata-tests.txt`, `/tmp/newsflow-metadata-evidence/metadata-1366.png`, `metadata-390.png`.
- 전체 회귀는 반복하지 않았다. 기존 **57 FAIL** 기록을 유지하며 이번 범위의 통과를 전체 PASS로 확대하지 않는다.

## NOT VERIFIED

Windows 사용자 PC 적용, Python 3.14 및 Windows Actions의 이번 변경 실행, 실제 SNS 업로드·공급사 수락 결과, 실제 계정 권한 및 AI 생성 문구의 품질은 미검증이다. TikTok 실계정 연결·게시 차단은 그대로다.

완료 변경을 검토했으며 관련 범위에서 실패는 없었다. 검토 자료 작성 후 추가 개발을 중단한다.
