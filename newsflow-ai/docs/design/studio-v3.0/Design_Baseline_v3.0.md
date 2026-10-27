# NewsFlow AI Studio — 최종 UX/UI 통합 설계 기준 v3.0

- 작성 기준: 2026-10-26 KST
- 성격: **설계 및 구현 준비 명세**, 코드 구현·운영 배포 완료 보고서 아님
- 기준 GitHub: [`jsbae1979-prog/JSBAE`](https://github.com/jsbae1979-prog/JSBAE)
- 이번에 확인한 원격 개발 브랜치: `codex/newsflow-step15b-20261026`
- 커밋: `b1eadb3686bfe5765ab1aa64d51688e180980b97` (2026-10-26 18:25 KST)
- 상태: 사용자가 기존 기능 개발 완료를 알림. 원격 Step15B 기록은 CONDITIONAL이며, 미반영 PC 로컬 변경은 검사하지 못함.

## 1. 변경 불가 마스터 디자인 결정

**`마스터_대시보드_사용자선정원본.png`가 사용자 선정의 최우선 시각 기준**이다. v2.4 통합 HTML은 작업 흐름·상호작용 참고용으로 사용하고, 원본 대시보드를 v2.4 수준으로 다운그레이드하지 않는다.

- 마스터: 네이비 공간감, 시안/보라 글로우, 대형 글로벌 비주얼과 영상/캐릭터 콘텐츠, 왼쪽 앱 메뉴, 중앙 히어로+프로젝트+빠른 제작, 오른쪽 작업 상태/일정/API 서비스/최근 활동.
- 타이포그래피와 카드 계층을 재현하되 화면 전체를 한 장의 이미지로 덮지 않는다. Hero 일러스트 등 합법적인 정적 장식만 자산으로 사용, 실제 카드/검색/수치/상태/일정은 DOM 요소와 서버 데이터에 바인딩한다.
- 원본의 예시 날짜, 가짜 KPI, AI 서비스 연결 표시, 요금제·사용자 이름은 실제 데이터로 대체하고 데이터 없는 경우는 미수집/미연결 상태로 표시한다.
- 1920×1080 기준, 1366×768 필수, Windows DPI 100/125/150/200%; 390 모바일은 보조 미리보기이고 최종 제품 타깃은 Windows.
- 시각 토큰: background `#0C1424`, surface `#19243A`, primary `#6D5DF6`, accent `#20C5D8`, text `#F5F7FF`, shell sidebar 240px (접힘 72px), header 64px. 44px 수준의 주요 조작 목표; 한국어 텍스트 대비·키보드·motion 감소 준수.

## 2. 최종 화면 정보 구조: 12개 그룹

| No. | 신규 화면 | 핵심 구성 |
|---|---|---|
| 01 | 대시보드 | 선정 마스터 비주얼, 작업/KPI, 최근 프로젝트, 빠른 제작, 연결 상태 |
| 02 | 콘텐츠 제작 홈 | **뉴스 쇼츠 / 캐릭터 쇼츠 / 이미지** 3가지 상위 유형, 프로젝트 재진입 |
| 03 | 뉴스 스튜디오 | RSS, SerpApi/AI 검색, 수집, 기사·출처·화제성 선정, AI 분석 |
| 04 | 뉴스 쇼츠 제작실 | 9:16 미리보기, 대본/자막/음성, FFmpeg·AI장면, 타임라인 |
| 05 | 캐릭터 쇼츠 제작실 | 캐릭터 PNG, Claude 스토리, 공식견적, 장면검토, 최종합성 |
| 06 | 이미지 스튜디오 | **독립 AI 이미지 생성** + **뉴스 이미지 카드/상위 3건 피드** 두 워크플로 탭 |
| 07 | 자동화 센터 | Autopilot, 예약(일/요일/단발), 실행 이력, 취소·안전복구 |
| 08 | 콘텐츠 라이브러리 | 원본 파일과 썸네일, 프로젝트, 대본/이미지/영상, 휴지통 |
| 09 | 게시 스튜디오 | 플랫폼별 승인, YouTube·Instagram·TikTok·Facebook, 예약 달력 |
| 10 | 성과·비용 | 실측 게시 지표, AI 토큰/공급사 사용량, 추정 비용과 청구액 구분 |
| 11 | 설정·관리 | API, 모델, 키, 권한, SNS 계정, Windows 운영·진단 |
| 12 | 초기 설정·공통 | 7단계 초기설정, 검증, 연결안내, 오류·승인·알림 |

### 2.1 이미지 영역의 중요 변경 (최신 GitHub 반영)

**독립 `/image-studio`와 기존 `/image-posts`는 같은 기능이 아니다.**

- `AI 이미지 생성`: 텍스트 프롬프트, OpenAI 이미지 모델 선택(현재 등록 2종), 5가지 크기, 3가지 품질, 생성 전 초안·승인, 결과 JPEG 미리보기·다운로드, 검토 후 뉴스/캐릭터 소재 재사용.
- `뉴스 이미지 게시물`: 기사·기존 대본, 뉴스 카드/상위 3건 피드, Claude 문구·디자인 지시문, OpenAI 배경·전체 이미지, 검토·출처·게시 준비.
- 참조 이미지는 독립 이미지 스튜디오에서 안전하게 **로컬 보관·선택**될 수 있으나, 그 이미지를 유료 이미지 생성의 참조로 전송하는 edit adapter는 **미구현**. 같은 버튼으로 통합하지 않는다.
- 이미지 직접 SNS 게시의 실계정 성공은 검증되지 않았으므로 연결 상태를 표시하고 실제 승인 전까지 차단한다.
- 관련 코드: `gui/creation_routes.py`, `creation/image_studio.py`, `creation/catalog.py`, `gui/image_post_routes.py`.

## 3. 화면·컴포넌트 구조

- 프런트엔드 제안: React + TypeScript + Vite + Tailwind + shadcn/ui + Lucide. 기존 Python FastAPI와 별도 개발 폴더.
- 공통: `AppShell`, `GlobalSearch`, `Navigation`, `WorkspaceLayout`, `MediaFrame`, `VerifiedVideoPlayer`, `MediaAssetTile`, `SceneTimeline`, `StoryboardReview`, `ImageCanvas`, `ApprovalDialog`, `CostApproval`, `ErrorRecovery`, `WorkItemState`, `ConnectionReadiness`.
- 메뉴는 내부 `ContentTypeRegistry`에 모듈을 등록하는 구조; 외부 동적 플러그인/임의 코드 실행은 이번 범위에서 제외.
- React UI는 기존 HTML/Jinja2를 wrapper로 두지 않는다. 현재 렌더링·계정·데이터 엔진은 재작성하지 않는다.

## 4. 미디어 및 서버 계약

- 사용자 미디어는 파일 존재·상태·권한 확인 후 서버에서 제공한 로컬 same-origin URL만 사용.
- 목록용 작은 WebP를 세로 메인 프리뷰로 확대하지 않는다. 실제 MP4는 `GET /video/jobs/{job_id}/file`, AI 장면은 `GET /video/ai/scenes/{scene_id}/clip`, 캐릭터는 `/character/{job_id}/file`, 이미지 직접생성은 `/image-studio/{identifier}/file`, 이미지 게시물은 `/image-posts/{id}/file`를 기존 정책에 따라 연결.
- `technical_status`, `review_status`, `publish_approval_status`를 별개로 유지. **완성 파일 = 사실검증/저작권 확인/게시 승인 완료가 아니다.**
- `result_unknown`은 성공/실패로 임의 변경하거나 동일 유료 요청을 자동 재전송하지 않는다.
- 새 JSON API는 기존 서비스에 얇은 adapter로 연결. CSRF, Origin, CSP, trusted-host loopback, 수정 revision, 사용 승인, 결괏값, idempotency, DPAPI/키 비노출, 결과 불명 규칙 유지.
- 독립 이미지 스튜디오에는 `reference`가 있어도 API 참조기반 편집 생성은 실제 지원하지 않으므로 명확히 안내.
- 작업 상태의 GET 요청이 공급사 동기화를 일으킬 수 있으므로 무제한 폴링 금지.

## 5. 프로젝트·파일 보존

- 기존 `ContentDraft`, `VideoProject`, `RenderJob`, `AIVideoPlan`, `AutopilotJob`, `ImagePost`, `ProductionSchedule`, `PublishDraft` 및 캐릭터 `jobs.json`의 저장 관계를 UI read model로 표시.
- 현재 DB 스키마 전체를 통일된 `Project`로 강제 마이그레이션하지 않는다.
- 원본 데이터 기본 위치 `%LOCALAPPDATA%\NewsFlowAI`. 프로젝트 원본, 비밀정보, `session.key`, DPAPI, DB/WAL, 비디오, 키 파일, 예약/승인/감사 기록은 변경·로그/저장소 반출 금지.
- 사용자가 여러 PC에서 설치할 수 있도록 설계하되 PC마다 해당 Windows 사용자 데이터는 구분하고 공유 로그인/클라우드 서버 인증을 새로 주장하지 않는다.

## 6. 실제 개발 구현 순서 (불필요한 중복 Gate 최소화)

A. **코드 기준선 동기화**: 최신 PC 작업트리/마지막 SHA와 GitHub `codex/newsflow-step15b-20261026` 비교. 임의 reset/stash/clean/merge 금지. 이전 UI PR35는 Draft이며 재사용 가능 여부만 확인. 최초 51개 기능 그룹을 최신 56개 그룹으로 갱신한 뒤 세부 라우트/버튼 대조.

B. **새 React 셸 + 원본 대시보드·콘텐츠 제작 홈**: 최초 기준 이미지와 비교하여 레이아웃을 먼저 맞춘다. CSS 색상만 바꾼 기존 HTML 화면을 완료 처리하지 않는다. 디자인 기준 1차 검토.

C. **3개 전문 제작실**: 뉴스/캐릭터/이미지(이미지 내부 2가지 워크플로)를 구현하고 실제 Python 서비스의 read-only 조회부터 연결. 이후 저장·작업 상태·유료 승인 등 명령 연결.

D. **나머지 7개 업무 화면 및 공통 화면**: 뉴스·자동화·라이브러리·게시·분석·설정·초기설정 순차/독립 병렬 적용.

E. **검증·전환 보고**: 디자인/기능/보안/Windows 결과를 나눠 제출. 이 단계에서 운영 적용·main 병합·기존 HTML 삭제는 수행하지 않는다.

## 7. 최종 인수 기준

| Gate | 실제 제품 합격 조건 |
|---|---|
| Design | 최초 마스터 대시보드 구성·이미지·색상·타이포·패널 비율에 근접. 12화면의 실제 1920/1366캡처 비교·차이 기록. 사용자 승인 필요. 가짜 KPI 허용 불가. |
| Function | 56개 기능그룹 + 최신 라우트·폼·버튼 전수 대조. 없어지는 기능 0, 의도적 미지원 표시. 실제 주요 시나리오 저장·재진입·미디어·승인 테스트. |
| Security | CSRF·Origin·CSP·DPAPI·사용자별 데이터, 예산·유료승인, 결과불명·재시도 차단, 파일·권리 검증 유지. |
| Windows | Windows11, DPI 100/125/150/200% 및 1920/1366, 시작/종료/다시실행, 기존 프로필 불변 확인. 설치형 배포는 별도 Gate. |
| Regression | 기존 회귀 실측 구분, 재사용 증거 명시, 새 중대 실패 0. 디자인 PASS와 기능 PASS 혼동 금지. |

## 8. 최신 기능 코드와 배포 상태 (2026-10-26)

- `codex/newsflow-step15b-20261026` 원격 커밋 `b1eadb3686bf`. 이전 Step13J는 최신 코드 기준이 아니다.
- Step13K: 독립 이미지 생성·모델 설정·기존 이미지 카드 보존; Fake 검증. 참조 기반 유료 편집 생성 미구현.
- Step13K-Fix: Windows 종료 최소 수정과 반복 검사 통과.
- Step15A/B: Windows 기술 EXE와 **현재 PC 합성 데모** 실행/종료/재실행 검증. 원격 최종 보고 판정 **CONDITIONAL**.
- 최신 보고서에 따르면 단일 전체 회귀 **5,454 PASS / 0 FAIL / 0 ERROR / 4 SKIP**는 Step15B 이전 증거 재사용 결과이며, Step15B에서 전체 회귀 재실행은 0회.
- **CI 잔여 FAIL 1건**: Windows Server2025 identity 테스트 PowerShell 관련 20초 TimeoutExpired. 신규 React UI 자체를 못 만드는 이유는 아니지만 일반 설치·배포 인수 시 해결/승인된 위험 수용 필요.
- EXE는 onedir 기술 데모이며 별도 현재 PC Python 도우미에 의존. 새 PC·Python 미설치 환경, 실계정 API/OAuth/SNS 게시, 설치/업데이트/서명·배포는 미완료/미검증.
- `main`에는 현재 NewsFlow AI 개발 코드가 반영되지 않았고 UX PR #35는 Draft/open. 자동 병합 금지.

## 9. 확인 자료

- [Step15B 최종 보고](https://github.com/jsbae1979-prog/JSBAE/blob/codex/newsflow-step15b-20261026/newsflow-ai/docs/validation/step15b/REPORT.ko.txt)
- [Step13K 제작 모델 보고](https://github.com/jsbae1979-prog/JSBAE/blob/codex/newsflow-step15b-20261026/newsflow-ai/docs/validation/step13k/REPORT.ko.md)
- [새 이미지 제작 라우트](https://github.com/jsbae1979-prog/JSBAE/blob/codex/newsflow-step15b-20261026/newsflow-ai/src/newsflow/gui/creation_routes.py)
- [UI 기존 PR 35](https://github.com/jsbae1979-prog/JSBAE/pull/35)
- `NewsFlow_Master_Experience_v2.4.html`: 클릭 가능한 이전 설계 시안, 실제 제품 아님
- `STEP18_Media_Component_Contract_v2.5.md`: 이전 미디어 상태 설계 참조

## 10. 최종 판정

**DESIGN BASELINE READY FOR IMPLEMENTATION — CONDITIONAL**.

최신 코드의 실제 구현·배포 위험을 구분해 기록했고 사용자 원본 마스터 디자인을 기준으로 착수할 수 있다. 운영 배포·실계정 API 검증과 원본 코드/데이터 변경 권한을 부여한 것은 아니다. Codex PC 최종 작업 트리·해시 확인 전 원격 브랜치가 절대 최신이라는 보장은 없다.