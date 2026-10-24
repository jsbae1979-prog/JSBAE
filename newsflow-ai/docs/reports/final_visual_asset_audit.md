# NewsFlow AI — 전체 주요 화면 최종 시각 감사

작성: 2026-10-24 13:10 KST. 대상: Draft PR #35 / `codex/newsflow-ux-video-app`.

**감사 완료. 대부분의 화면에는 추가 이미지가 필요하지 않다.** 기존 홈·빈 보관함 콘셉트 이미지와 대본 안내 SVG는 유지한다. 우선 개선 후보는 뉴스 목록의 기본 사진을 중립적 아이콘으로 바꾸는 것이며, AI 영상 절차도는 설명 정합성을 먼저 확인한 뒤 검토할 선택 후보다. 이번에는 새 이미지 제작·적용이나 제품 코드 수정을 하지 않았다.

- 감사 대상 SHA: `a3e9bad7ca46abc9a390166272a02f7c0f292f87`.
- 제품 코드 기준: `f6aedc5db10ac7df9e6ce7b2b7f8aab7f5c6bdac`. 두 SHA 사이 `newsflow-ai/src/` 차이 없음. 이후 차이는 CI·검증 도구·보고 자료다.
- 판정은 **시각 보조 요소의 적합성**에 관한 것이다. 기능 전체 PASS나 사용자 사용성 인수 판정이 아니다.
- 아래 ‘반영 권장 예’는 **후속 변경 후보**라는 뜻이며 이번에 반영했다는 뜻이 아니다. ‘적용 금지’는 가짜 콘텐츠·결과를 대신 보여주는 이미지 추가를 금지한다는 뜻이며, 실제 사용자 영상이나 편집 컨트롤을 제거하라는 뜻이 아니다.

## 화면별 판정

