# 핵심 제작실 5개 전면 교체 결과

최종 판정: **CONDITIONAL** — 독립 React 제작실 5개와 저장 분석 연결은 구현·집중 검증 완료. 시각적 픽셀 일치, 실계정 생성, Windows OS DPI와 로컬 전체 Python 앱 통합 인수는 별도입니다. 운영 전환·배포 승인이 아닙니다.

## 기준 및 변경 범위

- 작업 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 시작 제품 HEAD: `20ed36fb66d515ab36d19eccfb28c1a6de6c6924`. 기존 승인 UI 브랜치 보존.
- 최초 전면 교체 코드: `68db1cb995e6c0ac3aa2892bf3c9131ac6a26c8d`
- 최종 제품·테스트 코드: `f398c61ea0d42d30f11563d225a53922e28ac8ab`
- 디자인 기준: `17b81fab2325c4f1757a9e4d8cf88bd287719e4c`, 디자인 문서 브랜치의 `CORE_5_APPROVED_MANIFEST.json`.
- 새 브랜치는 작업 시작 시 로컬·원격에서 존재하지 않아 기존 제품 HEAD에서 한 번만 생성했습니다. 기존 개발·운영·main 브랜치와 PR #35는 수정하지 않았습니다.
- `validation/` 등 기존 로컬 미추적 자료는 그대로 보존하고 업로드 대상에서 제외했습니다. reset/clean/stash/force push를 사용하지 않았습니다.

## 구현 결과와 시각 판정

| 화면 | 구현 | 판정 | 남은 차이 |
|---|---|---|---|
| 뉴스 쇼츠 | 수평 TOP 3 선택, 대본 생성·편집·저장, 간편 음성/FFmpeg·AI 방식/자막·길이, 세로 미리보기, 하단 제작·저장, 접힌 고급 편집 | MINOR | 실제 장면 수·텍스트와 데이터가 시안 예시와 다름. 세부 글꼴·간격과 승인 창 유지. |
| 캐릭터 쇼츠 | 캐릭터/스토리/영상 3단계, 참조 PNG, 주제·Claude, 고정된 작업 모델·견적·승인, 3열 설정·미리보기, 하단 스토리보드 | FUNCTIONAL_CONSTRAINT | 실제 Seedance 720p 입력과 FFmpeg 1080×1920 출력을 분리. 가상 클립·견적·캐릭터를 만들지 않음. 작은 viewport에서는 세로 재배치. |
| 독립 AI 이미지 | 프롬프트·스타일 프리셋·모델/비율/품질, 초안·참조 첨부, 중앙 결과, 우측 이력, 저장·검토 후 재사용 | MINOR | 검증된 성공 파일만 미리보기. 참조 기반 유료 편집은 미구현 표시. 스타일은 프롬프트 텍스트에 실제 반영. |
| 뉴스 기반 TOP 3 | 독립/뉴스 탭, 완료 분석 선택, 순위별 3건, 공통 생성 옵션, 독립 결과 3개, 문구·출력 검토, 하단 기존 작업 재조회 | FUNCTIONAL_CONSTRAINT | 개별 뉴스 제작 선택 UI 제거. 기존 내부 단일 제작 데이터/API는 삭제하지 않음. 미확정 공식 가격·실계정 권한은 유료 실행 차단. 출처·AI 표시·게시 승인은 선택적 장식 스위치로 바꾸지 않음. |
| 뉴스 스튜디오 | 보관 검색·분야 필터, 기사 상세·출처, 실제 연결 분석 요약/선정 근거, TOP 3, 제작실 이동, 이번 화면 확인 기록 | FUNCTIONAL_CONSTRAINT | 저장 필드가 없는 키워드·관련 추천·즐겨찾기·공유 기능을 동작하는 것으로 표시하지 않음. 영상 편집 중복 없음. |

