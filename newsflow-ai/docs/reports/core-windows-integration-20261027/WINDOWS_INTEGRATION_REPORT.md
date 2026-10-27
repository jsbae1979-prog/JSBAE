# 핵심 제작실 5개 Windows 통합 검증

최종 판정: **CONDITIONAL**

허용된 Windows 임시 Runner에서 실제 Python 앱의 React 자산 제공과 데이터·폼/API 왕복 **7 PASS**, 캐릭터 상태 표시 최소 보완 후 단일 Chrome 진단 **1 PASS**입니다. 현재 Windows 11 PC에서의 전체 Python 앱+React 대화형 연결은 기존 Guard 경계 때문에 **BLOCKED**, OS DPI 100/125/150/200%는 모두 **NOT VERIFIED**입니다. 이 결과로 Windows 11 데스크톱 전체 인수 또는 배포를 승인하지 않습니다.

## 1. 브랜치·코드와 기존 증거

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 작업 시작 로컬·원격 HEAD: `ebe163e9c61e478af2a99e3e1352bf9cda6b45cf`
- 새 왕복 검사: `ebdc485490b55e7cbe05fe58cd2378c9a4670620`
- 최종 제품·검사 코드: `dcf7c0dfca79b911c2e84ed9bf3fe0f8090a90ad`
- 이전 [전면 교체 보고서](../core-studios-rebuild-20261027/CORE_STUDIOS_REBUILD_REPORT.md), Windows 59 PASS, 합성 브라우저 42 PASS, 홈·콘텐츠 제작 홈의 4장 픽셀 동일 및 기존 전체 Python 회귀 증거를 그대로 보존했습니다.
- 42개 브라우저 검사를 반복하지 않았고 전체 Python 회귀·디자인 자산 감사·기능 전체 감사를 다시 실행하지 않았습니다.
- `validation/` 기존 미추적 자료를 보존했습니다. reset/clean/stash/force push 없음.

## 2. 실제 실행 환경과 한계

| 구분 | 환경·실행 | 판정 |
|---|---|---|
| 현재 PC | Windows 11 Pro 64-bit, build 26300. 운영 앱은 127.0.0.1:8765, 동일 PID 유지 | 읽기 전용 확인 |
| 로컬 전체 Python 앱 | 기존 filelock/ntdll Guard 차단 경로를 재시도·우회하지 않음. 별도 서버를 띄우지 않음 | BLOCKED |
| 새 Windows 통합 | GitHub Actions Windows Server 2025 (`windows-2025-vs2026`), Python 3.14.7, Runner TEMP 합성 DB·설정·PNG/JPEG | PASS — 앱/API 범위 |
| HTTP 전송 형태 | 실제 create_app·security middleware·라우트·SQLite·서비스를 TestClient ASGI transport로 실행. base URL은 127.0.0.1:18765이나 TCP 리스너는 생성하지 않음 | 실제 TCP 서버/Chrome 연동과 구분 |
| React 자산 | 같은 제품의 Vite 자산을 조립해 실제 Python 정적 경로에서 5개 셸·JS·CSS 응답 확인 | PASS — 자산 제공 |
| React 실행 | 새 Windows Runner 검사에서 JavaScript를 브라우저로 실행한 것은 아님 | NOT VERIFIED — 실앱 연결 |
| 캐릭터 단일 Chrome | 기존 Node/Chrome Guard·request mock·전용 프로필·소유 Windows Job 경계 그대로 사용 | PASS — 합성 API 형태 진단 |

기존 로컬 실행 제한 근거는 `docs/design/studio-v3.0/implementation/REPORT.ko.txt`의 ntdll 경계 거절 및 `FOLLOWUP_REPORT.ko.txt`의 filelock/ntdll 차단 기록입니다. 선행 import, 네이티브 순서 변경, Guard 해제·완화, EXE 등 간접 실행으로 우회하지 않았습니다. 이번 실행이 새 자동 승인 심사에서 거절됐다고 주장하지 않으며, 이미 거절된 같은 경로를 반복하지 않았습니다.

## 3. 화면별 통합 결과

