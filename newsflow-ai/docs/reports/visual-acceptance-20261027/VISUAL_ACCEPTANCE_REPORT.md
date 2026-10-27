# NewsFlow AI — 최종 UX/UI 시각 인수 및 최소 보정

최종 판정: **CONDITIONAL**. 승인 PNG의 주요 배치 차이 6개 화면이 남아 있다. 이를 기능 테스트 PASS나 안전 제약으로 일괄 수용하지 않았다. 이번에는 두 작은 가독성 문제만 수정했으며 MAJOR 화면의 구조는 임의로 재설계하지 않았다.

## 기준과 범위

- 작업 브랜치: `codex/newsflow-approved-ui-20261027`
- 시작 HEAD: `a5fed98cdaa841b7e90f0302b010f64d1a9eed08`
- 보정 제품/테스트 커밋: `0789b14c0d2bddc701c3c0e523cc759a6a390f11`
- 승인 자산 커밋: `e6e493c0dbd5ab8ef017d716f466d715ec9896a9`. 기존 11개 PNG 및 등록 증거 재사용. 원본 재생성/바이너리 재검사 없음.
- 기존 [visual-comparison.html](../approved-ui-20261027/visual-comparison.html), 22개 업무 화면 캡처(11×2), 보호 홈 캡처 및 이전 보고서 보존.
- 이번 비교: 승인 PNG 1536×1024와 실제 1920×1080 / 1366×768 캡처를 눈으로 검토했다. 서로 다른 viewport를 단순 축소하여 픽셀 동일성을 주장하지 않는다.
- 공통 좌측 메뉴/상단 헤더는 홈 보호 조건에 따라 유지한 차이다. 이를 바꾸지 않았으며 각 업무 화면의 배치 차이와 별도로 판단했다.

## 화면별 판정

| 화면 | 판정 | 이번 조치 |
|---|---|---|
| 뉴스 쇼츠 | MAJOR | 구조 수정 보류 |
| 캐릭터 쇼츠 | MAJOR | 구조 수정 보류 |
| 독립 AI 이미지 | MINOR | 이력 내부 CSS만 보정 완료 |
| 뉴스 기반 이미지 | MATCH | 변경 없음 |
| TOP 3 자동 피드 | MINOR | 현 상태 유지·차이 기록 |
| 뉴스 스튜디오 | MAJOR | 구조 수정 보류 |
| 자동화 센터 | MAJOR | 구조 수정 보류 |
| 라이브러리 | FUNCTIONAL_CONSTRAINT | 안전 정책 차이 유지 |
| 게시 스튜디오 | MAJOR | 구조 수정 보류 |
| 성과·비용 | MAJOR | 라벨 보정 완료·주요 구조 수정 보류 |
| 설정·관리 | MINOR | 변경 없음·차이 기록 |

집계: MATCH 1 / MINOR 3 / MAJOR 6 / FUNCTIONAL_CONSTRAINT 1. 모든 화면에 보조적인 기능·데이터 제약이 있을 수 있으며, 주 판정을 안전 제약으로 덮지 않았다. MINOR 보정 완료는 승인 원본과의 픽셀 일치를 뜻하지 않는다.

### 뉴스 쇼츠 — MAJOR

- 승인 원본: [news_shorts_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_shorts_v2.png)
- 시각 비교: 기사·대본·9:16 미리보기·음성 4영역과 하단 타임라인은 존재한다. 그러나 승인 원본의 중앙 대본+미리보기 묶음과 다르며, 단계/명령 행과 편집 높이 때문에 1920에서도 타임라인이 하단에 걸리고 1366에서는 추가 스크롤이 필요하다.
- 기능·보안 차이: 실제 모델·음성 선택과 검토/비용 승인 폼은 유지해야 한다. 합성 컬러바는 기존 1080×1920 검증 파일이며 승인 PNG의 완성 영상 복제물이 아니다.
- 조치/수정안: 기능/승인 폼을 유지한 상태에서 중앙 편집+미리보기 그룹 및 타임라인의 높이 배분을 조정하는 안을 사용자 확인 후 적용한다.
- 증거: 기존 `../approved-ui-20261027/captures/shorts-1920.png`, `shorts-1366.png`. 이번에 화면을 재실행하지 않았다.