주요 패널 배치의 MAJOR 차이는 남기지 않았습니다. 보호된 기존 사이드바/상단 셸은 그대로이며 시안의 전체 상단 메뉴로 교체하지 않았습니다. 단순 스크린샷 덮기나 기존 HTML 외형 변경이 아니라 실제 입력·선택·저장·승인 창을 가진 독립 React 컴포넌트입니다. 위 판정은 시안과 캡처를 수동 검토한 결과로, 수치적 픽셀 일치나 사용자 최종 시각 승인을 의미하지 않습니다.

[승인 원본·이전·이후 비교](visual-comparison.html), [화면별 판정](SCREEN_VERDICTS.json), [1920/1366 캡처](after/).

## 신규 개발 및 재사용

새 React 계층:

- `frontend/src/studio/core/CoreStudios.tsx`: 대상 모듈 라우팅, 독립 이미지/TOP 3 모드.
- `shared.tsx`: 읽기 전용 자료 로드, 기존 명령 연결, 안전한 미디어·빈 상태·승인 창 호스팅.
- `NewsShortsStudio.tsx`, `CharacterStudio.tsx`, `ImageStudio.tsx`, `TopThreeImageStudio.tsx`, `NewsStudio.tsx`: 제작실별 상태와 JSX.
- `core-studios.css`: 모든 선택자는 `.approved-studio.core-studio` 하위로 제한.
- `Workbench.tsx`는 대상 4개 모듈(이미지 2개 모드 포함)만 새 호스트로 분기. 보호 화면의 기존 Workbench 함수 본문은 그대로 유지.

새 API:

- `GET /api/studio/production-context` — 기존 성공 TOP 3의 실제 순위·기사·공개 출처·요약·선정 근거·연결 대본 ID/Revision 및 수집 회차를 허용 목록으로 반환합니다.
- `studio/core_context.py`는 기존 `publishing.image_selection.selection()`을 재사용합니다. 조회에서 provider/vault/다운로드/migration/DB 쓰기를 호출하지 않습니다. 누락·중복·숨김·형식 오류·잘못된 출처는 빈 상태/차단 이유로 반환합니다.
- 새 수집과 다른 이전 분석은 stale 표시하며 무조건 최신 분석이라고 표시하지 않습니다.

기존 엔진 재사용:

- TOP 3 대본: `curation_generate` 원래 폼에 analysis_id/rank/duration 연결. 추가 분석 없이 기존 승인·durable claim·결과 불명 보호 사용.
- 대본 저장: 기존 `intelligence_edit`, Revision 기반 POST. 충돌 시 텍스트·당시 Revision·세션 복원본 보존. 새 저장 버전 조회가 편집 원본을 몰래 재기준화하지 않음. 최신 저장본 재열기/이전 편집 복구는 명시적 선택.
- 기존 뉴스 이미지 자동 연결·수동 소재 선택을 기본 FFmpeg 경로로 전달. 기본 카드 선택은 명시적 전환이며 이전 수동 선택을 자동 지우지 않음.
- 영상: 기존 FFmpeg/AI 계획·장면 검토·생성 승인 모달. 자막 프리셋은 실제 지원 font_size/subtitle_y만 사용.
- 캐릭터: 기존 create/write/prepare/submit/check/render와 실패 장면 새 견적 경로. 저장된 작업 모델과 새 작업 기본값 분리. 상태별 실행 차단 및 참조 PNG 파일 없음 처리.
- 이미지: 기존 draft/defaults/generate/reuse. 성공·검증된 파일만 표시하고 기존 outputId/실패/unknown의 암묵적 재요청 차단.
- TOP 3: 기존 `TopThreeFeeds`의 상태·승인·중단/복구·문구 수정·검토·중복 방지 엔진을 render prop으로 재사용. 새 UI가 별도 유료 요청 경로를 만들지 않음. 기존 기본 렌더러와 단일 뉴스 내부 엔진은 보존.

## 검증 결과