| 화면명 | 현재 상태 요약 | 판정 | 이유 | 추천 자산 유형 | 실제 반영 권장 여부 |
|---|---|---|---|---|---|
| 홈 / 메인 | 스튜디오 콘셉트 배경, 실제 HTML 제목·제작 진입, 실제 작업 목록. 콘셉트 표기 있음 | **적용 완료** | 브랜드와 제작 앱의 목적을 전달한다. 장식을 더 넣으면 제작 진입이 약해진다. 하단 기사 기본 썸네일 문제는 뉴스 항목 참조 | 없음 | 아니오 — 추가 이미지 없음 |
| 작업실 / 통합 작업 | 단계 링크, 작업 상태, 대본·영상·검토 영역과 실제 버튼 | **유지** | 진행 단계와 작업 산출물이 가장 중요한 시각 요소다. 사진을 추가하면 작업 내용과 경쟁한다 | 없음 | 아니오 — 추가 이미지 없음 |
| 뉴스 수집 / 뉴스 선택 | 검색·분류·출처·제목. 원본 대표 이미지가 없어도 사진형 분야 배경이 표시됨 | **개선 필요** | 사진형 기본 배경이 해당 기사 사진으로 해석될 여지가 있다. 더 화려한 뉴스 사진을 추가할 상황이 아니다 | **SVG — 기존 중립 뉴스/분야 아이콘 우선** | **예 — 원본 없는 기본 사진의 대체만 권장** |
| AI 분석 / 대본 작성 | 진입 화면에 기사→대본→세로 영상 안내 SVG, 결과에는 실제 텍스트·편집기. 모바일은 장식 SVG 숨김 | **적용 완료** | 이미 절차 이해를 보조한다. 결과 패널에 가짜 분석 그래프나 예시 대본 이미지를 더할 필요 없음 | 없음 | 아니오 — 추가 이미지 없음 |
| 음성 선택 | 제공 방식·준비 상태·선택·미리 듣기 조작 | **유지** | 사용자는 실제 음성과 준비 상태를 확인해야 한다. 가상의 성우 사진·항상 움직이는 파형은 잘못된 기대를 만든다 | 없음 | 아니오 — 추가 이미지 없음 |
| 영상 제작 | 실제 편집 폼, 9:16 배치 예시·안전 영역, 실제 결과 플레이어 | **적용 금지** | 스톡 영상/목업 편집 화면을 실제 출력 대신 넣으면 제작 완료·품질을 오인한다. 실제 로컬 소재·MP4·기능성 배치 안내는 유지 | 없음 | 아니오 — 추가 이미지 없음 |
| AI 영상 제작 | 기본/AI 방식 설명, 모델 준비 상태, 계획 폼과 장면 승인. 설명이 길고 모드 안내 일부가 혼재 | **개선 필요** | 텍스트 반복 일부를 짧은 절차 안내로 바꿀 여지는 있으나 먼저 선택 모드와 안내 문구를 일치시켜야 함 | **SVG — 비실사 절차 아이콘 + 실제 HTML 라벨** | **예, 조건부·낮은 우선순위 — 새 카드 추가 대신 반복 설명 대체** |
| 내 영상 / 영상 보관함 | 저장 영상의 실제 썸네일·상태·검토/편집 진입 | **유지** | 영상 자체가 핵심 시각 자료다. 실패·미완료 카드에 완성품처럼 보이는 사진을 채우면 안 됨 | 없음 | 아니오 — 추가 이미지 없음 |
| 게시 준비 | 플랫폼·계정 상태, 제목·설명·승인과 파일 정보 | **유지** | 플랫폼 아이콘과 명확한 상태면 충분하다. 장식이 승인 범위를 가리지 않아야 함 | 없음 | 아니오 — 추가 이미지 없음 |
| 게시 결과 | 플랫폼별 성공·대기·실패·결과 불명 상태 | **적용 금지** | 가짜 게시물 화면·조회수·성공 차트·축하 이미지는 실제 결과와 혼동된다. 서버 결과를 반영한 상태 UI만 유지 | 없음 | 아니오 — 추가 이미지 없음 |
| Instagram 피드 제작 | 기사 선택, 실제 초안/카드 제작 입력, 검토·승인 안내 | **유지** | 콘텐츠 미리보기와 입력이 중심이다. Instagram 계정·좋아요·댓글 목업은 결과처럼 보이며, 긴 폼도 추가 사진으로 해결되지 않음 | 없음 | 아니오 — 추가 이미지 없음 |
| 설정 / API 연결 | AI·음성·영상·비용·계정의 상태와 변경 조작. AI 영상에는 기존 준비 단계 안내 | **유지** | 입력과 다음 행동이 중요하다. 연결 완료처럼 보이는 보안 방패나 공급사 콘솔 이미지를 추가하지 않음 | 없음 | 아니오 — 추가 이미지 없음 |
| 빈 영상 보관함 | 콘셉트 이미지, 실제 영상이 없다는 문구, 첫 제작 버튼 | **적용 완료** | 실물 영상 목록과 분리되어 첫 사용 안내에 적합하다. 다른 빈 상태까지 복제할 필요 없음 | 없음 | 아니오 — 추가 이미지 없음 |
| 기타 빈 상태 | 기사 없음·작업 없음에 아이콘, 이유, 다음 행동 | **유지** | 목록 공간을 이미지로 채우기보다 검색 변경·수집·첫 제작 진입을 명확히 하는 편이 낫다 | 없음 | 아니오 — 추가 이미지 없음 |
| 오류 상태 | 오류 원인과 복구 행동, 색상과 텍스트 | **유지** | 해결 방법이 중심이다. 고장 난 로봇 등 큰 삽화는 복구 조작을 밀어낸다 | 없음 | 아니오 — 추가 이미지 없음 |
| 차단 상태 | 키/모델/동의 미준비 이유, 설정 이동, 비활성 조작 | **유지** | 연결·생성 완료로 보이는 이미지보다 다음에 할 구체적 행동을 보여야 한다 | 없음 | 아니오 — 추가 이미지 없음 |

## 우선 개선 후보와 오인 위험

### 1. 뉴스 기본 썸네일: 새 실사 이미지 대신 중립 표시

