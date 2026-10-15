# NewsFlow AI — Phase 5A Autopilot / Easy UI 검증 보고서

확인일: 2026-10-15 (한국 시간). 운영 대상은 Windows 11 / Python 3.12입니다. 기본 주소 `http://127.0.0.1:8765`, 사용자 데이터 `%LOCALAPPDATA%\NewsFlowAI`를 유지합니다. 이번 검증은 합성 뉴스·Offline 대본·무음 검토영상과 로컬 게시 초안에 한정합니다.

## 1. 결과

| 항목 | 판정 | 근거와 한계 |
| --- | --- | --- |
| Autopilot 통합 엔진과 Easy UI | PASS | 기존 수집·분석·영상·게시 초안 서비스를 연결; 외부 서비스 활성화 없음 |
| Cloud 전체 회귀 | PASS | 914 passed / 6 skipped / 1 warning / 0 failed, 총 920개 |
| 기존 테스트 보존 | PASS | 기존 830개 + 신규 90개. 기존 단계/DB head/화면 경로 기대값과 역사적 DB fixture만 조정 |
| Cloud 실제 서버·Chromium | PASS | 간편/단계별 제작, 대본 수정, 실제 영상 재생, 대기함, 취소, 재실행 후 보존 |
| 실제 30초 MP4 2개 | PASS | FFmpeg H.264/AAC, 1080×1920, 약 30.02초; AAC는 무음 |
| Windows Actions 전체 회귀·BAT·Chrome | PASS | 919 passed / 1 skipped / 0 failed; 실제 BAT·Chrome·MP4·재시작 확인 |
| 외부 OAuth·SNS 실행 | PASS | 실행 0건, 기존 차단 유지. 증거 범위는 9절 참조 |
| 사용자 Windows 11 PC·사용자 사용성 평가 | NOT VERIFIED | Cloud/Actions 자동화는 사용자 PC 수동 운영이나 사용성 연구가 아님 |
| Git 브랜치 업로드 | PASS | `feat/newsflow-phase5a`, main과 PR #1~#7 보존 |
| 신규 Draft PR | NOT VERIFIED | 생성 시 GitHub API/GraphQL이 프록시 403으로 거부됨; PR 번호를 만들거나 추정하지 않음 |

Cloud/Windows 구현·합성 동선 검증은 완료했습니다. Draft PR 생성은 접근 오류로 미완료이며 아래에 구분합니다. 실제 서비스 연결·게시 승인은 포함하지 않습니다.

## 2. Autopilot 아키텍처

`GUI → AutopilotCoordinator → PipelineBackend → 기존 서비스`

- Coordinator: UUID 작업 ID, 단일 활성 슬롯과 프로세스 파일 잠금, revision 확인과 SQLite `BEGIN IMMEDIATE`로 상태 변경을 직렬화합니다. 작업·시도·이벤트·산출물 참조·기사 예약을 별도 테이블에 보존합니다.
- Backend: `CollectionCoordinator/NewsService`의 기존 RSS 파싱·중복 제거·분류·저장, `IntelligenceService`, `VideoCoordinator`, `PublishingService`를 재사용합니다.
- 단계: `collect → select → script → render → validate → queue`. 시작·성공·실패와 진행률을 기록하며 잘못된 단계 결과는 성공으로 저장하지 않습니다.
- 체험 뉴스: 내장 합성 RSS 8건을 `FakeRSSAdapter`로 파싱합니다. 실제 기사·실시간 화제성으로 표시하지 않으며 발행시각은 미확인으로 유지합니다. 사용자 출처의 활성 여부를 바꾸거나 실제 RSS를 함께 호출하지 않습니다.
- 등록 출처: 사용자가 명시적으로 선택한 경우 활성 공개 RSS를 최대 20개 수집합니다. 부분 실패를 전체 성공으로 처리하지 않으며 SSRF·TLS·robots 정책을 보존합니다. 이번 실검증에서는 선택된 실제 외부 RSS가 없습니다.
- AI: Autopilot은 명시적으로 `OfflineProvider`를 사용합니다. 환경변수 API 키가 있어도 외부 AI로 전환하지 않습니다. 기존 고급 AI Studio의 별도 동의 경계는 유지합니다.
- 영상: 새 `start_preview`는 `preview_only`가 기록된 검토용 영상만 만듭니다. 기존 `start(reviewed=False)` 거부는 유지하며 사람의 검토 플래그를 대신 승인하지 않습니다. 영상에 “검토용 초안”이 표시됩니다.
- 대기함: 독립 ffprobe·SHA256·대본 revision 확인 후 기존 `PublishDraft`를 생성합니다. `autopilot_task_id` 고유 제약으로 같은 작업의 중복 초안을 방지합니다. 계정 없음, 내용·출처·권리 미확인, 실제 게시 준비 상태는 `blocked`입니다.
- Migration `0008`만 추가합니다. `0001`~`0007`과 OAuth 구현은 변경하지 않았습니다. DB 안에는 영상 원문·API 키·토큰을 새로 저장하지 않습니다.

