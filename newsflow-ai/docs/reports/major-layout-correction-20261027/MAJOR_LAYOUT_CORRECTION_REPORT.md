# NewsFlow AI — MAJOR 6개 화면 레이아웃 최종 보정

최종 판정: **CONDITIONAL**. 승인된 주요 배치 차이는 보정했으며 현재 판정은 **MINOR 4 / FUNCTIONAL_CONSTRAINT 2 / MAJOR 0**이다. 픽셀 동일·실제 API 성공·운영 전환 승인을 뜻하지 않는다. 최종 시각 인수는 사용자 판정을 기다린다.

## 기준과 변경

- 브랜치: `codex/newsflow-approved-ui-20261027`
- 시작 HEAD: `f88c8146dd8b79b9d020ecf02b04d7944f88abd6`. 시작 시 원격/로컬 일치, 기존 추적 변경 없음.
- 레이아웃 커밋: `c01ba851fce71e93c10970a49fcab74514cc3072`
- 최종 제품 SHA: `c892ba5ac3725072cd2f63ab2fcbd1b1d0a76025` / 최종 검사 도구 SHA: `db616e474c16d04ca14649d9d3134beef05096b1`
- 승인 자산: `e6e493c0dbd5ab8ef017d716f466d715ec9896a9` / `newsflow-ai/docs/design/approved-20261027/approved-assets/`
- 변경 파일: `frontend/src/studio/Workbench.tsx`, `frontend/src/studio/approved.css`, `tools/studio_v3/tests/approved_ui.browser.cjs`.
- 공유 상태/핸들러와 비대상 JSX는 그대로다. 새 API·Python 서비스·schema/migration·가격 계산·OAuth·승인 정책 변경 0.
- 기존 기능 감사·디자인 원본 검증·전체 Python 회귀를 반복하지 않았다. 기존 구현/시각 인수 보고서 폴더와 캡처는 변경하지 않았다.

## 6개 화면 판정

| 화면 | 이전 | 이번 |
|---|---|---|
| 뉴스 쇼츠 | MAJOR | MINOR |
| 캐릭터 쇼츠 | MAJOR | MINOR |
| 뉴스 스튜디오 | MAJOR | FUNCTIONAL_CONSTRAINT |
| 자동화 센터 | MAJOR | FUNCTIONAL_CONSTRAINT |
| 게시 스튜디오 | MAJOR | MINOR |
| 성과·비용 | MAJOR | MINOR |

### 뉴스 쇼츠 — MINOR

- 승인 원본: [news_shorts_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_shorts_v2.png)
- 보정: 기사/자료 · 중앙 대본+9:16 미리보기 그룹 · 우측 음성/영상 명령의 3영역으로 재배치했다. 단계/명령 높이를 줄이고 저장 버튼은 편집 스크롤 밖에 유지했다. 타임라인은 1920 첫 화면 안에 배치했다. 1366 좁은 기사/대본 제목도 상태 배지와 분리했다.
- 보존: 대본 저장/재조회, Revision 409 편집 보존, 장면 선택, 음성·영상 및 비용 승인 동작 유지.
- 남은 차이: 시안의 인라인 음성·영상 옵션 대신 기존 모델·비용 승인 폼을 유지한다. 패널 밀도·아이콘·간격은 작은 차이가 있다. 1366은 내부/본문 스크롤을 허용한다.
- 전후: `before/shorts-1920.png` → `after/shorts-1920.png`, `before/shorts-1366.png` → `after/shorts-1366.png`.

### 캐릭터 쇼츠 — MINOR

