# 핵심 제작실 5개 승인 디자인 정밀 보정

최종 판정: **CONDITIONAL**. 주요 작업 패널·반응형·샘플 공간 보정과 변경 범위 검증은 완료했다. 승인 PNG와 픽셀 동일한 복제라고 주장하지 않으며 실제 Windows 11 로컬 GUI·OS DPI와 최종 사용자 시각 인수는 남는다. 운영 반영·PR 병합 승인이 아니다.

## 기준

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 시작 HEAD/수정 전: `12e0d1a0c077a9bd2615060d299b7633d5cc0148`
- 최종 제품 UI 코드: `1dc4ec70a35b87f9cfde90aa8d63d8159bb354ae`
- 최종 비교 테스트 코드: `1dc4ec70a35b87f9cfde90aa8d63d8159bb354ae`. 이후 보고서 커밋은 문서·캡처만 포함한다.
- 승인 원본: GitHub 디자인 브랜치의 `17b81fab2325c4f1757a9e4d8cf88bd287719e4c`, `approved-assets/CORE_5_APPROVED_MANIFEST.json`. 원본 식별·자산 감사는 반복하지 않았다. 최신 뉴스 쇼츠와 TOP 3 최종본을 읽어 사용했으며 과거 후보·임의 생성 이미지를 사용하지 않았다.
- [시각 비교 자료](visual-comparison.html): 승인 원본 링크, 동일 해상도 비교 캔버스, 수정 전후 캡처, 오버레이·차이 이미지, 샘플 및 보호 화면. 합성 자료이며 사용자 체험용 Demo가 아니다.

## 화면별 결과

| 화면 | 판정 | 수정·남은 차이 |
|---|---|---|
| 뉴스 쇼츠 | MINOR | 가로 TOP 3 카드, 대본·간편 설정/9:16 미리보기, 하단 제작·저장 영역. 1920px 제작 바 전체가 첫 viewport 안에 위치한다. 실제 대본 3장면·저장 버전/검토 표시를 유지하며 가상 음성·60초 완료 영상을 표시하지 않는다. |
| 캐릭터 쇼츠 | MINOR | 3단계 안내, 참조/스토리/미리보기·견적의 3열과 하단 스토리보드. 1366px에서 영상 패널이 다음 행으로 내려가지 않는다. 실제 Seedance 2.0 계약·승인 버튼·3장면 상태를 유지한다. 시안의 1.0 Pro·120크레딧·5개 완성 클립을 복제하지 않는다. |
| 독립 AI 이미지 | MINOR | 왼쪽 프롬프트·스타일/옵션, 중앙 캔버스, 오른쪽 실제 이력, 하단 최근 이미지. 1366px에서도 이력 열을 유지한다. 스타일 그림 대신 기존 아이콘, 별도 승인·저장 버튼은 유지한다. |
| 뉴스 TOP 3 이미지 | FUNCTIONAL_CONSTRAINT | 뉴스 목록/공통 설정과 3개 독립 결과/문구·출처의 3열을 유지한다. 설정 고정 저장과 유료 비용 승인은 별도여서 승인 PNG의 즉시 생성·일괄 저장 버튼 및 가상 표시 토글과 다르다. 결과 상태/안내 때문에 세로 길이가 더 길며 실제 데이터가 없는 사진을 채우지 않는다. |
| 뉴스 스튜디오 | FUNCTIONAL_CONSTRAINT | 검색·기사 목록/선택 기사·AI 분석/제작실 연결·TOP 3·출처의 3열을 두 viewport에서 유지한다. 실제 API의 요약·선정 근거만 표시하며 미지원 분석 탭·키워드·추천·즐겨찾기를 시안처럼 만들지 않는다. |

**공통 차이**: 기존 보호 대상인 좌측 메뉴·상단 작업 검색을 유지한다. 승인 PNG의 상단 가로 메뉴로 교체하지 않았다(FUNCTIONAL_CONSTRAINT). 폰트·아이콘과 일부 그림자/문구 길이는 MINOR이며 래스터 원본의 폰트 픽셀과 일치를 주장하지 않는다. 실제 기사 사진·완성 영상·5장면·계정·금액 예시를 합성 성공 데이터로 추가하지 않았다. 관찰한 두 viewport의 주요 작업 패널에는 새 MAJOR 레이아웃 차이가 확인되지 않았지만, 위 FUNCTIONAL_CONSTRAINT 차이를 MATCH로 승격하지 않는다.

## 실제 수정 범위