### 캐릭터 쇼츠 — MAJOR

- 승인 원본: [character_shorts_v4.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/character_shorts_v4.png)
- 시각 비교: 3단계와 참조·스토리·미리보기 3열은 유지되지만 원본의 영상 옆 설정/비용과 즉시 보이는 하단 장면 카드가 현재는 서로 다른 아래 영역으로 밀린다. 1920 첫 캡처에서도 스토리보드는 보이지 않는다.
- 기능·보안 차이: 저장된 참조 PNG와 완료 영상을 구분하며 미완료 영상은 빈 상태다. 실제 모델·견적·생성 승인 조건과 3장면 데이터는 시안의 예시 5장면/55초로 대체하지 않는다.
- 조치/수정안: 기존 3열 안에서 참조/스토리 높이와 우측 설정 위치를 재배분하는 안만 승인 후 적용한다. 가짜 캐릭터/완성 클립은 넣지 않는다.
- 증거: 기존 `../approved-ui-20261027/captures/characters-1920.png`, `characters-1366.png`. 이번에 화면을 재실행하지 않았다.

### 독립 AI 이미지 — MINOR

- 승인 원본: [standalone_image_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/standalone_image_v2.png)
- 시각 비교: 지시문/모델·중앙 캔버스·우측 이력의 핵심 3열은 충족한다. 1366 우측 이력의 제목이 상태 배지에 눌리던 현상을 재현하여 제목/상태를 별도 행으로 최소 보정했다. 1920에서도 제목 가독성을 확인했다.
- 기능·보안 차이: 참조 로컬 보관과 유료 편집 생성은 별개다. 미지원 편집/스타일 기능을 장식 버튼으로 추가하지 않고 실제 성공 파일만 표시한다.
- 조치/수정안: 보정된 상태를 인수 후보로 제시한다. 모델명 길이와 실제 데이터에 따른 줄바꿈 차이는 남는다.
- 증거: 기존 `../approved-ui-20261027/captures/images-1920.png`, `images-1366.png` 및 이번 `after/images-1920.png`, `after/images-1366.png`.

### 뉴스 기반 이미지 — MATCH

- 승인 원본: [news_image_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_image_v2.png)
- 시각 비교: 기사 선택·카드/지시문·이미지 캔버스·속성/출처의 핵심 4영역과 독립 이미지/TOP 3 분리는 두 크기 캡처에서 확인된다. 핵심 배치 수정 필요 없음.
- 기능·보안 차이: 저장된 카드가 없는 합성 상태를 예시 카드로 채우지 않는다. 원본의 사진·문구·금액은 실제 데이터로 대체하며 실제 생성 성공을 뜻하지 않는다.
- 조치/수정안: 현재 핵심 구성을 유지한다. MATCH는 픽셀 동일 또는 실제 API 성공 판정이 아니다.
- 증거: 기존 `../approved-ui-20261027/captures/images-news-1920.png`, `images-news-1366.png`. 이번에 화면을 재실행하지 않았다.

### TOP 3 자동 피드 — MINOR

- 승인 원본: [top3_feed_v3.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/top3_feed_v3.png)
- 시각 비교: 좌측 순위/설정·중앙 3개 독립 결과·우측 문구/출처 검토 구성은 충족한다. 공통 옵션은 승인 원본 중앙 상단과 달리 좌측에 있고, 상태/승인 안내로 결과 카드가 더 아래 시작한다. 1366에서는 결과 하단을 스크롤해야 한다.
- 기능·보안 차이: 저장된 분석과 작업 고정값, 순위별 결과/오류, 검토 후 실행을 보존한다. 원본의 임의 생성·저장 성공 상태는 복제하지 않는다.
- 조치/수정안: 핵심 3개 결과 구조는 유지하고 작은 간격/위치 차이는 인수 의견으로 남긴다. 추가 소스 수정은 하지 않았다.
- 증거: 기존 `../approved-ui-20261027/captures/images-top3-1920.png`, `images-top3-1366.png`. 이번에 화면을 재실행하지 않았다.