| 구분 | 실제 결과 | 범위 |
|---|---|---|
| TypeScript | PASS | 최신 제품, 신규 컴포넌트 포함 |
| Vite | PASS | 최신 React 자산 빌드. 기존 폰트 런타임 경로/lucide use-client 경고는 보존 |
| Windows Chrome 합성 집중 | **42 PASS / 0 FAIL / 0 ERROR / 0 SKIP** | 24 캡처(5개 제작실+7개 보호 화면 × 2해상도)와 사용자 동선·안전 검사. 최종 `core04` 실행 |
| Windows Actions 최초 새 API 검증 | **58 PASS** projection + **1 PASS** HTTP integration | [68db1cb 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40493298225). Python 3.14.7, 신규 API 15건과 기존 projection 계약 43건, 새 GET 경계 1건 |
| Windows Actions 최종 제품 검증 | **59 PASS / 0 FAIL / 0 ERROR / 0 SKIP** | [f398c61 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40494128890). 58 projection + 1 HTTP, Python 3.14.7 및 frontend build 성공. 기존 TestClient deprecation 경고 1건 유지 |
| 기존 전체 Python 회귀 | 재실행 안 함 | 과거 5,454 PASS/4 SKIP 등을 최신 실행으로 합산하지 않음 |
| 과거 Windows 88 PASS·브라우저 40개·17 PASS | 기존 증거 보존 | 동일 엔진/보호 화면의 과거 검증이며 이번 신규 결과와 구분 |

신규 42개 검사에는 두 해상도 가로 넘침, 순위→분석/대본 연결, 저장 Revision, 409 편집 보존·재로드, 최신 서버 Revision이 바뀐 상태에서 기존 편집 보존, 명시적 복구, 제작 승인 창의 미동의 초기 상태, 참조 PNG/없음, 캐릭터 unknown 차단, 이미지 초안 옵션, 완료 이미지 중복 재생성 차단, TOP 3 부분 unknown 시 다른 성공 보존, 검색/실제 분석 필드, 분석 없음/GET 오류 차단이 포함됩니다.

최초 브라우저 시도 1건은 기존 모달의 aria-label을 테스트가 name 속성으로 찾은 검사 오류로 중단됐습니다. 제품 승인 경계를 바꾸지 않고 선택자를 보완했습니다. 이후 40개 통과, Revision 보호 2개 추가 후 최종 42개 통과. 실패·중간 산출물을 로컬에서 삭제하지 않았고 테스트 삭제/skip/xfail로 숨기지 않았습니다.

합성 UI는 실제 React를 Chrome에서 실행하고 요청을 로컬 fixture로 응답합니다. 새로운 전체 유료 제작 E2E·새 MP4 합성을 실행했다고 주장하지 않습니다. 기존 실제 합성 1080×1920·30초 MP4와 관련 엔진 증거를 재사용했고 새 미리보기에서 이 합성 영상을 로딩합니다.

## 보호 화면·운영 보존