- 승인 원본: [character_shorts_v4.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/character_shorts_v4.png)
- 보정: 3단계를 유지하고 참조 PNG·주제/스토리·영상+모델/견적 그룹을 첫 행에 배치했다. 실제 모델 고정값·공식 견적·검토 명령은 미리보기 옆에 있고 나머지 고급 설정만 접는다. 스토리보드를 프로젝트 목록보다 앞에 옮겼다.
- 보존: 참조/주제·작업 고정값·장면 선택, Claude → 견적/승인 → Seedance → FFmpeg 명령 및 원래 상태 게이트 유지.
- 남은 차이: 실제 클립/장면 이미지가 없는 상태는 텍스트 장면과 빈 미리보기로 표시한다. 원본의 캐릭터 사진·완성 영상·가상 견적을 복제하지 않는다. 1366은 스토리보드까지 본문 스크롤이 필요하다.
- 전후: `before/characters-1920.png` → `after/characters-1920.png`, `before/characters-1366.png` → `after/characters-1366.png`.

### 뉴스 스튜디오 — FUNCTIONAL_CONSTRAINT

- 승인 원본: [news_studio_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_studio_v2.png)
- 보정: 왼쪽 검색/필터/기사, 중앙 선택 기사+저장 요약+AI 분석 정보, 오른쪽 출처/검토와 제작실 이동으로 분리했다. 제공되는 분석 실행 메타데이터만 표시하고 기사별 분석 본문/키워드 미제공을 명시했다.
- 보존: 검색·선택·출처와 기존 분석 승인 명령 유지. 관련 뉴스 추천·즐겨찾기·새 분석 탭·영상 편집 기능 추가 없음.
- 남은 차이: 현재 read model은 articles.summary 및 analyses의 id/kind/provider/status/created_at만 제공한다. 기사별 분석 본문·키워드·연결 식별자가 없으므로 원본 분석 탭은 재현하지 않았다. 기사 요약이나 전체 실행 기록을 선택 기사의 AI 분석으로 오인시키지 않는다.
- 전후: `before/news-1920.png` → `after/news-1920.png`, `before/news-1366.png` → `after/news-1366.png`.

### 자동화 센터 — FUNCTIONAL_CONSTRAINT

- 승인 원본: [automation_v1.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/automation_v1.png)
- 보정: 예약명·주기·실행 시간·다음 실행·상태의 중앙 예약 테이블과 오른쪽 선택 상세/저장/상태 변경을 구성했다. 하단 예약 실행 기록과 자동 제작 기록을 구분했다.
- 보존: 기존 일정 선택과 revision, 저장 시 paused 및 별도 활성화 폼 유지. 결과 불명 자동 재실행·무인 유료 실행 없음.
- 남은 차이: 원본 왼쪽의 여러 제작 유형/예약 템플릿을 뒷받침하는 계약이 없어 추가하지 않았다. 가상 유형 없이 테이블+상세 2영역을 유지한다. 다음 실행이 없으면 미정으로 표시한다.
- 전후: `before/automation-1920.png` → `after/automation-1920.png`, `before/automation-1366.png` → `after/automation-1366.png`.

### 게시 스튜디오 — MINOR

- 승인 원본: [publishing_v4.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/publishing_v4.png)
- 보정: 초안 선택·중앙 미리보기+검토 나란히·플랫폼 계정으로 묶었다. 1366은 검토 폭을 확보하고 4플랫폼 계정을 다음 행에 배치했다. 게시/단일 이미지 전달 기록은 별도 하단 영역이며 값이 있는 두 기록의 겹침 방지를 검사했다.
- 보존: Instagram 다중 계정·YouTube·TikTok·Facebook 구분, 검토/저작권/출처/권한과 최종 실행 분리, TikTok/Facebook 실전송 차단 유지.
- 남은 차이: 원본의 인라인 편집·일괄 예약을 새로 구현하지 않고 기존 편집·검토·최종 승인 폼을 유지한다. 1366의 플랫폼/기록은 본문 스크롤로 확인한다. 시안보다 검토 안내 문구가 많다.
- 전후: `before/publishing-1920.png` → `after/publishing-1920.png`, `before/publishing-1366.png` → `after/publishing-1366.png`.

### 성과·비용 — MINOR

