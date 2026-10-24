# 실사형 콘셉트 이미지 선택 적용 검토

## 결과

[조건부 승인 의견](https://github.com/jsbae1979-prog/JSBAE/pull/35#issuecomment-6378433240)을 확인하고 사용자 ZIP의 4종을 직접 열어 검토했다. **홈·빈 영상 보관함 2곳만 적용**했다. 실제 기사 사진, 저장 영상 썸네일, 편집기 미리보기는 교체하지 않았다.

- 기준 SHA: `fbadd460d3005fca5c5aa613a78fd7c926c87be6`
- 검증 코드 SHA: `d8090dee7894597114f318553556f0ca521f0924`
- 브랜치: `codex/newsflow-ux-video-app`, 기존 [PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35) Draft 유지
- 자료 전용 커밋의 최종 SHA는 PR 결과 댓글에 기록한다.

## 4종 비교와 선택

| 자산 | 기존 화면과 비교 | 결정 |
|---|---|---|
| `hero_news_studio.webp` | 기존 지구 배경보다 뉴스 제작 공간이라는 정체성이 구체적이다. 화면 속 모니터를 실제 도구로 오해하지 않도록 제목과 기능 영역에서 분리한다. | 홈 헤더에만 적용. 한글 제목 아래 차분한 배경·그라데이션, 설명은 별도 HTML. |
| `news_analysis_studio.webp` | 모니터 속 가상 뉴스·차트가 실제 기사 목록/분석 결과와 시각적으로 경쟁한다. 기존 기사 이미지·출처와 설명용 지도는 정보 역할이 명확하다. | 미적용. 뉴스 자료/대본 화면과 실제 기사 이미지를 보존. |
| `video_editing_studio.webp` | 이미지 속 편집기·파형·다중 모니터가 실제 편집기 또는 현재 영상 산출물처럼 보일 수 있다. 기존 영상 캔버스와 실제 미리보기를 대체할 이점이 부족하다. | 미적용. 기존 편집기·실제 MP4·장면 컨트롤 보존. |
| `media_gallery_studio.webp` | 기존 Storyflow SVG보다 홈과 소재·조명 톤이 일관되고 세로 콘텐츠 보관함의 느낌을 전달한다. 단 SVG 5,057 bytes보다 무겁다. | **빈 보관함에만** 적용. 빈 상태 문구와 첫 제작 버튼을 우선하고, 실제 영상 카드에는 적용하지 않음. 기존 SVG 파일 자체는 삭제하지 않음. |

두 이미지에 **“AI 생성 콘셉트 이미지 · 실제 보도 사진 아님”**을 읽을 수 있는 HTML 캡션으로 표시했다. 이미지 `alt=""`는 장식임을 나타내고 캡션은 접근성 트리에 남는다. 이미지 안의 모니터는 앱 UI가 아니며 클릭 동작이 없다. 제목·메뉴·입력·상태·버튼은 기존 HTML/CSS를 유지했다. 이미지가 기사 근거나 영상 소재로 자동 선택되는 경로는 없다.

## 로딩·반응형

사용자 WebP 원본에서 로컬 리사이즈/재인코딩만 했다. 새 이미지 생성·유료 API는 사용하지 않았다. 원본 4종의 해시는 [목록](evidence/photoreal-studio/supplied-assets.json), 적용 파생본 정보는 [provenance](../../src/newsflow/static/images/studio-concepts/provenance.json)에 있다.

| 이미지 | 원본 | 512px | 1024px |
|---|---:|---:|---:|
| 홈 | 198,466 bytes | 27,168 | 78,102 |
| 갤러리 | 160,642 bytes | 23,410 | 64,008 |

`srcset/sizes`, 고정 width/height, 비동기 디코딩을 사용한다. 홈은 첫 화면 이미지, 빈 보관함은 lazy loading이다. 좁은 화면은 작은 후보를 사용하며 홈 배경 밝기를 낮춰 한글을 읽기 쉽게 했다. 갤러리 이미지 폭은 모바일 240px로 제한했다. 고밀도 디스플레이의 선택은 브라우저에 맡긴다.

로딩 검사에서 홈의 이전 2,361,213-byte 지구 배경이 불필요하게 함께 요청되는 것을 발견해 해당 배경 요청을 제거했다. 최종 감사에서 홈은 새 WebP만 요청한다. 뉴스/영상 편집의 기존 이미지 자산은 유지했다. 실측 전체 앱 전송량이나 네트워크 속도 개선 수치로 확대하지 않는다.

## 전후 화면

Cloud Chromium 실제 뷰포트, 임시 합성 DB와 Fake 공급사. 아래는 화면 크기별 직접 열 수 있는 PNG다. 운영 PC·실제 뉴스·생성 품질 검증 자료가 아니다.

| 화면 | 1366×768 | 1920×1080 | 390×844 |
|---|---|---|---|
| 홈 | [전](evidence/photoreal-studio/before/home-1366.png) · [후](evidence/photoreal-studio/after/home-1366.png) | [전](evidence/photoreal-studio/before/home-1920.png) · [후](evidence/photoreal-studio/after/home-1920.png) | [전](evidence/photoreal-studio/before/home-390.png) · [후](evidence/photoreal-studio/after/home-390.png) |
| 빈 보관함 | [전](evidence/photoreal-studio/before/empty-library-1366.png) · [후](evidence/photoreal-studio/after/empty-library-1366.png) | [전](evidence/photoreal-studio/before/empty-library-1920.png) · [후](evidence/photoreal-studio/after/empty-library-1920.png) | [전](evidence/photoreal-studio/before/empty-library-390.png) · [후](evidence/photoreal-studio/after/empty-library-390.png) |

[모바일 빈 보관함 전체 길이](evidence/photoreal-studio/after/empty-library-390-full.png)는 스크롤 아래의 이미지·캡션을 보기 위한 추가 자료이며 위의 실제 뷰포트 캡처와 구분한다.
뉴스·영상 편집·기존 영상 목록의 전후 캡처도 같은 before/after 폴더에 보존했다. 해당 화면에는 새 콘셉트 이미지가 나타나지 않는 것을 검사했다.

## 테스트 결과

| 검증 | 결과 |
|---|---|
| 별도 Cloud 실제 서버/Chromium 감사 | **PASS: 2 passed / 0 failed / 1 warning**. 4개 화면×3크기 및 빈 보관함×3크기. HTTP 200, 문서 가로 넘침 0, 외부 요청·POST·JS 오류 0. 이미지 로딩·캡션/제목 비겹침·빈 상태 키보드 제작 진입 확인. |
| 관련 회귀 24개 | **FAIL: 20 passed / 4 failed / 1 warning**. 전체 PASS가 아님. |
| 동일 기준 커밋의 24개 비교 | **20 passed / 동일 4 failed / 1 warning**. 같은 Python 3.12.14·동일 venv 의존성·동일 pytest 명령과 테스트 파일. 실패 ID 및 실패 assertion 모두 동일, 비교 범위 신규 실패 0. |
| 데이터 보존 | 합성 대본/작업/설정 레코드와 합성 영상 파일 해시 동일. 운영 데이터 접근/변경 없음. |
| `git diff --check`, `pip check` | PASS. pip 캐시 경로 권한 경고로 캐시 비활성화; 의존성 충돌 없음. |
| 전체 회귀 | 재실행하지 않음. **기존 57 FAIL 기록 유지**. 이번 4건을 그 57건과 일대일 대응했다고 주장하지 않음. |
| Windows·Windows Actions | **NOT VERIFIED**. 표시/정적 에셋 한정으로 Cloud 검증했고 `[skip ci]`로 광범위 CI를 반복하지 않음. |

[최종 화면 감사](evidence/photoreal-studio/after/audit.json) · [브라우저 로그](evidence/photoreal-studio/final-browser.txt) · [최종 범위 테스트](evidence/photoreal-studio/final-scoped.txt) · [기준 범위 테스트](evidence/photoreal-studio/baseline-scoped.txt) · [실패 비교](evidence/photoreal-studio/failure-comparison.json)

4건은 `/create`의 과거 단계 문구 “자료 준비” 기대 1건과 `/ai`의 과거 빈 미리보기 문구 “영상이 준비되면” 기대 3건이다. 미유효 영상의 미리보기를 제공하지 않는 검사는 통과하고 문구 검사에서 실패했다. 이번 이미지 변경에서 해당 화면·테스트·서비스를 수정하거나 skip하지 않았다. 경고는 기존 Starlette TestClient/httpx deprecation이다.

### 재현

프로젝트 루트에서 격리 환경으로 실행한다.

```sh
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
 NEWSFLOW_STUDIO_POLISH_EVIDENCE=/tmp/newsflow-photoreal-polish \
 .venv/bin/python -m pytest -q -rs tests/test_creator_ui.py \
 tests/test_studio_design_system.py tests/test_studio_dashboard_polish.py

PYTHONPATH=tests NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
 UX_PHASE=after UX_EVIDENCE=/tmp/newsflow-photoreal-recheck \
 .venv/bin/python -m pytest -q -rs docs/reports/evidence/photoreal-studio/test_visual_audit.py
```

기준 비교는 `git archive fbadd460...`의 src/tests/pyproject를 `/tmp/newsflow-photoreal-baseline`에 읽기 전용 기준으로 추출하고 동일 venv에서 그 src를 PYTHONPATH로 지정했다. 기존 작업 트리를 checkout/reset하거나 변경하지 않았다. 테스트 파일의 바이트 동일성도 확인했다.

## 변경 파일·보존·한계

- `src/newsflow/gui/templates/creator_dashboard.html`: 홈의 장식 이미지와 명시적 캡션.
- `src/newsflow/gui/templates/video_library.html`: 빈 보관함에만 장식 이미지와 캡션.
- `src/newsflow/static/css/studio-system.css`: 해당 두 구역의 크기·밝기·여백·반응형, 기존 홈 배경 요청 제거.
- `src/newsflow/static/images/studio-concepts/`: 최적화 WebP 4개(두 이미지×두 크기)와 출처·변환·해시 정보.
- 본 보고서 및 `docs/reports/evidence/photoreal-studio/`의 전후 캡처·감사·로그.

기존 함수·DB·설정·API·OAuth·게시 승인·실제 MP4·마이그레이션 변경 없음. 운영 앱 재시작·운영 PC 반영·main 병합 없음. 실제 유료 이미지/AI API·실계정·SNS 호출 0건. GitHub 코드 보존과 PR 보고만 수행한다.

실제 Windows의 화면 배율·색 표현·브라우저, 실제 영상 재생·한국어 음질·공급사 품질·실계정 게시는 NOT VERIFIED다. 합성 플레이어의 로딩 표시를 실제 MP4 재생 성공으로 기록하지 않는다. 제출 후 추가 개발 없이 중단한다.