구현 상세와 Windows 사용법은 [Autopilot 안내](../autopilot.md), [README](../../README.md)를 참고하세요.

## 3. 전체 자동 제작 시나리오

### 간편 제작

초기 설정에서 홈의 **자동 제작 시작** 1회 → 체험 뉴스 수집·중복 제거 → 미사용 기사 선정 → Offline 대본 → 실제 30초 FFmpeg 영상 → 파일 검증 → 로컬 게시 대기함 보관을 확인했습니다. 결과 화면에서 재생 시간이 진행되는 것을 확인했고 MP4 다운로드와 대기함 링크를 사용했습니다. 동일 작업 실행 중 두 번째 시작은 HTTP 409입니다.

### 단계별 제작

뉴스 확인 → 대본 확인 → 영상 확인의 세 지점에서 멈춥니다. AI Studio에서 대본 제목을 수정하여 revision 2가 저장되는 것, 서버 재시작 뒤 동일 대본과 대기 상태가 유지되는 것, 해당 대본으로 영상을 만든 뒤 명시적인 확인 전에는 대기함이 비어 있는 것을 확인했습니다. 다른 기사로 진행하여 같은 뉴스의 중복 자동 제작도 방지했습니다.

다음 단계로 진행하는 것은 SNS 게시·저작권·사실 확인 승인이 아닙니다. 영상 제작 후 대본을 변경하면 기존 영상을 새 대본의 결과로 재연결하지 않습니다. 고급 Video Studio에서 변경한 대본을 확인하고 새 영상을 제작할 수 있습니다.

## 4. GUI 변경 전후와 검증 자료

| 이전 동선 | Phase 5A 동선 |
| --- | --- |
| 개별 스튜디오에서 수집·분석·대본·영상·게시 초안을 따로 실행 | 홈에서 시작하고 작업 화면에서 진행·오류·결과 확인 |
| 상세 메뉴를 동일 수준에서 탐색 | 홈·자동 제작·대기함·간단한 설정과 접을 수 있는 고급 모드 분리 |
| 개별 작업 이력을 연결해 확인 | 고유 작업 번호와 단계별 산출물로 한 흐름을 조회 |
| 기존 `/` Dashboard | 기존 Dashboard를 `/dashboard`로 보존, `/`는 Easy 홈 |

기존 `/news`, `/ai`, `/video`, `/publishing`, `/settings`를 유지했습니다. 수동 수집 POST도 `/dashboard`로 돌아와 기존 완료 상태 갱신을 유지합니다. OAuth·DB·실행 로그 등은 고급 화면에서 확인합니다.

[이전 Phase 4B-2B Dashboard](phase5a_evidence/before-dashboard.png)와 아래 실제 Cloud 화면을 제공합니다. 이전 화면은 이전 단계의 보존 자료이며 이번 실행 화면으로 표시하지 않습니다.