[현재 뉴스 1920 화면](evidence/final-visual-audit/screens/news-1920.png)에서 원본 썸네일 없는 합성 기사 옆에 사진형 도시/분야 배경이 나타난다. 홈 뉴스 목록에도 같은 계열의 기본 배경이 있다. 이것은 실제 사용자 오인이 입증됐다는 뜻은 아니지만, 현재 요청의 ‘실제 보도 사진처럼 오해될 이미지 금지’ 원칙에 비추어 개선할 여지가 있다.

근거:

- `src/newsflow/gui/templates/news.html:8`: 원본 이미지가 없는 기사에도 `.suite-topic-art` 배경을 표시한다.
- `src/newsflow/gui/templates/news_thumbnail.html`: 출처 제공 대표 이미지가 있는 경우에만 실제 `<img>`를 삽입한다.
- `src/newsflow/static/css/studio-pages.css:37`, `dashboard.css:66`: 사진형 `news-topic-atlas.png`를 기본 배경으로 사용한다.
- `src/newsflow/static/js/news-thumbnails.js`: 원본 이미지 로딩 실패 시에도 기본 배경이 드러날 수 있다.
- 항상 보이는 문구는 “보관 기사 검색 · 대표 이미지는 목록 미리보기용”이다. 더 명확한 “기본 주제 이미지는 실제 보도 사진이 아닙니다”는 접힌 “자료·점수·이미지 안내” 내부에 있다 (`news.html:18`).

후속 권장: **원본 이미지 없음/로딩 실패 상태만** 기존 뉴스·분야 SVG 아이콘으로 대체하고, 필요한 경우 실제 HTML로 짧게 “분야 아이콘”을 표기한다. 출처 제공 대표 이미지와 기존 권리·재사용 정책은 그대로 둔다. 새 사건 사진, 공급사 이미지 API, 기사별 추정 이미지는 필요하지 않다. 이번 감사에서는 변경하지 않았다.

### 2. AI 영상: 문구 정합성 확인 후 작은 절차도 선택 검토

[현재 AI 영상 전체 화면](evidence/final-visual-audit/screens/ai-video-1366-full.png)의 `video_ai.html`에는 아래 문구가 함께 있다.

- 선택 항목: “전체 AI 영상 — 모든 장면 Higgsfield”
- 방식 설명: “고른 장면만 유료 생성”
- 하단 설명: “기본은 카드이며 … 첫 훅 장면을 AI 후보로 배정합니다”

이 감사는 문구가 혼재한다는 **화면 관찰**이다. 어느 엔진 동작이 맞는지 추측하거나 승인 정책을 수정하지 않는다. 선택 모드와 설명의 정합성을 먼저 확인해야 하며, 이를 이미지로 덮어서는 안 된다.

그 후 필요하다면 반복 문단 일부를 “장면 계획 → 별도 생성 승인 → 생성 소재·음성·자막 합성 → 최종 검토”의 작은 SVG 아이콘과 HTML 안내로 대체할 수 있다. `제작 방식 안내`로 명시하고, 실제 작업 진행률·가격·생성 성공·공급사 품질은 표현하지 않는다. 작은 화면에서는 세로 배치 또는 문장만 남긴다. 새 히어로·목업 영상·실사 인물 이미지는 권장하지 않는다.

## 화면 근거 및 비교 위치

현재 캡처는 합성 데이터임을 화면에 표시한 Cloud Chromium 결과다. [전체 화면 인덱스](evidence/final-visual-audit/screens.md)에 20개 화면/상태의 각 뷰포트를 연결했다.

