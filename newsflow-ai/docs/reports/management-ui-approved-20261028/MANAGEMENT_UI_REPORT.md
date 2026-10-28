# NewsFlow AI 관리 화면 5개 승인 디자인 적용 결과

최종 판정: **CONDITIONAL**. 5개 관리 화면을 독립 React 구조로 적용했고 주요 패널 배치의 MAJOR 차이는 남기지 않았습니다. 최종 사용자 시각 인수, 실제 Windows 11 데스크톱 및 OS DPI는 별도입니다. 운영 전환·배포 승인이 아닙니다.

## 기준과 변경 범위

- 브랜치: `codex/newsflow-management-ui-approved-rebuild-20261028`
- 기준 개발 코드: `8ecf7e29f3d73a598e26d68d388a7a3ec232e0f6`
- 최종 검증 제품·테스트 코드: `5a05167d762bcea7b65a4c7a06d3c2c1208a9ff3`. 이후 커밋은 이 보고서·캡처만 보존합니다.
- 승인 원본: `e6e493c0dbd5ab8ef017d716f466d715ec9896a9`, `newsflow-ai/docs/design/approved-20261027/approved-assets/`. 5개 파일 SHA-256과 1536×1024 규격은 [자산 근거](evidence/APPROVED_ASSET_EVIDENCE.json)에 보존.
- 기존 `?? validation/` 변경을 보존했습니다. reset/clean/stash/force push 없음. 기존 핵심 제작실 브랜치는 기준 8ecf7e2 유지.
- PR #35는 Draft·open·미병합, HEAD `75626f74cc1bfe750d24132e44019bcda478247b`를 읽기 전용 확인. PR 변경/신규 생성 없음. main 변경·병합 없음.

## 화면별 디자인·기능

| 화면 | 판정 | 실제 적용 | 남은 차이·데이터 제약 |
|---|---|---|---|
| 자동화 센터 | **MINOR** | 상단 빠른 작업, 좌측 제작 유형/현황, 중앙 예약 테이블, 우측 선택 예약 상세, 하단 실행 이력 | 실제 서비스가 지원하는 뉴스 예약만 표시. PNG의 가상 캐릭터/TOP3 무인 유료 유형·예약 템플릿은 추가하지 않음. 실행 이력 없는 경우 빈 표. 저장/활성화는 기존 별도 승인 창. |
| 라이브러리 | **MINOR** | 좌측 유형·검색·기간, 중앙 4열 카드/목록, 우측 9:16 미리보기·다운로드·활용, 전체/내 콘텐츠/샘플 | 실제 파일 없는 경우 빈 썸네일. 합성 뉴스 MP4는 기존 샘플12초 참고 영상. 실제 제작 수량·날짜·길이를 PNG 예시로 채우지 않음. |
| 게시 스튜디오 | **MINOR** | 콘텐츠 목록 / 영상+편집 / 플랫폼·계정·검토 3열, 하단 일정·승인·결과 | 계정 등록은 인증 성공과 별개. 필수 승인 문구·Revision 복구는 기존 모달에 유지. 1366px 세로 스크롤 허용. PNG에만 있는 AI 썸네일 추천·즐겨찾기 등의 새 유료 기능은 만들지 않음. |
| 성과·비용 | **MINOR** | 상단 요약·기간, 간결한 플랫폼/계정 선택, 콘텐츠 성과·실제 사용량 추이, 우측 미리보기/예상 비용·계정 비교 | 미수집 지표/청구액은 미확인. 실제 기록이 없는 수익·비율·차트 생성 안함. 중립 원형은 비용 미확정 상태 표시이며 실제 공급사별 배분 차트가 아님. |
| 설정·관리 | **MINOR** | 7개 탭, 시작 가이드, 개별 Instagram 다중 계정/4플랫폼 카드, Windows·모델·기본값·RSS·시스템 패널 | 1366px에서는 실제 계정 카드가 다음 행으로 감겨 스크롤이 늘어납니다. 미지원 트레이 토글/새 저장경로 이전/일괄 저장은 만들지 않음. 기존 설정별 저장과 사용자 승인 유지. 모든 연결 성공/키 값 노출 없음. |