| 제출 화면 | 자료 |
| --- | --- |
| 메인 대시보드 | [홈](phase5a_evidence/cloud-autopilot/dashboard.png) |
| 자동 제작 시작 | [시작 화면](phase5a_evidence/cloud-autopilot/start.png) |
| 제작 진행 | [진행 화면](phase5a_evidence/cloud-autopilot/progress.png) |
| 완료 영상 | [완료 화면](phase5a_evidence/cloud-autopilot/completed-video.png) |
| 게시 대기함 | [대기함](phase5a_evidence/cloud-autopilot/queue.png) |
| 오류 원인과 해결 | [등록 출처 없음 안내](phase5a_evidence/cloud-autopilot/error-guidance.png) |
| 간단한 설정 / 고급 설정 | [간단한 설정](phase5a_evidence/cloud-autopilot/simple-settings.png), [고급 설정](phase5a_evidence/cloud-autopilot/advanced-settings.png) |
| 단계별 검토 | [대본](phase5a_evidence/cloud-autopilot/guided-script-review.png), [영상](phase5a_evidence/cloud-autopilot/guided-video-review.png) |
| 모바일 / 확대 | [320px](phase5a_evidence/cloud-autopilot/mobile-320.png), [CSS 200%](phase5a_evidence/cloud-autopilot/desktop-200percent.png) |

자동화된 실제 동선은 PASS이며, 단순 렌더링으로 사용성을 통과 처리하지 않았습니다. 320px 및 CSS 200% 확대에서 홈·시작·결과·대기함·설정의 가로 넘침과 주요 제목/버튼 접근을 확인했습니다. Windows 브라우저 메뉴의 네이티브 확대, 스크린리더 전체 동작, 실제 초보 사용자 사용성 평가는 NOT VERIFIED입니다.

## 5. 상태·취소·복구 정책

- 한 데이터 폴더에는 실행 중 또는 검토 대기 중인 자동 작업 하나만 허용합니다. 여러 탭·프로세스의 오래된 revision 요청은 거부합니다.
- 수집·분석·렌더의 외부 효과를 시작하기 전에 할당된 기존 서비스 ID를 기록합니다. 기록 실패 시 해당 효과를 시작하지 않습니다. 재시도는 저장된 참조와 실제 상태를 대조합니다.
- 취소 시 추가 단계를 시작하지 않고 완료된 기사·대본·MP4·초안은 보관합니다. 렌더 취소는 해당 렌더 ID에만 적용합니다. 진행 중 수집/분석은 현재 요청 또는 timeout까지 기다릴 수 있습니다.
- 재시작 시 미완료 작업은 `interrupted`, 미완료 시도는 `unknown`입니다. 자동 재시도나 자동 성공 전환은 없습니다. 살아 있는 다른 프로세스의 작업을 복구 로직으로 덮어쓰지 않습니다.
- 단계별 검토를 취소했다가 재개해도 검토 대기 화면을 복원하며 다음 단계를 건너뛰지 않습니다.
- 기사 예약은 실패/취소 후에도 유지합니다. 같은 작업에서 안전하게 재시도하거나 다른 뉴스로 새 작업을 만듭니다. 고급 스튜디오에서 명시적으로 수정·재제작하는 것은 별도입니다.
- Fake Render의 비재생 파일은 완료 MP4나 대기함 등록으로 승격하지 않습니다. 파일 변경·대본 revision 불일치·타 기사 참조 혼용·검토 플래그 위조는 실패로 처리합니다.

## 6. Cloud 전체 회귀와 실제 실행

최종 코드: `80ff59a7c2a774ea92c5cfb076b76ab83327a9c1`.

```text
python -m pytest -q -rs --junitxml=/tmp/newsflow-phase5a-validation/pytest.xml
python -m ruff check src tests tools
python tools/ci_autopilot_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase5a-validation/autopilot
python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase5a-validation/legacy
```

전체 920개 중 914 passed / 6 skipped / 0 failed입니다. Skip은 실제 RSS opt-in 1건과 native Windows 검증 5건입니다. Starlette/httpx 기존 deprecation warning 1건은 제거하거나 숨기지 않았습니다. [pytest 출력](phase5a_evidence/cloud-pytest.txt), [JUnit](phase5a_evidence/cloud-pytest.xml), [요약](phase5a_evidence/cloud-test-summary.json)을 보존합니다.