- 승인 원본: [analytics_v4_option2.png](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/analytics_v4_option2.png)
- 보정: 큰 계정 카드를 기본 닫힌 등록 계정/권한 요약으로 바꾸고 플랫폼·계정 선택을 유지했다. 성과·콘텐츠·AI 사용량을 위로 올리고 추정 비용/실제 청구액은 상단 요약에서 구분한다. 계정 라벨 nowrap을 보존했다.
- 보존: Instagram 복수 계정, 계정 식별자 없는 지표 비귀속, 공급사 견적/청구액 분리 유지. 가짜 조회수·수익·비용 생성 없음.
- 남은 차이: 시안의 콘텐츠 격자·그래픽 차트 대신 기존 실제 지표/사용량 표와 콘텐츠 목록을 재사용한다. 미수집/미확인 표시와 9:16 미리보기로 정보 밀도 차이가 남는다.
- 전후: `before/analytics-1920.png` → `after/analytics-1920.png`, `before/analytics-1366.png` → `after/analytics-1366.png`.

## 시각 비교

[승인 원본·수정 전·수정 후 갤러리](visual-comparison.html)에 두 viewport를 함께 보존했다. 승인 PNG는 1536×1024, 실제 캡처는 1920×1080/1366×768이다. 보호된 공통 메뉴와 실제 데이터/승인 폼이 달라 사진·문구·금액·픽셀 동일을 주장하지 않는다. 네이비·보라·시안 체계와 실제 조작 컴포넌트를 유지했고 PNG를 앱 위에 덮지 않았다.

- 뉴스 쇼츠 1920 타임라인 y≈893, 높이≈142, 하단≈1034 ≤ 1080. 중앙 대본과 세로 미리보기는 나란히 배치했다.
- 캐릭터 1920 스토리보드 y≈805, 높이≈172, 하단≈976 ≤ 1080. 영상 옆 실제 모델/견적 영역을 확인했다.
- 성과 영역 시작은 y≈511로 올라왔다. 계정 상세는 별도로 펼쳐 본다.
- 1366에서는 정상 스크롤을 허용하며 저장/제작/검토 동작은 접근 가능하다. 게시 검토 폭은 최소 250px 이상, 플랫폼/하단 이력은 본문 스크롤로 접근한다.
- 원본의 가상 계정·연결 성공·조회수·견적·완성 영상을 실제 결과처럼 만들지 않았다.

## 신규 검증

| 항목 | 이번 결과 |
|---|---|
| TypeScript 타입 검사 | PASS |
| 최종 Vite 빌드 | PASS |
| Windows 실제 Chrome 합성 React 검사 | **56 checks PASS / 0 FAIL / 0 ERROR** |
| 캡처 | 대상 12장 + 홈/비대상 보호 14장 |
| 실제 API·OAuth·SNS 호출 | 0 |
| 테스트 종료 후 소유 프로세스 | 0 |

56개는 대상 렌더/넘침 12 + 배치 12 + 저장·오류·승인/범위 동작 17 = 대상 41개, 보호 렌더 14 + TOP 3 CSS 대조 1 = 보호 15개다. 보호 화면은 기능 전수 재실행 없이 캡처/적용 규칙만 확인했다.

주요 확인: 대본 저장/재조회·Revision 409 편집 보존·장면 선택, 캐릭터 주제의 기존 초안 폼 전달·고급 고정값·생성 게이트·참조 없음, 뉴스 검색/분석 미제공 표시, 예약 저장 후 paused와 별도 상태 변경, 게시 검토/실행 분리·4플랫폼 접근·값 있는 하단 이력의 겹침 방지, Instagram 다중 계정/미연결 지표 비귀속, 명시적 로딩 실패 UI.

첫 배치 검사는 상속 여백으로 실패해 해당 중앙 그룹 안에서 보정했다. 선택자 정리 중 제가 만든 주석 오류로 빌드도 1회 실패했고 바로잡았다. 기존 CSS 범위 단언을 바꾸지 않고 명시적 module 선택자로 정리해 최종 검사에 포함했다. 실패를 삭제하거나 timeout 상향, skip/xfail·Guard·CSP 완화로 숨기지 않았다. 최종 신규 FAIL/ERROR는 없다. 빌드의 기존 폰트 런타임 경로 안내 경고는 유지한다.