- `precision.css`를 기존 제작실 전용 CSS 다음에 연결했다. 모든 규칙은 `.approved-studio.core-studio` 아래이며 보호 화면에 적용되는 전역 선택자는 없다.
- 패널 비율·테두리·배경·제목 크기·간격·버튼·스크롤·세로 미리보기 비율을 보정했다.
- 1366px에서 캐릭터 영상, 이미지 이력, TOP 3 문구, 뉴스 우측 패널이 통째로 다음 행으로 내려가던 기존 규칙을 제작실 범위에서만 보정했다. 950px 이하에서는 기존 세로 반응형을 유지한다.
- 4개 제작실의 샘플 갤러리를 핵심 작업/최근 이력 뒤로 이동했다. 작은 가로 카드·접힘 상태를 유지하며 라이브러리 갤러리에는 적용하지 않는다.
- 공통 `approved.css`의 `aria-pressed` 배경 `!important`가 선택 카드의 전체 배경을 파랗게 만들고 있었다. 공통 CSS를 변경하지 않고 대상 제작실 선택 카드에 한정해 어두운 배경/보라 테두리 우선순위를 명시했다.
- 뉴스 목록의 제목/분야/출처 줄 구분과 이미지 없음 상태의 공간을 정리했다.
- 4개 JSX 변경은 SampleGallery 위치 이동뿐이다. 컴포넌트 속성, 이벤트 처리, 상태·API/승인·Revision 로직은 공백 정규화 비교에서 동일하다. 근거: [PROTECTION_EVIDENCE.json](PROTECTION_EVIDENCE.json).
- 신규 API, Python 제작 엔진, 모델·비용 계약, DB schema/migration, 저장 구조, Guard·CSP·Origin·CSRF 변경은 **0**.

변경 파일:
- `.github/workflows/newsflow-ui-precision.yml`
- `newsflow-ai/frontend/src/studio/core/CharacterStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/CoreStudios.tsx`
- `newsflow-ai/frontend/src/studio/core/ImageStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/NewsShortsStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/TopThreeImageStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/precision.css`
- `newsflow-ai/tools/studio_v3/integration/precision_gui.browser.cjs`

## Windows 집중 검증

- [최종 수정 후 Windows Chrome CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40605184617): **20 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
- [수정 전 동일 데이터 비교 기준](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40605050446): **20 PASS**, 원본 코드 12e0d1a. 새 기능 PASS에 합산하지 않는다.
- [최종 제작실 집중 CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40605184616): **59 PASS** (정적·계약/모델 58 + 실제 합성 앱 API 1).
- TypeScript 검사와 Vite 빌드 PASS. 기존 패키지의 use-client/폰트 경로 해석 경고는 남지만 빌드는 성공했고 Windows 실제 로컬 자산 응답을 사용했다.
- Python **3.14.7**, GitHub Windows Server 2025 Runner, 실제 Chrome `156.0.8078.48`, Node 24.22.1, Playwright 1.64.1.
- React 요청 → 기존 합성 file IPC → 실제 Python `create_app` / FastAPI TestClient·SQLite. 앱의 TCP 서버 실행이나 Windows 11 사용자 GUI 실행으로 확대하지 않는다.
- 수정 전후 5개 화면을 각각 **1920×1080, 1366×768**로 캡처했다. 가로 넘침 0, 주요 작업 패널 나란히 배치·포트레이트 9:16 확인.
- 1920px 뉴스 쇼츠 제작 바의 아래 끝: **1070.6px**. 1366px에서는 정상 세로 스크롤로 제작·저장/승인 버튼에 접근한다.
- 대표 기능: 보관 뉴스→TOP 3/기사·대본 연결, 실제 대본 저장·재열기·Revision 충돌 보호, 별도 생성 승인, 참조 PNG 업로드·스토리보드·결과 불명 차단, 독립 이미지 초안/품질 저장·Fake 생성/검토, TOP 3 독립 결과 3개·1080×1350 파일·재요청/게시 차단, 승인 창 접근성.
- 검증용 이미지/주제/스토리만 사용했다. 실제 유료 API·OAuth·SNS 호출 0, 외부 앱 요청 0, JavaScript page error 0.
- 샘플 테스트는 갤러리 표시/접힘·미리보기와 작업 공간 비침범을 새로 확인했다. 기존 12개 파일 무결성·복사·숨김·오프라인·영상 재생/탐색 API 9 PASS/GUI 21 PASS는 b7870b9의 기존 증거를 재사용한다. 최신 재실행 결과로 표시하지 않는다.
- 전체 Python 회귀·Guard 보안 감사·디자인 자산 감사는 실행하지 않았다. 기존 Windows identity timeout 1건도 관련 없는 잔여 위험으로 유지하며 숨기거나 skip/xfail을 추가하지 않았다.

### 중간 실행과 최종 결과 구분

