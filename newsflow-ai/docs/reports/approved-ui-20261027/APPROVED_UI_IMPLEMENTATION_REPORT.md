# NewsFlow AI — 최종 승인 UX/UI 실제 구현 결과

기준일: 2026-10-27 KST
**최종 판정: CONDITIONAL** — 승인 자산의 11개 작업 화면 적용과 허용된 집중 검증 완료. 원본 PNG와의 최종 시각 인수, 실제 OS DPI 및 실계정 검증은 별도다.

## 1. 기준·브랜치·GitHub 상태

- 작업 시작 시 PR #35 최신 HEAD: `75626f74cc1bfe750d24132e44019bcda478247b`, Draft·미병합.
- 독립 구현 브랜치: `codex/newsflow-approved-ui-20261027`.
- 제품·테스트 체크포인트: [`95d61470e9df36582b9e29361bbdba0bc0a5d76e`](https://github.com/jsbae1979-prog/JSBAE/commit/95d61470e9df36582b9e29361bbdba0bc0a5d76e).
- 승인 디자인: [`e6e493c0dbd5ab8ef017d716f466d715ec9896a9`](https://github.com/jsbae1979-prog/JSBAE/tree/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/), [승인 매니페스트](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/APPROVED_DESIGN_MANIFEST.md).
- 이 보고서·캡처는 별도 증거 커밋에 보존한다. 문서 전용 커밋을 제품 테스트 SHA로 혼동하지 않는다.
- PR #35·main·디자인 문서 브랜치·운영 브랜치는 변경하지 않았다. 새 PR도 생성하지 않았다.

## 2. 화면별 적용 및 시각 비교

[승인 원본 / 실제 1920·1366 비교 보기](visual-comparison.html). 원본은 1536×1024, 실제 캡처는 1920×1080 및 1366×768이다. 11개 화면 모두 직접 조작 가능한 React 컴포넌트이며, 원본 PNG를 배경으로 덮거나 운영 결과로 사용하지 않았다.

**공통 차이:** 홈·콘텐츠 제작 홈의 보호를 위해 기존 좌측 메뉴·공통 상단 바·사용자 동선을 그대로 유지했다. PNG의 상단 전면 메뉴로 공통 셸을 교체하지 않았다. 미지원 기능, 예시 사진/모델/가격/계정/성과는 실제 제품 정보로 복제하지 않았다. 따라서 픽셀 단위 완전 일치라고 판정하지 않는다.

| 화면 | 적용 결과 | 승인 원본·실제 캡처 | 남은 시각/기능 차이 |
|---|---|---|---|
| 뉴스 쇼츠 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 기사·대본·세로 미리보기·음성 4영역과 하단 장면 타임라인, 저장·Revision 복구 유지 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_shorts_v2.png) · [1920](captures/shorts-1920.png) · [1366](captures/shorts-1366.png) | 대본/음성/생성의 기존 승인 모달과 실제 등록 모델을 유지. 예시 인물·비용·장면 사진을 가짜 결과로 채우지 않음. |
| 캐릭터 쇼츠 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 3단계·참조 PNG·스토리 주제·세로 미리보기·고정 설정·스토리보드 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/character_shorts_v4.png) · [1920](captures/characters-1920.png) · [1366](captures/characters-1366.png) | 새 주제는 새 초안 폼으로 전달. 저장 스토리 임의 편집·다중 캐릭터 관리·무인 합성은 추가하지 않음. 단계별 견적/승인 유지. |
| 독립 AI 이미지 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 지시문/모델·크기·품질 → 중앙 캔버스 → 우측 초안·결과 이력 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/standalone_image_v2.png) · [1920](captures/images-1920.png) · [1366](captures/images-1366.png) | 스타일 프리셋·자유 편집 등 미지원 도구는 추가하지 않음. 참조 기반 유료 편집 미구현 안내 유지. |
| 뉴스 기반 이미지 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 기사 → 카드 기획 → 이미지 캔버스 → 문구·속성·출처 4영역 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_image_v2.png) · [1920](captures/images-news-1920.png) · [1366](captures/images-news-1366.png) | 뉴스 카드/생성 결과/게시물/선정 기록을 구분. 생성·출처 검토는 기존 모달 경로를 유지. |
| TOP 3 자동 피드 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 순위·분석 선택, 공통 모델 설정, 3개 독립 결과, 우측 출처/승인 영역 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/top3_feed_v3.png) · [1920](captures/images-top3-1920.png) · [1366](captures/images-top3-1366.png) | 기본값과 진행 중 작업의 고정 설정을 구분. 모드 번호를 추가하지 않고 TOP 1·2·3 순위만 유지. 유료 실행은 기존 견적/승인 조건 유지. |
| 뉴스 스튜디오 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 보관 기사·출처 상세·다음 제작 단계의 3열 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/news_studio_v2.png) · [1920](captures/news-1920.png) · [1366](captures/news-1366.png) | 최신 TOP 3가 없는 자료를 인기 뉴스로 꾸미지 않음. 대본/영상 편집기를 중복 추가하지 않음. |
| 자동화 센터 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 예약 목록·선택 예약·하단 실행 이력 배치 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/automation_v1.png) · [1920](captures/automation-1920.png) · [1366](captures/automation-1366.png) | 실제 지원하는 저장·상태 변경만 유지. 미지원 예약 템플릿·무인 캐릭터/TOP 3 실행 스위치를 만들지 않음. 시안의 전면 표와 달리 기존 목록 선택 계약 유지. |
| 라이브러리 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 왼쪽 검색·유형 필터, 중앙 콘텐츠 카드, 우측 미리보기/보관 관리 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/library_v2.png) · [1920](captures/library-1920.png) · [1366](captures/library-1366.png) | 없는 썸네일은 빈 상태. 가짜 보관 용량·기간/다중 선택 기능 추가 없음. 제작실 이동·휴지 보관은 기존 계약 유지. |
| 게시 스튜디오 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 5단계 안내·초안 선택·미리보기/검토·4플랫폼 계정·기록 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/publishing_v4.png) · [1920](captures/publishing-1920.png) · [1366](captures/publishing-1366.png) | 실제 검토·최종 실행은 기존 승인 폼으로 분리. TikTok/Facebook 실전송 차단. 미지원 일괄 예약·썸네일 AI 추천은 표시하지 않음. |
| 성과·비용 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 요약 카드·4플랫폼·등록 계정 필터·콘텐츠·사용량·비용 구분 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/analytics_v4_option2.png) · [1920](captures/analytics-1920.png) · [1366](captures/analytics-1366.png) | Instagram 다중 계정은 실제 메타데이터만 표시. 계정 식별자 없는 지표는 계정별로 귀속시키지 않음. 미확정 견적·청구액은 금액으로 꾸미지 않음. |
| 설정·관리 | 적용 완료 · 최종 시각 인수 CONDITIONAL. 7개 기능 탭·기존 7단계 가이드·계정·기본값·모델/API·출처·Windows 영역 적용 | [승인 PNG](https://github.com/jsbae1979-prog/JSBAE/blob/e6e493c0dbd5ab8ef017d716f466d715ec9896a9/newsflow-ai/docs/design/approved-20261027/approved-assets/settings_v2.png) · [1920](captures/settings-1920.png) · [1366](captures/settings-1366.png) | 키 저장≠인증 성공. Windows 조회는 명시적 클릭 시만 실행. 시안의 예시 모델·연결 성공·자동 시작 활성화를 그대로 복제하지 않음. |

1366×768에서는 전체 제작 도구가 한 화면에 모두 들어가는 것으로 주장하지 않는다. 페이지/패널의 정상 스크롤로 하단 타임라인·저장·승인 영역에 접근한다. 네이비 패널, 보라·시안 선택/주요 동작, 아이콘·테두리·간격을 작업 화면 범위에서 통일했다.

## 3. 홈·콘텐츠 제작 홈 무변경

- `frontend/src/main.tsx`, `style.css`, `studio/workbench.css`, `legacy-actions.json`, `CommandDialog.tsx`, `contracts.ts`는 기준 작업본과 **바이트 동일**.
- 원래 홈의 JSX·이미지·카드·메뉴·동선·공통 CSS는 수정하지 않았다.
- 새 스타일은 모두 `.approved-studio` 아래에서만 적용된다. 브라우저 CSSOM 검사도 새 선택자의 범위 이탈 0건을 확인했다.
- 동일 기준 SHA를 별도 프런트엔드 기준 빌드로 재현하여 고정 시각·동일 합성 데이터·동일 Chrome에서 비교했다.
- 홈·콘텐츠 제작 홈 각각 1920/1366 **4쌍 PNG가 바이트 단위 동일**했다. [동일성 기록](protected-home-proof.json).
- [홈 1920 이전](protected-before/dashboard-1920.png) / [이후](captures/dashboard-1920.png), [홈 1366 이전](protected-before/dashboard-1366.png) / [이후](captures/dashboard-1366.png).
- [제작 홈 1920 이전](protected-before/create-1920.png) / [이후](captures/create-1920.png), [제작 홈 1366 이전](protected-before/create-1366.png) / [이후](captures/create-1366.png).

## 4. 변경 파일과 기능 연결

| 파일 | 목적 |
|---|---|
| frontend/src/studio/Workbench.tsx | 작업 화면의 배치·상태 선택·기존 명령 연결, 설정 탭, 새 초안 입력, 읽기 전용 메타데이터 재사용 |
| frontend/src/studio/TopThreeFeeds.tsx | 기존 배치 엔진/승인/복구 동작을 보존한 순위·설정·결과·출처 영역 |
| frontend/src/studio/ApprovedPanels.tsx | 작업실 전용 단계 안내·계정/플랫폼·비용 자료 구분·이미지 옵션·시작 가이드 |
| frontend/src/studio/approved.css | 보호 화면에 영향을 주지 않는 작업실 전용 디자인·반응형 배치 |
| tools/studio_v3/tests/approved_ui.browser.cjs | 합성 브라우저 사용자 동선·캡처·오류·승인 경계 집중 검증 |
| .github/workflows/newsflow-studio-v3.yml | 기존 집중 Windows CI의 대상에 이번 독립 브랜치만 추가 |
| docs/reports/approved-ui-20261027/ | 보고서·30개 PNG(변경 22/홈 이후4/홈 이전4)·비교 보기·검증 근거 |

전체 목록은 [CHANGED_FILES.txt](CHANGED_FILES.txt)에 기록한다. 백엔드 Python·DB schema·migration·공급사 Adapter·가격/과금·OAuth/게시 승인 정책은 변경하지 않았다.

설정/성과 화면은 기존 게시 모듈의 비밀값 없는 계정 조회를 재사용하고, 뉴스 쇼츠는 기존 뉴스 모듈의 기사 조회를 재사용한다. 모두 동일 출처의 기존 읽기 전용 JSON 경로이며 공급사 조회나 유료 호출을 추가하지 않는다. 모델/이미지 선택은 기존 초안 폼에 전달하고 기존 작업의 고정값을 바꾸지 않는다.

## 5. 이번 신규 검증 결과

### Windows 로컬 프런트엔드

- TypeScript `tsc --noEmit`: **PASS**.
- React/Vite 프로덕션 빌드: **PASS**.
- 실제 Windows Chrome·Playwright 합성 브라우저: **40개 확인 항목 PASS** = 화면/가로 넘침 26건 + 대표 기능·안전 동선 14건. pytest 40건이라는 뜻은 아니다.
- 1920×1080, 1366×768: 각 13개 화면·모드 **26개 현재 캡처**. JavaScript 오류 0, 외부 애플리케이션 요청 0.
- [브라우저 결과](captures/browser-results.json), [로컬 요약](verification-summary.json), [자체 프로세스 정리](after-acceptance.safe.json).
- 기존 검증된 **1080×1920·30초 합성 MP4**를 재사용하여 새 React 미리보기의 메타데이터/프레임 디코딩을 확인했다. 새 유료 영상 생성 또는 새 FFmpeg 엔진 인수로 확대 해석하지 않는다.
- 최종 테스트 종료 후 자체 Node·Chrome 잔여 프로세스 **0**. 운영 포트 8765와 운영 프로세스는 사용/변경하지 않았다.

검증한 대표 동선:

1. 대본 저장 → 갱신/재열기, Revision 충돌 시 입력 보존.
2. 참조 PNG 및 실제 합성 3장면 스토리보드 표시, 잘못된 단계의 캐릭터 생성 차단.
3. 새 캐릭터 주제 → 기존 초안 폼 전달·취소, 저장된 작업 불변.
4. 독립 이미지 모델·크기·품질 → 기존 초안 저장 폼·기록 전달.
5. 결과 불명 이미지의 성공 미리보기 차단.
6. TOP 1·2·3 독립 결과, Fake 결과의 실제 게시 준비 차단.
7. 예약 저장 후 paused 유지·활성화 분리.
8. 설정 7개 탭·공급사별 빈 비밀키 입력.
9. Instagram 복수 계정 메타데이터와 TikTok/Facebook 실전송 차단 표시.
10. 계정 식별자 없는 성과의 잘못된 귀속 방지·미확정 청구액 표시.
11. 콘텐츠 검토와 실제 실행의 분리, 새 CSS 범위 보호.

기존 149개 정적 폼 계약 파일은 변경하지 않았다. 149개 전부를 실제 런타임 재실행했다는 뜻은 아니다.

### Windows Actions · Python 3.14.7

[집중 검증 run 40467597750](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40467597750), 제품 SHA `95d61470e9df36582b9e29361bbdba0bc0a5d76e`: **SUCCESS / 88 PASS / FAIL 0 / ERROR 0**.

- 읽기 전용 projection 검사 **43 PASS**.
- TOP 3 배치 Fake 검사 **25 PASS**.
- 승인된 일회성 Windows Runner의 합성 Python 앱/폼 통합 **20 PASS**, warning 1건.
- CI React 타입 검사·빌드 PASS. 이 검증은 운영 PC 앱 실행이 아니다.
- [CI 요약](windows-ci-summary.json).

기존 전체 회귀 **5,454 PASS / 4 SKIP**은 과거 증거로만 유지했다. 이번 전체 회귀는 실행하지 않았다. 과거 Windows identity timeout 1 FAIL은 무관한 경로여서 재실행하지 않았고 이번 결과로 해소했다고 주장하지 않는다.

### 초기 문제와 최종 실패 구분

- 초기 타입 검사에서 새 아이콘 import/타임라인 타입 오류를 확인·수정했다. 최종 타입·빌드 PASS.
- 최초 비표준 Node 실행에서 Chrome 프로필 오류가 발생했고 정리 경로의 spawnSync 시도 1건을 기존 Guard가 차단했다. 강행하지 않았으며 기존 PASS 환경의 Playwright 전용 Node·임시 프로필/AppData 구성으로 정상화했다. Guard 코드·차단 정책은 완화하지 않았다.
- 이미지 초안이 기존 multipart 폼을 사용하는데 합성 응답이 URL 인코딩으로만 읽던 fixture 오류를 수정했다. 제품 폼/CSRF 계약을 바꾸지 않았다.
- 최종 성공 실행의 Guard 거절 **0**, 신규 FAIL/ERROR **0**. 초기 실패 근거는 로컬 검증 폴더에 보존했다. skip/xfail 추가·단언 삭제 없음.

## 6. 미지원·미검증 및 잔여 조건

- **디자인 인수:** 11개 승인 PNG의 핵심 배치·색·선택 상태는 적용했지만 공통 셸 보존·승인 모달·실제 데이터 유무·미지원 도구 차이가 남는다. 픽셀 완전 일치 PASS로 처리하지 않는다.
- **Windows OS DPI 100/125/150/200%: NOT VERIFIED**. 브라우저 viewport 검증으로 대체하지 않는다.
- **로컬 전체 Python 앱 기동: NOT VERIFIED**. 기존 네이티브 Guard 제한을 그대로 유지했고 사전 import·실행 순서 변경·우회 기동을 하지 않았다. 허용된 Windows Runner의 합성 통합 PASS와 구분한다.
- 실제 유료 AI·계정 권한/가격·SNS OAuth/업로드/게시: **NOT VERIFIED / NOT EXECUTED**.
- Chrome 자체 백그라운드 통신의 OS 수준 전면 차단: **NOT VERIFIED**. Playwright의 애플리케이션 요청 차단만으로 모든 통신이 차단됐다고 주장하지 않는다.
- 참조 기반 유료 이미지 편집, 캐릭터 다중 프로필/저장 스토리 편집/무인 전 과정, TOP 3 실계정 유료 견적 연동, TikTok/Facebook 실전송, 실제 성과 수집 등 기존 미지원·차단 정책은 유지했다.
- 성과 계정 필터는 식별자 있는 자료만 표시한다. 현재 backend 투영에 계정 식별자가 없는 지표는 계정 선택 시 표시하지 않으며 새 조회 Adapter·schema를 만들지 않았다.
- 라이브러리의 유형별 휴지 보관 및 제작실 이동은 기존 계약을 유지했다. 모든 유형의 동등한 파일 복원이나 특정 ID 재진입을 새로 완성했다고 주장하지 않는다.

## 7. 보호 상태·최종 판정

독립 개발 폴더/브랜치만 사용했다. 기존 로컬 미커밋 변경에 reset·clean·stash를 하지 않았고 기존 운영 소스·DB·ledger·설정·API 키·미디어·백업 A/B를 테스트 입력으로 사용하거나 변경하지 않았다. 운영 앱 종료·재시작·배포·main 병합·PR #35 변경·새 PR 생성·유료 AI·OAuth/SNS 호출 없음.

이번 구현 범위는 완료했다. **최종 판정 CONDITIONAL**은 화면별 시각 인수 및 위 미검증 범위를 별도로 남긴다는 의미다. 실제 운영 전환·배포 승인이 아니며 추가 기능 개발은 진행하지 않는다. 다음 사용자 판정을 기다린다.