## 재사용과 미검증

- Windows CI **88 PASS**: 기존 [run 40467597750](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40467597750) 재사용. 이번 재실행 아님.
- 브라우저 **40개**, 최근 **17 PASS**: 이전 증거로 보존. 이번 56개와 별도.
- 기존 전체 **5,454 PASS / 4 SKIP**: 역사적 결과이며 최신 전체 회귀가 아님. 과거 Windows identity 시간 초과 1건도 해결됐다고 표시하지 않는다.
- Windows DPI **100/125/150/200%: NOT VERIFIED**. viewport 캡처는 OS DPI 대체 증거가 아니다.
- 로컬 전체 Python 앱 통합: **NOT VERIFIED**. Guard 우회·사전 import·네이티브 순서 변경 없음.
- 실제 공급사 API·OAuth·SNS, Chrome 자체 OS 수준 백그라운드 통신 차단: 미검증/미실행.
- 이번 커밋은 중복 백엔드 CI를 피하도록 `[skip ci]`를 명시했다. workflow·단언·보안 정책·skip/xfail을 완화하지 않았고 새 Actions 결과로 표시하지 않는다.

## 홈과 비대상 보호

[소스 보호](protected-source-proof.json), [캡처 보호](protected-capture-proof.json), [TOP 3 CSS 대조](non-target-css-proof.json)에 근거를 남겼다.

- 보호 소스 6개 SHA-256 동일. 공통 상태/핸들러, 이미지 3모드·라이브러리·설정 JSX와 초기 설정/명령 카탈로그는 바이트 동일. Guard 원본 동일.
- 홈·콘텐츠 제작 홈 × 두 해상도 **4쌍 PNG 바이트 동일**.
- 다른 확정 화면 10쌍: 파일 동일 **4쌍**, 미디어 내부만 다른 **5쌍**, 미디어 밖 텍스트 픽셀도 다른 **1쌍**이다. 완전 동일로 뭉뚱그리지 않았다.
- TOP 3 1366의 텍스트 차이는 실제 DOM 266개에 매칭되는 CSS가 기존/현재 **50개 모두 동일**이고 JSX도 동일함을 확인했다. 구조/CSS 회귀 근거는 없지만 픽셀 차이의 정확한 렌더링 원인은 미확정으로 남긴다. 해당 제품 화면은 수정하지 않았다.
- 독립 이미지 MINOR, 뉴스 이미지 MATCH, TOP 3 MINOR, 라이브러리 FUNCTIONAL_CONSTRAINT, 설정 MINOR의 기존 판정 유지. 비대상 화면에 새 기능을 추가하지 않았다.
- 운영 DB·ledger·키·설정·실사용 미디어·백업을 테스트 입력으로 쓰거나 수정하지 않았다. 새 운영 전수 해시 감사를 수행했다고 주장하지 않는다.
- PR #35/main/운영 브랜치 변경, 운영 앱 종료·재시작·배포, 실제 유료 API·OAuth·SNS 게시 없음. reset/clean/stash/force push 없음.

## 남은 인수 조건

이번에 승인된 6개 화면의 MAJOR 배치 차이는 남아 있지 않다. 다만 기사별 AI 분석 본문/키워드 연결과 미지원 자동화 유형은 기존 API/기능 제약이다. 원본 대비 작은 밀도·모달/인라인 차이, TOP 3 캡처의 텍스트 렌더 차이, 실제 DPI·전체 Python 통합은 위와 같이 남긴다. 기능 확장·운영 전환·실제 API·배포 인수는 별도 승인 범위다. 결과 보고 후 추가 개발/운영 반영 없이 사용자 판정을 기다린다.