- 7f857be 첫 비교: 수정 전/후 각각 20 PASS, 집중 CI 59 PASS.
- 10be238 선택 강조/캡처 보완: 수정 후 20 PASS, 집중 CI 59 PASS. 수정 전 비교에서는 샘플 응답 도착 전 개수를 검사한 대기 오류 1건(19 PASS/1 FAIL)이 있었다.
- b48681a에서 샘플 첫 카드의 실제 표시를 기다린 후 개수를 검증하도록 테스트만 수정했다. timeout 상향·단언 삭제·skip/xfail로 해결하지 않았다.
- 최종 1dc4ec7은 공통 우선순위에 대한 화면 전용 선택 색상 보정이다. 수정 전 캡처는 확보된 기준을 재사용하고 변경 UI만 다시 검증했다. 최종 수정 후 실패 0. 전체 원시 CI/화면/정리 자료를 보존했다.

## 샘플 콘텐츠 유지

이미지 9개/MP4 3개, 미리보기·재생·복사·참조 활용·사용자별 숨김·복원은 그대로다. 원본 매니페스트·바이너리·사용자 저장 경로·API와 샘플 라이브러리는 변경하지 않았다. 실제 TOP 3 분석/실제 생성 이력에 샘플을 삽입하지 않는다.

샘플 카드의 제목·예제 프롬프트·미리보기·세 동작을 작은 보조 카드에 유지했다. 실제 갤러리 높이 및 항목 수는 after-gui-results.json의 sampleGeometry에 기록했다. 사용자 작업이 있는 화면의 기존 접힘 기본값과 사용 후 접힘 동작은 동일하다. 3개 영상이 무음 12초 예제이며 편집 원본 프로젝트가 없다는 기존 표시도 유지한다. 재배포 권리 확인과 EXE/설치 프로그램 포함 검증은 이전 잔여 조건으로 유지한다.

## 보호 화면 및 운영 보호

- 홈·콘텐츠 제작 홈 JSX/공통 CSS·이미지·메뉴·사용자 동선 수정 0. 자동화·게시·라이브러리·성과·설정 소스 수정 0.
- 두 보호 화면은 양 viewport에서 DOM 위치·크기·색상·글꼴·간격 등 계산된 표시값이 동일했다. 원시 캡처는 별도 실행의 합성 작업 저장 시각 텍스트 때문에 소량의 픽셀이 다르며, 픽셀 바이트 동일이라고 보고하지 않는다.

| 보호 화면 | 너비 | 계산된 배치/스타일 | 비동일 픽셀 수 |
|---|---:|---|---:|
| dashboard | 1920 | 동일 | 276 |
| create | 1920 | 동일 | 162 |
| dashboard | 1366 | 동일 | 117 |
| create | 1366 | 동일 | 0 |

- 운영 앱·프로세스·8765에 접속하거나 종료/재시작하지 않았다. 운영 DB·ledger·설정·키·토큰·미디어·백업 A/B를 읽거나 쓰는 테스트를 하지 않았다.
- 테스트 Python/Chrome만 종료되었고 잔여 Chrome 0, 미완료 요청 0, 정상 Python 종료, 강제 종료 없음. before/after-process-cleanup.json 보존.
- PR #35는 `75626f74cc1bfe750d24132e44019bcda478247b`, Draft/open/미병합 상태 그대로다. PR 수정·새 PR·main 병합·운영 배포·실계정 호출 없음.
- 기존 미추적 `validation/` 보존. reset/clean/stash/force push 없음.

## 남은 차이와 미검증

| 항목 | 상태 / 이유 |
|---|---|
| 승인 PNG와 완전한 픽셀 동일성 | NOT VERIFIED / 원본 예시 데이터, 보호 앱 메뉴, 래스터 폰트, 필수 승인 경로 차이 |
| Windows 11 로컬 전체 앱 GUI | NOT VERIFIED / 허용된 Windows CI 합성 앱·Chrome 절차만 사용 |
| Windows OS DPI 100/125/150/200% | NOT VERIFIED / viewport를 실제 DPI로 표시하지 않음 |
| 실제 공급사·Seedance·유료 생성·SNS | NOT VERIFIED / 이번 범위에서 실행 금지 |
| 새로운 EXE·설치·업데이트·제거 | NOT VERIFIED / 이번 작업에 포함하지 않음 |

디자인 정밀 보정은 완료했다. 핵심 화면 배치 개선과 기능 보존 근거를 제출하며, FUNCTIONAL_CONSTRAINT 및 사용자 최종 시각 인수를 남겨 **CONDITIONAL**로 보고한다. 운영 반영·PR 병합·신규 기능 개발 없이 중단한다.