| 화면 | 새 실제 Windows 앱/API 확인 | 전체 GUI/Windows 11 실제 연결 |
|---|---|---|
| 뉴스 스튜디오 | 저장 기사·출처, 완료 TOP 3 1·2·3 순위, 기사 ID·분석 ID·연결 대본 ID 조회. 분석은 한 건 그대로 유지 | NOT VERIFIED. 기존 42 PASS의 검색·이동 동선은 이전 증거 |
| 뉴스 쇼츠 | 연결 대본 편집·저장, Revision 1→2, 재조회, 이전 Revision 저장 409 및 최신 내용 보존. 무승인 대본 생성·영상 제작 차단, 새 RenderJob 없음 | NOT VERIFIED. 새 유료 대본/영상 생성·실제 새 MP4 없음 |
| 캐릭터 쇼츠 | 합성 PNG HTTP 등록·해시 동일 재열기, 고정 모델·주제, 저장 스토리·장면 상태 재조회. 조회가 작업 기록을 변경하지 않음 | 상태 표시 연결 결함 1곳 보완 후 단일 합성 Chrome PASS. 전체 앱 연결·유료 Claude/Seedance·FFmpeg 실행은 미검증 |
| 독립 AI 이미지 | 초안 저장, 모델/비율/품질 snapshot 보존, 다음 기본값 저장과 기존 작업 분리, Fake 성공 파일 조회·치수 검증·검토 후 재사용. 같은 요청 두 번에도 Fake 생성 1회 | NOT VERIFIED — 실제 앱 연결. 실제 공급사 생성은 아님 |
| 뉴스 TOP 3 이미지 | 기존 분석·대본 재사용, 공통 옵션 고정, 부분 실패 `[success,failed,success]`와 결과 불명 `[success,unknown,pending]`, 서비스 객체 재생성 후 상태·기존 파일 보존. 결과 불명 추가 요청 422, 성공 파일 1080×1350 | 기존 42 PASS의 TOP 3 전용 UI 증거 재사용. 새 실앱 GUI 확인은 미검증 |

뉴스 기반 개별 제작 선택 UI는 이전에 제거된 상태를 유지하며 이번 제품 변경 대상이 아닙니다. TOP 3·이미지·캐릭터의 실제 공급사 생성 권한을 조회하거나 키를 사용하지 않았습니다. 캐릭터 스토리/장면 상태는 합성 저장 레코드이며 실제 Claude/Seedance 결과로 표시하지 않습니다.

### TOP 3 → 대본 → 영상 제작 준비

새 검사에서 실제 앱의 `production-context` 순위·출처·articleId·draftId를 `modules/news`, `modules/shorts` 및 `/ai/drafts/{id}`와 대조했습니다. 저장 후 다시 조회하면 같은 기사 연결과 새 Revision이 유지됩니다. 이전 Revision으로 다시 저장하면 409이고 최신 대본이 덮어써지지 않습니다. 승인 없는 `/news/curation/generate` 및 `/video/render`는 422이며 분석/렌더 기록 수가 증가하지 않습니다.

실제 유료 생성, 실제 최신 영상 렌더, 로컬 서버를 통한 Chrome↔Python 전체 동선 성공은 주장하지 않습니다. 기존 검증된 세로 MP4 및 과거 화면 검증은 재사용 근거로만 남깁니다.

## 4. 확인한 결함과 최소 보완

**직접 원인:** Python의 캐릭터 장면 DTO는 `state`를 반환하지만 React 스토리보드가 `clips[i]?.status`를 읽어 fallback `pending`을 표시했습니다. 따라서 `downloaded/failed/unknown` 장면이 모두 ‘대기’로 보였습니다.

- 제품 변경은 `frontend/src/studio/core/CharacterStudio.tsx`의 **필드 연결 한 곳**: `status` → `state`.
- 데이터·API·모델·가격·견적·승인·재시도·보안·레이아웃 변경 없음.
- 실제 Windows 앱/API가 세 상태를 `state`로 반환하고 `status`가 없음을 새 검사에서 확인했습니다.
- 동일 DTO 형태를 사용한 실제 React/Chrome 단일 진단: 보완 전 **FAIL 1**, 보완 후 **PASS 1**. 두 결과와 캡처를 보존합니다.
- 새 표시는 ‘클립 저장 / 실패 · 확인 필요 / 결과 불명 · 재요청 금지’. 결과 불명 상태의 생성 버튼은 여전히 차단됩니다.
- 이 단일 진단은 **합성 응답 기반**이며, 실제 Python에 연결한 Chrome 검증으로 확대 해석하지 않습니다.

[변경 diff](PRODUCT_CHANGE.diff) · [이전 캡처](before/character-scene-state.png) · [이후 캡처](after/character-scene-state.png)

## 5. 실행 집계 및 실패 이력

| 실행 | PASS | FAIL | ERROR | SKIP | 근거 |
|---|---:|---:|---:|---:|---|
| 새 Windows 앱/API 왕복 최종 | 7 | 0 | 0 | 0 | [40497641341](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497641341), 6.31초, 기존 TestClient deprecation 경고 1건 |
| 제품 보완으로 자동 실행된 기존 집중 CI | 59 | 0 | 0 | 0 | [40497641175](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497641175), 58 projection + 1 HTTP. 새로운 전체 회귀가 아님 |
| 캐릭터 단일 React 진단 최초 | 0 | 1 | 0 | 0 | 실제 결함 재현, 숨기지 않고 보존 |
| 캐릭터 단일 React 진단 보완 후 | 1 | 0 | 0 | 0 | 합성 DTO→React 장면 상태, page error 0, 외부 앱 요청 0 |
| 기존 합성 브라우저 42개 | 이전 증거 재사용 | — | — | — | 이번 전체 재실행 없음 |