색상은 네이비 배경·보라/시안 선택 강조·청색 카드 테두리로 맞췄습니다. 원본의 개별 아이콘/브랜드 일러스트를 무단 추출하지 않고 기존 lucide와 CSS를 사용하여 아이콘 형태·발광·폰트 렌더링에 작은 차이가 있습니다. UI는 실제 입력·선택·상태·핸들러를 가진 React 컴포넌트이며 전체 PNG를 배경으로 덮지 않습니다.

[원본·전·후 2해상도 비교](visual-comparison.html) · [패널 좌표·폭 비율·색상·오버레이 차이 수치](DESIGN_DIFF_METRICS.json).

비교 원본은 1536×1024이며 캡처는 서로 다른 종횡비의 1920×1080/1366×768입니다. 오버레이는 원본의 종횡비를 보존한 contain/pad 파생본입니다. 차이 수치는 데이터·텍스트·빈 상태·시간·폰트 차이를 모두 포함하므로 픽셀 일치율이나 PASS 기준으로 사용하지 않았습니다. 가로·세로를 별도로 정규화한 추가 오버레이도 제공합니다. 이는 패널의 상대 좌표 비교용이며 미디어·폰트가 왜곡되므로 원본 품질 판정에 사용하지 않습니다. 시각 판정은 핵심 패널 배치의 수동 비교이며 사용자 최종 인수를 대체하지 않습니다.

## 주요 패널 폭 측정

승인 PNG의 테두리를 수동으로 읽은 대략의 폭 비율과 실제 DOM 측정입니다. 여백을 제외한 패널 폭의 합을100%로 하며, 수동 경계 오차와 반응형 차이를 포함합니다. 자동 픽셀 합격 점수가 아닙니다.

| 화면/패널 순서 | 원본 대략 비율 | 1920px 실제 | 1366px 실제 |
|---|---|---|---|
| 자동화 · 좌/중/우 | 18.8% / 52.8% / 28.4% | 18.9% / 52.4% / 28.8% | 18.8% / 52.2% / 29.0% |
| 라이브러리 · 좌/중/우 | 16.8% / 57.2% / 26.0% | 16.7% / 57.7% / 25.6% | 16.9% / 57.1% / 26.0% |
| 게시 · 콘텐츠/편집/검토 | 32.7% / 41.0% / 26.3% | 31.2% / 42.2% / 26.6% | 30.0% / 41.7% / 28.3% |
| 성과 · 본문/우측 | 72.3% / 27.7% | 72.2% / 27.8% | 71.4% / 28.6% |
| 설정 · 계정/Windows | 71.1% / 28.9% | 70.8% / 29.2% | 69.1% / 30.9% |

라이브러리의 영상은 실파일 비율을 유지한9:16 프레임이며 PNG 예시의 가로 썸네일을 세로 영상 자체로 바꾸어 표시하지 않습니다. 실제 이미지·MP4가 없는 상태는 명확한 빈 상태로 보존합니다.

## 실제 기능 연결과 보안