[Autopilot 브라우저 증거](phase5a_evidence/cloud-autopilot/autopilot-result.json)는 실제 서버·Chromium·동일 Origin/CSRF POST·두 제작 모드·재생·수정·취소·오류·확대·재시작 보존 결과입니다. [기존 GUI 회귀](phase5a_evidence/cloud-legacy-result.json)는 출처 등록/활성화·수집·검색·AI/Video/Publishing POST, 30초 영상, OAuth 위조 시작 차단과 기존 데이터 재실행을 별도로 검증했습니다. Cloud에서 BAT나 native DPAPI를 실행했다고 주장하지 않습니다.

검증 중 발견한 실패는 숨기지 않았습니다. 첫 전체 회귀의 3건은 이전 DB fixture에 새 ORM 컬럼이 포함된 문제 2건과 이전 Dashboard 경로 기대값 1건이었습니다. 실제 과거 스키마를 반영해 fixture를 넣고 기대 경로를 수정했습니다. 별도 실제 브라우저에서는 수동 수집 후 새 홈으로 이동하는 오류를 발견하여 `/dashboard`로 복귀하게 고쳤습니다. 같은 동선 재검증은 PASS이며 기존 테스트를 삭제하거나 보안 검사를 완화하지 않았습니다.

## 7. Windows Actions·BAT·Chrome

새 `.github/workflows/newsflow-phase5a-windows.yml`은 이 feature 브랜치 push에만 실행됩니다. `windows-latest`, Python 3.12, 전체 pytest, 기존 합성 native DPAPI/운영 Vault·다른 사용자 거부, 실제 `run.bat`, health, 종료·포트 충돌·재시작·LOCALAPPDATA·Chrome POST를 유지합니다. Easy UI의 실제 30초 영상 두 개와 단계별 수정·취소·대기함 동선을 추가했습니다. 실제 API 키는 등록하지 않았고 RSS는 계속 opt-in입니다.

**PASS — [Windows Actions run 38666644966](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38666644966), job 116200040689.** GitHub 공식 실행 페이지의 코드 링크 `80ff59a7c2a774ea92c5cfb076b76ab83327a9c1`, 전체 run `Success`, 모든 step `success` 및 검사 annotation을 확인했습니다. API 접근 차단으로 웹에서 읽었으며 [원본 결과를 구조화한 증거](phase5a_evidence/windows-actions-evidence.json)를 보존합니다.

| Windows 실제 검사 | 결과 |
| --- | --- |
| 전체 pytest | **919 passed / 1 skipped / 0 failed**, 총 920개. 실제 RSS opt-in만 skipped |
| 실제 BAT와 서버 | PASS: health, HTTP POST, 종료, 포트 충돌/중복 실행 거부, LOCALAPPDATA 경로 |
| SQLite와 재시작 | PASS: 저장·재조회, 수정 대본·검토 대기·MP4·게시 초안 보존 |
| 기존 Chrome GUI | PASS: 출처 등록/토글/수집, 검색, AI·Video·Publishing POST 및 OAuth 위조 요청 차단 |
| Easy Chrome GUI | PASS: 간편 제작 1클릭, 진행률, 단계별 대본 수정/영상 확인, 취소, 오류 해결 안내, 고급 설정 진입 |
| 실제 Autopilot MP4 | PASS: 간편/단계별 각 30초, H.264/AAC, 1080×1920, 30fps, 실제 재생 시간 진행 |
| 화면 레이아웃 | PASS: 320px, CSS zoom 200%로 5개 화면 검사; 네이티브 메뉴 확대는 NOT VERIFIED |
| DPAPI 보안 회귀 | PASS: 합성 자격 증명만 사용, current-user 암호화/회전/변조 거부/다른 프로세스/다른 Windows 사용자 거부 |
| 로컬 TTS | PASS: 설치된 SAPI 음성의 WAV→MP4 짧은 샘플 생성. 한국어 발음·청취 품질은 NOT VERIFIED |
| 외부 OAuth·SNS | PASS: 실제 호출 0, 환경/GUI production activation 차단 유지 |