새 Windows 최초 실행 [40497210843](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497210843)은 **4 PASS / 3 FAIL / 0 ERROR**였습니다. 원인은 새 합성 자료의 (1) 저장 대본 출처 summary 누락, (2) 기존 캐릭터 계약의 English visual action 위반, (3) 요청 4:5 크기에 대해 Fake가 정사각 이미지를 반환한 것입니다. 실제 기존 계약에 맞게 출처 자료·영문 시각 지시·출력 치수를 보완했으며 제품 검증/단언/보안 정책을 낮추지 않았습니다. 최초 실패 기록과 JUnit은 CI에 남아 있습니다.

새 skip/xfail 추가·테스트 삭제·타임아웃 상향·Guard/CSP 완화 없음. 이번 타입 검사와 빌드도 PASS이며, 기존 Vite 폰트 경로/lucide 경고는 숨기지 않았습니다.

## 6. 실제 OS DPI

| Windows OS DPI | 판정 | 이유 |
|---|---|---|
| 100% | NOT VERIFIED | 현재 PC의 승인된 전체 앱 대화형 실행 경로 없음 |
| 125% | NOT VERIFIED | 동일 |
| 150% | NOT VERIFIED | 동일 |
| 200% | NOT VERIFIED | 동일 |

OS 배율·해상도·보안 설정을 변경하지 않았습니다. 기존 1920/1366 viewport, headless Chrome 캡처, devicePixelRatio 또는 CSS zoom을 OS DPI 결과로 바꾸지 않았습니다. 실제 배율별 화면 잘림·한글 줄바꿈·9:16 비율·스크롤·비용 승인 모달의 전체 앱 검증은 남아 있습니다.

## 7. 데이터·보안 및 운영 보호

- 운영 앱은 처음과 마지막 조회 모두 127.0.0.1:8765, 동일 PID 55740. 테스트 포트 18765 리스너 0. 프로세스 종료·재시작·운영 적용 없음.
- 운영 DB/ledger/설정/키/미디어/백업 A/B를 읽거나 쓰거나 테스트 입력으로 사용하지 않았습니다. 실행 중 운영 DB 자체의 합법적 쓰기 가능성이 있으므로 새 ‘전체 해시 불변’ 검사를 했다고 주장하지 않습니다.
- Windows Runner의 기존 승인 fixture를 변경하지 않았습니다. Runner TEMP의 새로운 합성 프로필과 SQLite 사용, 실제 provider 환경변수 제거, worker/스케줄러 시작 차단, 프로세스 실행·외부 socket 차단 유지.
- 실제 API 키·OAuth 토큰 복호화/사용 0. Fake Adapter용 명시적 합성 marker만 사용했습니다. 운영 DPAPI·OAuth 저장/승인 코드는 변경하지 않았습니다.
- 새 CSRF 누락 403, 외부 Origin 403, 외부 Host 거부, 승인 없는 유료 실행 거부, unknown 자동 재요청 거부를 확인했습니다. 실제 SNS 로그인·게시·유료 생성 0.
- 캐릭터 Chrome 진단 전후 소유 Windows Job 정리 완료, 잔여 테스트 프로세스 0. 브라우저 앱 요청은 mock으로만 응답했습니다. Chrome 전체 배경 통신의 OS 수준 완전 차단은 별도 미검증입니다.
- 홈·콘텐츠 제작 홈·나머지 보호 화면 소스/CSS와 기존 Workbench, Python 서비스·API·데이터 계약 변경 없음. 변경은 캐릭터 표시 한 곳뿐입니다. 기존 보호 화면 캡처 증거를 재사용하며 최신 픽셀 검사를 다시 했다고 표시하지 않습니다.
- main·PR #35·운영 브랜치 변경, 새 PR, force push, 설치/배포, Sandbox/Hyper-V/사용자/ACL/방화벽 구축 없음.

증거: [범위·보존](scope-and-preservation.json), [보호 소스](protected-source-proof.json), [포트·OS 읽기 전용 관측](host-readonly-observation.json), [DPI](DPI_RESULTS.json), [검증 집계](verification-summary.json), 전후 JSON/프로세스 정리 파일.

## 8. 남은 차단 사항과 종료

1. 현재 Windows 11 PC의 전체 Python 앱+React 연결은 기존 filelock/ntdll Guard 경계 때문에 **BLOCKED**. 정식 허용된 로컬 실행 절차가 확정되기 전 우회하지 않습니다.
2. 네 배율의 실제 OS DPI 인수 및 전체 앱 승인 모달/주요 동선은 **NOT VERIFIED**.
3. 실제 공급사 유료 생성·계정 권한·실제 SNS 게시·새 FFmpeg 렌더·최신 EXE 재빌드는 이번 범위에서 실행하지 않았습니다. 기존 검증과 구분합니다.

허용된 Windows 앱/API 검증과 확인된 표시 결함의 최소 보완·집중 재검증은 완료했습니다. 전체 Windows 11 GUI 인수와 운영·배포 준비를 PASS로 표시하지 않습니다. 보고서와 증거를 지정 브랜치에 보존한 뒤 추가 작업 없이 사용자 판정을 기다립니다.