- 기존 `useStudio`, `CommandDialog`, 폼 카탈로그와 Python 서비스를 재사용했습니다. 저장·Review·비용·게시 승인 체크를 자동으로 채우지 않습니다.
- 예약 편집에 기존 source/duration/platform/voice를 읽기 모델로 전달해 저장 시 기본값으로 초기화되지 않게 했습니다. 저장만으로 활성화하지 않습니다. 일시정지 예약의 next_run_at은 저장된 시각으로 구분합니다.
- 게시 콘텐츠 변경 시 해당 콘텐츠의 초안·검토 기록으로만 연결합니다. 다른 콘텐츠의 제목·Revision·승인 토큰을 재사용하지 않습니다. Revision 충돌 시 편집 내용을 유지합니다.
- Instagram 다중 계정은 실제 등록 ID로 구분합니다. TikTok·Facebook 실전송 차단, 최종 승인 분리, 기존 unknown/성공 재전송 금지를 유지합니다.
- 라이브러리 샘플 복사·숨김은 기존 사용자별 API와 CSRF를 사용합니다. 원본 샘플은 쓰지 않습니다. 게시 기록에 연결된 영상은 휴지 보관 거부를 확인했습니다. 별도 미연결 합성 영상만 휴지 보관·복원했습니다.
- 검토 완료 ImagePost와 독립 이미지 초안은 다른 ID 공간을 유지합니다. ImagePost를 독립 초안 ID로 재사용하지 않습니다. 개별 원본 작업의 기존 상세 링크도 제공했습니다.
- 성과는 job_id/account_id/기간 필드를 명시적으로 읽어 특정 계정에 임의 귀속하지 않습니다. 금액 없는 견적은 0원으로 바꾸지 않습니다. 공급사 실제 청구액은 미확인입니다.
- 설정의 키 저장 버튼은 공급사별 구분이며 비밀값을 읽거나 복호화하지 않습니다. Windows 상태는 사용자가 눌렀을 때만 조회하고, 이번 CI에서는 합성 상태 응답만 검증했습니다.

## 신규 검증 결과

| 항목 | 이번 결과 | 환경/범위 |
|---|---|---|
| TypeScript | PASS | 최종 Windows Actions, tsc --noEmit |
| Vite | PASS | 최종 Windows Actions. 500KB 초과 JS chunk 경고 유지, 폰트 런타임 응답 성공. 경고 숨김 없음 |
| 신규 API 계약 | **4 PASS / 0 FAIL / 0 ERROR / 0 SKIP** | Windows Python3.14.7, 합성 SQLite, CSRF/Origin·비밀값 비노출·unknown 보존·읽기 필드 |
| 실제 Chrome → React → Python ASGI | **20 PASS / 0 FAIL / 0 ERROR / 0 SKIP** | Windows Server2025 CI, Chrome 156.0.8078.48, 실제 FastAPI create_app/TestClient·합성 DB. localhost18765 페이지 요청을 파일 IPC로 실제 앱에 전달; TCP 서버/Windows11 데스크톱 검증과 구분 |
| 수정 전 기준 캡처 | **11 PASS** (재사용) | run40609939982, 8ecf7e2, 동일 합성 데이터·동일 캡처 조건 |
| 실제 Windows11 GUI/OS DPI100·125·150·200% | **NOT VERIFIED** | 브라우저 viewport를 실제 DPI로 주장하지 않음 |
| 유료 API/OAuth/SNS/운영 EXE | **NOT VERIFIED / 미실행** | 승인 범위 밖 |

최종 실행: [Windows CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40611504906). [API JUnit](evidence/management-api.xml) · [브라우저](evidence/after-gui-results.json) · [실제 Python 응답](evidence/after-backend-summary.json) · [프로세스 정리](evidence/after-process-cleanup.json).

### 새 Chrome 검사 항목

| 검사 | 결과 |
|---|---|
| viewport automation 1920 | PASS |
| viewport library 1920 | PASS |
| viewport publishing 1920 | PASS |
| viewport analytics 1920 | PASS |
| viewport settings 1920 | PASS |
| viewport automation 1366 | PASS |
| viewport library 1366 | PASS |
| viewport publishing 1366 | PASS |
| viewport analytics 1366 | PASS |
| viewport settings 1366 | PASS |
| protected home and five studios presentation | PASS |
| schedule save preserves options and remains paused | PASS |
| publishing edit save and Revision conflict protect unsaved text | PASS |
| publishing has separate review, approval and blocked platforms | PASS |
| library samples copy, hide and restore remain user scoped | PASS |
| library actual MP4 playback and no editable-project claim | PASS |
| library trash and restore use existing confirmation | PASS |
| publishing content selection never edits a different saved draft | PASS |
| analytics account identities, synthetic labels and unknown cost | PASS |
| settings tabs, secret-free key dialogs and saved defaults | PASS |