Windows 두 30초 MP4의 크기·SHA256·ffprobe는 해당 증거의 `NewsFlow Autopilot easy_video`와 `guided_video` annotation에 있습니다. Windows 원본 스크린샷·영상은 run의 `newsflow-phase5a-windows-validation` artifact에 보존되며 보존 기간은 7일입니다. 이번 다운로드 ZIP에 넣은 스크린샷·MP4 원본은 Cloud 산출물입니다. Windows annotation의 요약을 Windows 원본 영상 다운로드와 혼동하지 않습니다.

자동 종료 검증은 `taskkill` 프로세스 트리 종료를 사용했습니다. 사용자 Windows 11 PC의 수동 Ctrl+C, 실제 브라우저 메뉴 확대와 사람의 사용성·음성 품질은 여전히 NOT VERIFIED입니다. 앞선 코드 실행은 수정 커밋으로 대체되었으며 최종 판정은 위 run에만 근거합니다.

## 8. 생성 영상과 게시 대기함

| 파일 | 확인 결과 |
| --- | --- |
| [간편 제작 30초 MP4](phase5a_evidence/cloud-autopilot/easy-30s.mp4) | H.264/AAC, 1080×1920, 30fps, 30.021029초, 실제 브라우저 재생 |
| [수정 대본의 단계별 30초 MP4](phase5a_evidence/cloud-autopilot/guided-30s.mp4) | 같은 규격, 수정 대본 사용, 명시적 영상 확인 후 대기함 보관 |

합성 실행 DB에는 기사 8건, 대본·영상·게시 초안 각 2건, 게시 작업·시도 0건이 남았습니다. 모든 생성 대본은 `review_required`, 영상은 `preview_only`, 초안은 계정 없음/검토 미확인/게시 차단입니다. MP4의 SHA256와 ffprobe 상세는 브라우저 증거 JSON에 있습니다. 영상 재생·규격 PASS를 음성 품질·사실성·콘텐츠 편집 품질 PASS로 해석하지 않습니다.

## 9. 외부 서비스 호출과 보안 경계

검증 시 실제 OAuth 시작·code exchange·refresh·revoke 카운터는 모두 0, 모드는 `OFFLINE/BLOCKED`였습니다. 기존 Publishing safety도 실제 게시/OAuth 0건이며 `external_execution_enabled=false`입니다. 합성 실행의 PublishJob/PublishAttempt는 0, 활성 외부 RSS 출처는 0, AI provider는 offline뿐이고 실제 credential reference가 있는 계정은 없습니다. 브라우저 외부 HTTP origin은 빈 목록입니다.

이 증거는 실행 경로의 카운터·DB 상태·브라우저 요청과 외부 호출을 금지하는 회귀 테스트를 함께 확인한 것입니다. OS 전체 패킷 캡처나 실제 서비스 인증 성공을 주장하지 않습니다. 개발용 GitHub·패키지 다운로드는 OAuth/SNS 호출 0건과 별개입니다.

CSRF·Origin·Host·CSP·SSRF·TLS·robots 경계를 유지했습니다. HTML은 기존 escaping을 사용하고 JS는 `textContent`와 동일 origin 요청을 사용합니다. 로그/이벤트에는 Provider 원문 예외 대신 고정 오류 분류를 저장합니다. 기존 synthetic-only/production credential boundary는 변경하지 않았으며 환경변수·GUI 플래그로 실인증·게시를 열지 않습니다.

## 10. 변경 파일과 Git

- 새 `autopilot/` 계약·코디네이터·서비스 연결·체험 RSS, DB 모델/추가 migration 0008.
- 새 Easy 라우트·홈/시작/작업/대기함/간단한 설정 템플릿·CSS/JS, 기존 메뉴와 수동 수집 복귀 경로.
- 기존 서비스에 할당 ID 기록 callback, 출처별 수집, 검토용 영상/작업별 취소, 게시 초안 작업 ID 고유성만 추가.
- 앱 wiring/종료 순서/실행 중 작업 복구, 버전 `0.5.0a1`, 기존 DB 이전 도구 head 지원.
- 신규 테스트 90개와 기존 테스트의 schema/path/stage 기대값, CI 도구/새 Windows workflow, README·안내·보고서.

[전체 변경 파일](phase5a_evidence/changed-files.txt)에 목록을 보존합니다. JSBAE의 다른 프로젝트와 기존 Windows workflow는 수정하지 않았습니다.