| 화면 묶음 | 현재 근거 |
|---|---|
| 홈·제작·작업실 | [홈 1366](evidence/final-visual-audit/screens/home-1366.png), [제작 390](evidence/final-visual-audit/screens/create-390.png), [작업실 1366](evidence/final-visual-audit/screens/workspace-1366.png) |
| 뉴스·분석·대본 | [뉴스 1920](evidence/final-visual-audit/screens/news-1920.png), [분석 진입 1366](evidence/final-visual-audit/screens/analysis-entry-1366.png), [합성 분석 결과 1366](evidence/final-visual-audit/screens/analysis-result-1366.png), [대본 1366](evidence/final-visual-audit/screens/script-1366.png) |
| 음성·영상·AI 영상 | [음성 전체](evidence/final-visual-audit/screens/voices-1366-full.png), [영상 1920](evidence/final-visual-audit/screens/video-1920.png), [AI 영상 전체](evidence/final-visual-audit/screens/ai-video-1366-full.png) |
| 보관함·게시 | [보관함 1366](evidence/final-visual-audit/screens/library-1366.png), [게시 준비 1366](evidence/final-visual-audit/screens/publish-1366.png), [이전 Windows Fake 부분 결과](evidence/script-flow-recheck/py312/product-fixed/openai/synthetic-partial-result.png) |
| 피드·설정 | [피드 기사 선택 후 전체](evidence/final-visual-audit/screens/feed-selected-1366-full.png), [설정 390](evidence/final-visual-audit/screens/settings-390.png), [AI 영상 설정 전체](evidence/final-visual-audit/screens/ai-video-settings-1366-full.png) |
| 빈 상태·오류·차단 | [빈 보관함 1366](evidence/final-visual-audit/screens/empty-library-1366.png), [빈 대기함 390](evidence/final-visual-audit/screens/empty-queue-390.png), [오류 390](evidence/final-visual-audit/screens/error-390.png), [모델 미준비 390](evidence/final-visual-audit/screens/ai-video-390.png) |

이미 적용된 이미지의 실제 전후는 [기존 이미지 적용 보고서](photoreal_studio_assets_review.md)의 동일 fixture 비교를 재사용한다. 현재 감사에서 가상의 after를 만들지 않았다.

| 비교 위치 | 적용 전 | 실제 적용 후 | 이번 판정 |
|---|---|---|---|
| 홈 상단 | [1366 전](evidence/photoreal-studio/before/home-1366.png) | [1366 후](evidence/photoreal-studio/after/home-1366.png) | 기존 적용 유지 |
| 빈 보관함 | [1366 전](evidence/photoreal-studio/before/empty-library-1366.png) | [1366 후](evidence/photoreal-studio/after/empty-library-1366.png) | 기존 적용 유지 |
| 뉴스 기본 썸네일 | [현재 후보 전](evidence/final-visual-audit/screens/news-1920.png) | **미제작·미적용** | 중립 SVG 대체 후보 |
| AI 영상 설명 | [현재 후보 전](evidence/final-visual-audit/screens/ai-video-1366-full.png) | **미제작·미적용** | 문구 확인 후 절차도 선택 후보 |

과거 전후는 `fbadd460d3005fca5c5aa613a78fd7c926c87be6` / `d8090dee7894597114f318553556f0ca521f0924` 기준이다. 현재 캡처의 합성 기사 수 등은 과거와 다르므로 데이터 차이를 디자인 변경으로 해석하면 안 된다. 기존 Windows 화면도 검토했지만 이번 실행을 Windows 실행이라고 기록하지 않는다.

## 이번 검증과 한계

Cloud Python 3.12.14 + Chromium, 임시 DB·설정·합성 자료, GET만 허용한 브라우저로 확인했다. 실제 서비스 요청은 차단했고 앱 실행도 격리된 검증용 인스턴스만 사용했다.

| 항목 | 결과와 확인 범위 |
|---|---|
| 주요 16화면 × 3크기 | **PASS** — 48개 조합의 HTTP 200, 수평 넘침 0px, 브라우저 JS 오류 0건. 1366×768 / 1920×1080 / 390×844 |
| 빈 보관함·대기함 × 3크기 | **PASS** — 6개 조합, 빈 상태·CTA·키보드 Enter로 제작 진입 확인 |
| 분석 진입·합성 결과 × 3크기 | **PASS** — 6개 조합. 기존 안내 SVG 로드, 데스크톱 표시/모바일 의도적 숨김 확인 |
| 캡처 테스트 | **2 passed + 1 passed / 0 failed** — 아래 두 최종 명령 결과. 각 실행에 Starlette/httpx deprecation warning 1건 |
| 자료 보존 | **PASS(격리 fixture 범위)** — 비교 대상 ContentDraft·IntelligenceRun·RenderJob 기록, 설정, 합성 미디어 해시 불변. 사용자 운영 DB·키·MP4에는 접근하지 않음 |
| 외부 호출 | **0건** — 브라우저 외부/POST 시도 목록 비어 있음, Fake/offline fixture 및 외부 호출 차단 guard 사용. 이미지 API·AI·OAuth·SNS 호출 없음 |
| 새 전체 회귀 / Windows 실행 | **미실행** — 시각 감사·자료만 변경. 기존 전체 회귀 **57 FAIL 기록 유지**. 이번 캡처 결과를 전체 기능 PASS로 확대하지 않음 |
| 사용자 Windows 11, 배율·음질·실계정 | **NOT VERIFIED** — Cloud viewport 확인은 Windows 배율·사용자 PC 검증이 아님 |