### 뉴스 스튜디오 — MAJOR

- 승인 원본: [news_studio_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_studio_v2.png)
- 시각 비교: 3열과 기사·출처·다음 제작실 이동은 존재하지만 원본 중앙의 AI 분석 탭/핵심 키워드와 우측 관련 뉴스 영역이 현재 캡처의 본문 계층과 일치하지 않는다. 현재는 기사 상세와 분석 명령 중심이다.
- 기능·보안 차이: 보관 기사 검색을 실시간 인기 TOP 3로 표시하지 않는다. 없는 분석 결과나 관련 뉴스는 생성해 채우지 않는다.
- 조치/수정안: 기존에 제공되는 분석 필드만 중앙 분석 영역으로 표현 가능한지 확인한 뒤 해당 배치 변경을 별도 승인받는다. 신규 분석 기능은 자동 추가하지 않는다.
- 증거: 기존 `../approved-ui-20261027/captures/news-1920.png`, `news-1366.png`. 이번에 화면을 재실행하지 않았다.

### 자동화 센터 — MAJOR

- 승인 원본: [automation_v1.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/automation_v1.png)
- 시각 비교: 현재는 넓은 예약 카드 목록·우측 상세·하단 이력이다. 원본의 좌측 제작 유형과 중앙 다열 예약 테이블이 없어 정보 밀도와 조작 위치가 두 크기 모두 크게 다르다.
- 기능·보안 차이: 예약 저장과 활성화는 분리하며 미지원 예약 종류/템플릿/무인 유료 실행을 추가하지 않는다. 결과 불명 자동 재요청 금지 유지.
- 조치/수정안: 지원되는 예약 필드만 이용한 테이블 및 선택 상세 배치안을 승인 후 적용한다. 지원하지 않는 제작 유형을 채우지 않는다.
- 증거: 기존 `../approved-ui-20261027/captures/automation-1920.png`, `automation-1366.png`. 이번에 화면을 재실행하지 않았다.

### 라이브러리 — FUNCTIONAL_CONSTRAINT

- 승인 원본: [library_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/library_v2.png)
- 시각 비교: 좌측 검색/유형·중앙 카드·우측 9:16 미리보기 핵심 배치는 충족한다. 원본의 다수 완성 썸네일/길이/기간 수치와 달리 누락 썸네일은 미리보기 없음으로 보이며 카드 수는 실제 합성 목록 수다.
- 기능·보안 차이: 없는 썸네일·기간별 수·길이/용량·미구현 배치 기능을 꾸미지 않는다. 결과 불명 및 휴지 보관 경계를 보존한다. 주요 차이는 데이터/기능 정직성 때문에 유지한다.
- 조치/수정안: 현재 빈 상태/실제 자료 표시를 유지한다. 가짜 결과나 원본의 장식용 시간 이미지를 추가하지 않는다.
- 증거: 기존 `../approved-ui-20261027/captures/library-1920.png`, `library-1366.png`. 이번에 화면을 재실행하지 않았다.

### 게시 스튜디오 — MAJOR

- 승인 원본: [publishing_v4.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/publishing_v4.png)
- 시각 비교: 5단계·초안·미리보기·4플랫폼 계정은 존재한다. 원본은 중앙 미리보기와 기본 정보 편집이 나란하지만 현재는 긴 미리보기 아래 검토 영역이 배치돼 1920에서도 검토 패널이 하단에 걸리고 1366에서는 더 내려야 한다.
- 기능·보안 차이: 검토와 최종 실행 승인 분리, 실제 권한 미검증 표시, TikTok/Facebook 실전송 차단은 필수다. 원본의 연결 완료·일괄 예약을 가짜로 표시하지 않는다.
- 조치/수정안: 검토 폼과 미리보기의 같은 높이 배치를 사용자 승인 후 검토한다. 승인 단계를 줄이거나 실행 버튼으로 대체하지 않는다.
- 증거: 기존 `../approved-ui-20261027/captures/publishing-1920.png`, `publishing-1366.png`. 이번에 화면을 재실행하지 않았다.