### 중간 실패·기존 결과 구분

- 첫 CI40609422480은 합성 SocialMetric의 기존 고유키를 잘못 구성해 API2PASS/2FAIL 및 브라우저 준비 실패였습니다. 계정별 게시 Job을 분리해 Fixture만 수정했습니다. DB schema/보안 정책 수정 없음.
- CI40609939982는 API4PASS, 새 브라우저17PASS/2FAIL. 게시 기록 연결 영상 삭제 거부는 정상 보호였고, 독립 휴지 보관 Fixture와 거부 확인을 추가했습니다. 다른 실패는 테스트가 실제 라벨 `품질`을 `이미지 품질`로 찾은 오류를 수정했습니다. timeout 상향·skip/xfail 추가 없음.
- CI40610724312에서 API4PASS/브라우저19PASS. 이후 콘텐츠/초안 ID 연결 범위를 강화했습니다. CI40610889231은 API4PASS/브라우저19PASS·1FAIL(콘텐츠 전환 직후 복원 완료 전 값을 읽은 간헐 대기 오류). 동일 제품 코드의 CI40611052098은 API4PASS/브라우저20PASS였습니다. 제한 시간 상향 없이 React 복원 완료 조건 대기를 보강한 최종 CI40611504906에서도 API4PASS/브라우저20PASS를 확인했습니다. 중간 이력은 [CI 근거](evidence/CI_EVIDENCE.json)에 보존합니다.
- 기존 핵심 제작실 GUI20PASS·집중CI59PASS·샘플API9PASS/GUI21PASS는 기존 증거를 재사용합니다. 이번 신규 실행 수와 합산하지 않습니다. 전체 Python 회귀·Guard 감사·샘플 원본 무결성 검사를 반복하지 않았습니다. 과거 전체 회귀 PASS를 최신 전체 결과로 표시하지 않습니다.

## 보호 대상·운영 환경

- 홈/콘텐츠 제작 홈/핵심 제작실5개 및 공통 셸·샘플·보안·DB 등 **99개 보호 파일의 SHA-256이 기준과 동일**. 기존 LegacyWorkbench 본문 동일. Workbench 변경은 새 관리 모듈5개 분기와 import만입니다.
- 보호7화면×2폭의 계산 스타일/좌표 비교: **14/14 동일**. [소스 증거](evidence/PROTECTION_SOURCE_EVIDENCE.json), [캡처 비교](evidence/PROTECTION_CAPTURE_EVIDENCE.json). 시각 캡처의 시계/생성시각 텍스트 차이를 소스 회귀로 단정하거나 모든 픽셀 동일이라고 주장하지 않습니다.
- CSS는 `.management-ui` 및 그 존재에 한정된 셸 선택자로만 적용합니다. 보호 화면에 진입하면 새 셸 조건이 사라집니다. 기존 핵심 제작실·홈 JSX/CSS 변경 없음.
- Python 변경은 기존 읽기 모델3곳뿐: 성과 ID/기간, 예약의 저장 옵션, 합성/현재 사용자 저장경로·Python버전 메타데이터. 쓰기 서비스·schema·migration·Guard·DPAPI·CSRF·Origin·가격·승인 정책 변경 없음.
- 운영 앱·8765·DB·키·토큰·설정·미디어·백업A/B를 테스트 입력으로 사용/변경하지 않았습니다. 운영 앱 중지/재시작 없음. 이를 확인하려고 운영 비밀값·DB·백업을 다시 열거나 해시 감사하지 않았습니다. 보존 판단은 코드 차이·실행 경로·합성 Fixture·테스트 호출 기록 범위입니다.
- CI의 실제 공급사/SNS 호출0, PublishAttempt0, unknown 예약 보존. 허용 페이지 외부 요청0과 앱 Fixture의 차단을 확인했습니다. Chrome 자체 OS 백그라운드 통신 전부 차단을 입증했다고 주장하지 않습니다.
- 소유 Python 정상 종료/Chrome 잔여0/대기 요청0/강제 정리 없음은 cleanupJSON을 참조합니다. Runner TEMP는 일회성 작업 프로필이며 아티팩트는 테스트 증거만 보존합니다.