- 홈·콘텐츠 제작 홈: 두 해상도 4장 모두 기존 기준 캡처와 **픽셀 차이 0**.
- 공유 보호 소스 6개 및 추가 3개(approved.css/ApprovedPanels/Thumbnail) 동일. 기존 `LegacyWorkbench` 함수 본문도 동일.
- 자동화 2장·설정 2장·성과 1366은 동일. 라이브러리/게시 4장의 차이는 기존 video 사각형 내부 Chrome 네이티브 재생 제어/로딩 표시뿐이며 바깥 픽셀 동일.
- 성과 1920 최종 캡처에는 좁은 텍스트 영역 1,329픽셀 차이가 남음. 같은 보호 코드·CSS의 바로 전 `core03` 캡처는 기준과 완전히 동일하며 보조 증거로 보존. 원인을 확정하지 않고 보호 화면 전체 픽셀 동일이라고 주장하지 않음.
- 보호 원본의 선택 상태가 달랐던 초기 비교는 동일 상태로 맞춰 대조했으며 제품 코드 변경으로 해결하지 않음.
- 운영 앱·운영 Git/DB/ledger/설정/키/미디어/백업 A/B를 테스트 입력으로 사용하거나 쓰지 않았음. 운영 앱 정지/재시작, 포트 8765 사용 없음. 실행 중 운영 DB의 전후 전체 해시를 새로 측정한 것은 아니므로 전역 바이트 불변을 새 검사 PASS로 표시하지 않음.
- 테스트 전용 Node/Chrome는 소유 Windows Job에서 정리, 종료 후 잔여 테스트 프로세스 0. 실제 공급사 API 0, OAuth/SNS 0.
- 기존 Guard/CSP/CSRF/Origin/로컬 접근/DPAPI/비용/게시 승인 코드를 완화하지 않음. 브라우저 앱 요청은 전부 mock, 외부 앱 요청 0. Chrome 자체 배경 통신의 OS 수준 완전 차단은 NOT VERIFIED.
- PR #35는 조회 시 Draft/open/unmerged, HEAD `75626f74cc1bfe750d24132e44019bcda478247b`. 변경하지 않음. 신규 PR·main 병합·운영 적용·EXE 배포 없음.

자세한 증거: [소스](protected-source-proof.json), [캡처](protected-capture-proof.json), [브라우저](browser-results.json), [프로세스 정리](browser-safe-run.json).

## 미지원·미검증과 인수 조건

- 실제 Claude/OpenAI/ElevenLabs/Higgsfield 생성·계정 권한·요금·키 사용: NOT VERIFIED, 이번 요청 범위에서 실행하지 않음.
- TOP 3 실계정 공식 견적 미확정 유료 생성: BLOCKED 유지. Fake 성공을 실제 공급사 성공으로 표시하지 않음.
- 참조 기반 OpenAI 유료 이미지 편집: NOT IMPLEMENTED 유지. 로컬 참조 첨부/보관과 구분.
- 최신 5개 화면의 실제 Windows OS DPI 100/125/150/200%: NOT VERIFIED. viewport 캡처로 대체하지 않음.
- 로컬 Guard 아래 전체 Python 앱 기동/운영 DB 통합: NOT VERIFIED. 사전 import·실행 순서 우회·Guard 완화 없이 Windows 승인 임시 Runner의 새 API HTTP 검사만 수행.
- 수동 시각 판정 MINOR/기능 제약에 대한 사용자 최종 인수 필요. 기존 셸은 보호했고 가상 데이터·계정·금액·지원 모델을 만들어 시안에 맞추지 않음.
- Step 14 운영 적용, Step 15~18 설치·배포 및 실제 유료 API/SNS는 별도 승인 필요.

## 단계 상태

| 단계 | 상태 |
|---|---|
| Step 1~12 백업/복원·Git·기존 검증 | 기존 승인 증거 보존, 이번 재실행 없음 |
| Step 13G~13J 집중 개발/회귀 | 이전 승인 결과 보존 |
| Step 13K/13K-Fix | 이전 조건부/정상 종료 PASS 증거 보존 |
| UX/UI 감사·승인 PNG 등록 | 기존 승인 및 이번 최종 5개 manifest 재사용 |
| 핵심 제작실 5개 전면 교체 | 이번 구현·집중 검증 완료, CONDITIONAL |
| Step 14 최신 운영 전환 | 이번 미실행·미승인 |
| Step 15-A/B 기술 EXE | 이전 CONDITIONAL, 새 5개 UI EXE 재빌드 없음 |
| Step 16~18 일반 사용자 설치·업데이트·배포 | 이번 미실행·별도 승인 |

개발·검증·증거 보존 후 중단합니다. 이 보고서는 추가 개발·운영 배포·PR 병합 승인 요청을 자동 실행하지 않습니다.