### 성과·비용 — MAJOR

- 승인 원본: [analytics_v4_option2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/analytics_v4_option2.png)
- 시각 비교: 3개 요약·4플랫폼·Instagram 다중 계정 필터는 존재한다. 그러나 큰 전폭 계정 카드가 성과/콘텐츠보다 위에 있어 원본의 콘텐츠·미리보기·비용 집중 구조가 아래로 밀린다. 별개로 계정 라벨이 세로로 줄바꿈되던 MINOR 오류는 수정했다.
- 기능·보안 차이: 미수집 지표, 추정 비용, 실제 청구액을 구분하며 미확인 금액/연결 성공을 원본 숫자로 채우지 않는다. 계정 식별자 없는 지표를 임의로 귀속하지 않는다.
- 조치/수정안: 계정 정보를 간결한 선택/요약 영역으로 재배치하는 안만 별도 승인 후 적용한다. 이번에는 라벨 CSS만 보정했다.
- 증거: 기존 `../approved-ui-20261027/captures/analytics-1920.png`, `analytics-1366.png` 및 이번 `after/analytics-1920.png`, `after/analytics-1366.png`.

### 설정·관리 — MINOR

- 승인 원본: [settings_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/settings_v2.png)
- 시각 비교: 7개 기능 탭·7단계 가이드·계정·제작 기본값·API·뉴스/Windows 영역을 유지한다. 원본의 조밀한 여러 패널에 비해 가이드/계정 카드가 높아 개요 하단 항목은 스크롤해야 한다. 기능별 탭으로도 접근하는 기존 동선을 유지했다.
- 기능·보안 차이: 키 저장과 인증 성공을 구분하고 Windows 조회/자동 시작은 명시적 사용자 동작으로 유지한다. 시안의 예시 모델/연결 상태는 복제하지 않는다.
- 조치/수정안: 높이/밀도 차이를 인수 의견으로 남기며 임의 축소나 기능 이동은 하지 않는다.
- 증거: 기존 `../approved-ui-20261027/captures/settings-1920.png`, `settings-1366.png`. 이번에 화면을 재실행하지 않았다.

## 이번에 수정한 항목

1. **독립 이미지 이력:** 좁은 패널에서 제목과 긴 상태 배지가 같은 줄을 나눠 써 제목이 압축되던 문제. 이력 행 안에서만 제목/상태를 분리한 grid로 보정했다. 1366 제목 영역은 약 96.4px, 1920은 약 194.8px이며 상태는 카드 안의 별도 행에 있다. 실제 항목 선택과 성공/결과 불명 미리보기 구분은 그대로다.
2. **성과 계정 라벨:** `계정` 글자가 세로로 갈라지던 문제. 해당 필터만 nowrap과 select 자동 폭을 적용했다. 두 너비 모두 한 줄이고 select 폭은 160px이다. 큰 계정 패널의 위치는 변경하지 않아 성과 화면 주 판정은 MAJOR다.

제품 수정은 `frontend/src/studio/approved.css` 한 파일, 집중 검사는 `tools/studio_v3/tests/approved_ui.browser.cjs` 한 파일이다. 모든 새 CSS는 `.approved-studio`와 해당 module/mode 아래에만 적용된다. 기존 `workbench.css`의 강제 flex 때문에 최초 검사 1회가 실패했으나 해당 이력 내부의 우선순위만 수정했다. 첫 실패의 JSON과 프로세스 정리 증거를 보존했다. 단순 timeout 상향, Guard 완화, 단언 삭제, skip/xfail 추가는 없다.