## 변경 파일

- `.github/workflows/newsflow-management-ui.yml`
- `newsflow-ai/frontend/src/studio/Workbench.tsx`
- `newsflow-ai/frontend/src/studio/management/Analytics.tsx`
- `newsflow-ai/frontend/src/studio/management/Automation.tsx`
- `newsflow-ai/frontend/src/studio/management/Library.tsx`
- `newsflow-ai/frontend/src/studio/management/Management.tsx`
- `newsflow-ai/frontend/src/studio/management/Publishing.tsx`
- `newsflow-ai/frontend/src/studio/management/Settings.tsx`
- `newsflow-ai/frontend/src/studio/management/management.css`
- `newsflow-ai/frontend/src/studio/management/shared.tsx`
- `newsflow-ai/src/newsflow/studio/read_models.py`
- `newsflow-ai/tools/studio_v3/integration/management_gui.browser.cjs`
- `newsflow-ai/tools/studio_v3/integration/management_gui_bridge.py`
- `newsflow-ai/tools/studio_v3/integration/management_seed.py`
- `newsflow-ai/tools/studio_v3/integration/test_management_api.py`

이 보고서·비교 캡처·증거 폴더만 추가 보존됩니다. 별도 PR 생성 및 PR35 수정 없이 새 작업 브랜치에만 push했습니다.

## 미구현·미검증 및 남은 조치

1. 사용자 최종 시각 판정: MINOR 차이(아이콘 세부, 실제 데이터 밀도, 폰트/글로우, 필수 승인 설명)를 비교 페이지에서 인수해야 합니다.
2. 실제 Windows11 앱/OS DPI·설치 EXE는 NOT VERIFIED. 이번 Windows Server CI ASGI/Chrome 증거와 구분합니다.
3. 실제 공급사 계정 권한/청구액/OAuth/SNS 전송은 미검증입니다. 새 공급사 API나 실제 전송 기능을 추가하지 않았습니다.
4. 기존 서비스의 미지원 자동화 유형·템플릿·성과 수집/청구서 동기화·저장경로 이전·트레이/업데이트 엔진은 구현 범위 밖입니다. 버튼을 가짜 성공으로 채우지 않습니다.
5. 샘플은 사용자별 참조 자산 복사이며 MP4만 있는 샘플을 편집 가능한 원본 프로젝트로 표시하지 않습니다. 일반 제작 MP4의 새 편집 프로젝트 복제 기능은 추가하지 않았습니다.
6. 기존 React 이미지/캐릭터 제작실은 URL의 특정 작업 ID를 자동 선택하지 않는 제약이 있어, 제작실에서는 목록 선택이 필요할 수 있습니다. 이 보호 소스는 변경하지 않고 선택한 원본 작업의 기존 상세 링크를 병행 제공합니다. 최종 게시 실전송/이미지·캐릭터 신규 게시 Adapter 확장은 별도입니다.
7. 라이브러리는 기존 workspace 읽기 모델의 최신100개 프로젝트 범위와 기존 샘플 카탈로그를 재사용합니다. 전체 DB의 무제한 검색/서버 페이지 탐색은 새로 추가하지 않았고 표시 수량은 조회된 목록 기준입니다.
8. 과거 Windows CI identity 조회 시간 초과는 이번 변경과 독립된 기존 위험으로 남습니다. Windows 실행 상태 실조회/OS 등록을 이번에 다시 실행하거나 해결했다고 주장하지 않습니다.
9. JS 묶음 약536KB의 빌드 성능 경고는 남습니다. 로딩 실패는 없었으며 보호 화면 구조를 바꾸는 코드 분할을 이번에 추가하지 않았습니다.

이번 작업은 여기서 종료합니다. 운영 배포·PR 병합·실계정 API·SNS 게시 또는 새로운 기능 개발은 진행하지 않습니다.