- 분기 기준: `72b274314f220a1f03ff5b52b5c65123ea34acd0` / `feat/newsflow-phase4b2b`.
- 구현 커밋: `6d73a492cdd6d0eae51b322b4688e64538a0eda6`.
- 최종 코드 커밋: `80ff59a7c2a774ea92c5cfb076b76ab83327a9c1`. 이후 제출 커밋은 이 보고서·증거·ZIP만 추가하며 실행 코드/테스트는 동일합니다.
- 작업 브랜치: `feat/newsflow-phase5a`, 원격 업로드 완료.
- Draft PR: **미생성**. `gh pr create --draft`가 `https://api.github.com/graphql`의 Forbidden으로 실패했습니다. Git 읽기/업로드와 GitHub 웹 Actions 조회는 성공했으나 API는 proxy CONNECT 403입니다. 네트워크·프록시·TLS·자격 증명을 변경하지 않았습니다. [접근 결과](phase5a_evidence/github-access.json).
- [브랜치 비교 및 PR 준비](https://github.com/jsbae1979-prog/JSBAE/compare/feat/newsflow-phase4b2b...feat/newsflow-phase5a?expand=1). API 접근 복구 후 이 base/head로 **Draft** PR을 생성해야 합니다. PR 번호를 추정하지 않았습니다.
- main 및 기존 PR #1~#7은 병합/수정하지 않았습니다. [Git 보존 확인](phase5a_evidence/git-preservation.json).

Cloud 환경 설정에는 검증한 의존성 설치와 시작/검사 절차를 `install_script`·`start_skill`로 저장했습니다. 네트워크·비밀값은 변경하지 않았습니다. 저장은 새 환경 적용/발행을 의미하지 않습니다. 환경 설정에서 내용을 검토·저장한 뒤 Publish해야 하며, 새 작업에서의 복원은 NOT VERIFIED입니다. [설정 저장 결과](phase5a_evidence/environment-setup.json).

[다운로드 ZIP](phase5a_autopilot_easyui_report.zip)은 보고서, 화면 이미지, Cloud 샘플 MP4, Cloud/Windows 검사 증거, README와 Autopilot 안내를 포함합니다. DB·개인정보·세션 비밀값·토큰은 포함하지 않습니다.

## 11. 미구현·미검증 항목과 다음 단계

- 실제 RSS 수집, 외부 AI API, 실제 Google/Instagram 로그인·서비스 토큰 발급/저장·SNS 업로드/게시: NOT VERIFIED. 이번 단계에서 실행하지 않았습니다.
- 사용자 Windows 11 PC 설치·수동 종료·실제 브라우저 확대·초보 사용성 연구: NOT VERIFIED. Windows Actions runner와 구분합니다.
- 한국어 TTS 발음 및 30/45/60초 완성 콘텐츠의 사람에 의한 품질 평가: NOT VERIFIED. 자동 흐름의 기본 음성은 무음이며 실브라우저 MP4 확인은 30초에 한정합니다.
- 신규 PC는 기존 Python 3.12, FFmpeg/ffprobe, 한국어 글꼴 준비가 필요합니다. BAT는 FFmpeg를 자동 설치하지 않습니다. 준비된 환경에서 홈 한 번 클릭을 검증했으며 무설치 실행이라고 주장하지 않습니다.
- 검토용 영상에는 자동 외부 소재 다운로드·저작권 판정·사실 확인 완료 기능이 없습니다. 사용자가 내용을 검토해야 합니다.
- 실제 브라우저/합성 검증이 완료되어도 신규 Draft PR 생성이 남아 있으므로 Git 제출 완료 조건 전체를 충족했다고 표시하지 않습니다.

다음 작업은 GitHub API 접근 복구 및 신규 Draft PR 생성, 사용자 Windows 11에서 초기 설치와 간편/단계별 동선 확인, 초안 내용·음성·영상 품질의 사용자 검토입니다. **Phase 5B 스케줄러와 Phase 4B-2C 실계정 연결은 시작하지 않습니다.** 실제 SNS 게시와 main 병합도 수행하지 않습니다. 보고서 제출 후 사용자 승인을 기다립니다.