총 60개 화면/크기 조합과 긴 화면 보조 full-page 4장을 보존했다. 대표 화면을 실제로 열어 레이아웃·문구·오인 위험을 검토했으며 자동 넘침 검사만으로 디자인 품질 PASS를 선언하지 않았다.

**영상 fixture 제한:** 이번 공통 캡처 fixture는 배치 확인용 합성 미디어를 포함하며 일부 바이트는 실제 재생 가능한 MP4가 아니다. 썸네일/플레이어 로딩 표시와 `audit.json`의 일부 `loaded:false`를 실제 영상 실패나 재생 성공으로 판정하지 않는다. 실제 합성 MP4와 Fake 플랫폼 부분 결과는 기존 [Windows 대본 동선 재검증 보고서](windows_script_flow_recheck.md)의 근거만 참조했다. 그 당시 제품 소스와 현재 제품 소스는 동일하지만, 이번에 재생·게시를 재실행한 것은 아니다.

**준비 중 확인된 캡처 스크립트 오류도 보존:** 추가 분석 캡처 첫 실행은 합성 IntelligenceRun의 필수 message 누락으로 실패했고, 다음 probe는 모바일에서 의도적으로 숨기는 장식 SVG를 visible로 기대하여 실패했다. fixture 필수값과 화면의 기존 반응형 정책에 맞는 기대값만 수정하여 최종 1건을 통과했다. 제품·보안 검사·기존 회귀를 수정하거나 실패를 skip하지 않았다. 원본 로그도 evidence에 포함한다.

재현 명령(프로젝트 루트, 최종 스크립트의 앞 2개와 추가 1개를 구분):

```bash
PYTHONPATH=src:tests:tools NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
UX_PHASE=after UX_EVIDENCE=/tmp/newsflow-final-visual-audit \
.venv/bin/python -m pytest -q -rs -p windows_final_guard \
docs/reports/evidence/final-visual-audit/test_capture.py::test_all_screens \
docs/reports/evidence/final-visual-audit/test_capture.py::test_empty_states

PYTHONPATH=src:tests:tools NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
UX_PHASE=after UX_EVIDENCE=/tmp/newsflow-final-visual-audit \
.venv/bin/python -m pytest -q -rs -p windows_final_guard \
docs/reports/evidence/final-visual-audit/test_capture.py::test_analysis_entry_and_result
```

처음 2건은 추가 분석 테스트를 작성하기 전 파일 전체 명령으로 실행했으며 [원본 결과](evidence/final-visual-audit/newsflow-final-visual-audit.txt)와 [추가 결과](evidence/final-visual-audit/newsflow-final-visual-analysis.txt), XML, [캡처 스크립트](evidence/final-visual-audit/test_capture.py), JSON, SHA-256 manifest를 함께 보존한다.

## 보존 및 종료

수정 범위는 이 감사 문서와 `docs/reports/evidence/final-visual-audit/`의 검토 자료뿐이다. 템플릿·CSS·정적 이미지·비즈니스 로직·DB 구조·API/OAuth·승인·게시 정책 변경 없음. 사용자 설정·운영 데이터·운영 앱 재시작 없음. 새 이미지 제작·유료 호출·main 병합·운영 반영 없음. 기존 PR #35 Draft를 유지하며 보고 후 추가 개발을 중단한다.