## 신규 검증과 과거 증거 구분

| 구분 | 결과 | 이번 실행 여부 |
|---|---|---|
| React 타입 검사 | PASS | 신규 실행 |
| Vite 빌드 | PASS | 신규 실행, CSS 추가 보정 후 최종 빌드 PASS |
| 변경 화면+홈 보호 합성 Chrome | **17 checks PASS / 0 FAIL / 0 ERROR** | 신규 실행 |
| 캡처 | 변경 화면 2×2=4 + 보호 홈 2×2=4 | 신규 8장 |
| Windows Actions 집중 | **88 PASS** | 이전 제품 95d6147 증거 재사용, 재실행 아님 |
| 기존 합성 브라우저 | **40 checks PASS** | 이전 증거 재사용, 재실행 아님 |
| 전체 회귀 | 이전 5,454 PASS / 4 SKIP | 이번 미실행, 최신 결과로 표시하지 않음 |
| Windows OS DPI | **NOT VERIFIED** | 미실행, viewport는 DPI 대체 증거 아님 |
| 로컬 전체 Python 앱 통합 | **NOT VERIFIED** | 기존 Guard 제한 유지, 우회 없음 |

17개 구성: 화면/가로 넘침 8, 두 너비의 이력/라벨 기하 검사 4, 선택·결과 불명 미리보기·계정 필터·CSS 범위·무제출 검사 5. 변경하지 않은 업무 화면의 테스트를 반복하지 않았다. 홈은 기능 재감사 대신 시각 무변경 증거용으로만 캡처했다.

이전 Actions: [run 40467597750](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40467597750). 기존 Windows identity 시간 초과 1건은 과거 잔여 위험으로 유지하며 이번에 해결됐다고 주장하지 않는다. 중복 백엔드 CI 실행을 피하기 위해 이번 커밋은 `[skip ci]`로 명시했다. 워크플로와 기존 검사를 수정하거나 실패를 숨긴 것이 아니며 최신 검증 근거는 위 17개 로컬 집중 검사다.

## 전후 비교 및 홈 보호

- [11개 판정·원본·현재·수정 전후 비교](visual-comparison.html)
- [신규 검사 원본 JSON](after/browser-results.json), [정리 결과](focused-run.safe.json), [초기 실패](initial-attempt.json)
- [홈 보호 증거](protected-home-proof.json): 보호 소스 6개 SHA-256 동일, 홈/제작 홈 × 두 너비 PNG 4쌍 바이트 동일.
- 이전 보고서/캡처 경로는 Git 기준 변경 없음. 보정 전 4장은 기존 PNG 바이트 그대로 `before/`에 재사용했다.
- 사용자 데이터·운영 DB·ledger·키·설정·백업 A/B를 테스트 입력으로 사용하거나 수정하지 않았다. 이번 범위를 넘어 새 운영 자료 전수 해시 검사를 수행했다고 주장하지 않는다.
- 실제 API 호출/폼 제출 0, 운영 앱 실행·재시작 0, 테스트 종료 후 소유 프로세스 0. 기존 Guard·CSP·승인·재시도 정책 불변. Playwright 앱 요청은 전부 합성 응답이며 Chrome 자체 백그라운드 통신의 OS 수준 완전 차단은 NOT VERIFIED다.
- PR #35는 Draft·미병합이고 head `75626f74cc1bfe750d24132e44019bcda478247b`를 변경하지 않는다. main·운영 브랜치 변경 없음. 이번 작업 브랜치에만 보존한다.

## 남은 인수 조건

MAJOR 6개 화면의 위 배치 수정안에 대한 사용자 판정이 필요하다. 해당 구조 보정은 이번에 실행하지 않았다. 승인되지 않은 신규 기능, 실제 생성/게시, 운영 전환은 하지 않는다. 실제 Windows DPI와 전체 Python 앱 통합은 별도 허용된 검증 절차에서 확인해야 한다. 이번 결과를 보고한 뒤 추가 개발·운영 반영 없이 중단한다.
