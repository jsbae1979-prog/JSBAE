# Settings UX Simplification

기준: `feat/newsflow-api-news-search` / `d081cfa33f75369881063fcac5e6e408cc793bf2` (PR #28). 설정 화면만 정리하며 실제 API·CLI 인증·추론을 실행하지 않는다. 실제 API 연결·웹 검색은 **NOT VERIFIED / BLOCKED**를 유지한다.

## 기존 문제와 화면 구성

기존 화면은 제작 기본값, 일곱 연결 단계, Provider 설명, 키·비용·음성·영상·운영 설정을 길게 나열했다. 같은 연결 설명이 반복되고, 비용 승인과 키 입력 위치를 찾기 위해 여러 접기 영역을 탐색해야 했다.

개편 화면은 저장된 AI·음성·영상 구성과 네 가지 핵심 상태를 먼저 보여준다. 본문은 **AI 연결 / 음성·영상 / 운영 관리**로 나눈다. 현재 선택한 Provider의 연결만 표시하고, 키 등록과 필수 승인·월 예산은 해당 항목에서 다룬다. 모델·단가·타임아웃·상세 사용 기록과 일곱 단계 진단은 필요할 때 펼친다. 저장 전 변경 상태와 저장 후 작업실로 돌아가는 경로를 구분한다.

## 저장 위치와 중복 정리

| 화면 항목 | 재사용한 저장 기준 | 보존 조건 |
|---|---|---|
| 기본 AI·모델 | `studio_provider`, `studio_model_{provider}` | 선택한 Provider만 갱신; 다른 모델 유지 |
| 뉴스·길이·목적지·수집 정책 | 기존 `autopilot_*` | 저장된 RSS 정책 유지; 자동 대체 없음 |
| 음성·속도·쉼 | `video_default_voice/rate/pause_ms` | 사용 불가한 기존 선택도 임의 대체하지 않음 |
| 영상 방식 | `video_ai_provider` | Higgsfield 승인·가격·키와 분리 |
| API 키 | 기존 OpenAI/Claude API DPAPI 저장소 | SQLite·HTML에 키 평문 저장 안 함 |
| API 승인·예산·검색 동의 | 기존 `api_{provider}_*` | Provider별 독립 승인·검색 동의·예약 유지 |
| OpenAI 기존 토큰 게이트 | `ai_approved_at`, `ai_monthly_token_limit`, `ai_timeout` | USD 예산과 별개의 기존 제한 유지 |

제작 구성은 기존 `/production/preferences`를 사용하며, API 승인·키는 기존 전용 라우트를 유지한다. 화면 단순화를 위해 서로 다른 승인·과금 범위를 합치거나 새 저장소를 만들지 않는다. 기존 URL·고급 관리·예약·AI Studio·Video Studio 접근을 보존한다.

## 보안과 데이터

GET와 설정 저장은 추론·유료 API·CLI 인증을 실행하지 않는다. 키 등록, 실제 인증 확인, 실제 검색 성공을 구분한다. 미승인·미검증·예산 제한·결과 불명 예약에 대한 기존 차단은 유지한다. CSRF·Origin·CSP·DPAPI와 사용자 검토·SNS 게시 차단을 변경하지 않는다.

GUI 검증은 127.0.0.1:8782의 별도 테스트 DB를 사용했다. Chrome에서는 키 입력 위치만 확인하고 실제 키를 등록하지 않았다. 키 저장·보존 자동 테스트는 합성 키만 사용했다. 기존 사용자 앱·DB·API 키·승인·영상은 변경하지 않는다. migration, Provider 구현, Autopilot·FFmpeg·TTS 엔진은 이 작업의 변경 대상이 아니다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| 변경 영역 핵심 테스트 | 로컬 Python 3.14: 85개 계약 PASS. 최초 84 PASS와 기존 문구 콜론 차이 1건 실패 후 해당 1건만 수정·재검증 PASS. 테스트 파일 Ruff PASS |
| Windows Python 3.12 / 3.14 CI | 각 85 PASS · Ruff·pip check PASS. 동일 실행 1회, 재실행 없음 |
| Chrome 전후 화면·선택한 연결만 표시 | PASS: 현재 AI·음성·영상 구성을 확인하고 OpenAI/Claude 선택 시 해당 연결 패널만 표시 |
| 키 입력 위치·비용 승인·BLOCKED 사유 | PASS: 두 API의 직접 키 입력 위치·월 예산·미검증 표시 확인. 별도 검색 동의·계정 잔여 예산 확인은 임의 체크되지 않음. 실제 키 등록은 미실행 |
| 음성 저장·변경 상태·작업실 복귀 | PASS: 미저장 표시·변경 취소 후 모델 선택 유지, Supertonic F1→F2 저장 안내 후 작업실에서 F2 확인 |
| 키보드·좁은 화면·오류 안내 | PASS: Enter로 전체 연결 상태 7행 열기, Escape로 닫은 뒤 버튼 포커스 복귀. 고급 링크 14개 유지. 음수 예산 저장 422 오류를 인라인 표시하고 오류로 포커스 이동. 실제 CSS 너비 355px에서 페이지 가로 넘침 없음; 비용 대화상자 너비·scrollWidth 모두 291px |
| 사용자 데이터·기존 키·승인 보존 | PASS: 일반 LocalAppData·Codex LocalCache 두 DB integrity=ok, 전체 테이블 행 해시·행수 동일, 기존 MP4 총 6개 해시 동일, DPAPI 파일 목록 변화 없음 |
| 실제 API 인증·뉴스 웹 검색 | NOT VERIFIED / BLOCKED; 호출하지 않음 |
| Claude Code·Codex 설치·인증·추론 검사 | 미실행; 사용자 지시로 재검사하지 않음 |

화면 캡처는 별도 테스트 자료이며 비밀키·개인 데이터·DB·MP4를 Git에 포함하지 않는다. 핵심 테스트와 Windows CI만 수행하고 전체 회귀는 반복하지 않는다. 테스트 범위는 설정 정보 구조, 선택한 Provider 표시, 키·비용 폼, 기존 설정 라우트, 승인·예산·결과 불명 예약 보존이다. 모든 데이터는 임시 DB·합성 키이며 실제 API·CLI 요청을 사용하지 않는다.

Chrome 화면 증거는 로컬 전용 `validation-output/settings-simplification/`에 보관했다.

- `before-desktop.png` / `after-desktop.png`: 개편 전후 기본 설정 화면.
- `after-saved.png`: 음성 변경 저장 안내와 작업실 복귀 경로.
- `after-budget-error.png`: 음수 예산 오류 안내와 승인 상태.
- `after-mobile.png` / `after-mobile-budget.png`: 좁은 화면 기본 배치와 비용 대화상자. 요청 viewport는 390px이며 브라우저 배율이 반영된 측정 CSS 너비는 355px였다.

- 브랜치: `feat/newsflow-settings-simplification`
- 변경 파일: 총 14개 (아래 목록)
- 검증 코드 SHA: `4169eb809653ff4f4ec9b17203ef77828dd511b7` (후속 커밋은 이 보고서 결과 기록만 변경)
- 신규 Draft PR: [#29](https://github.com/jsbae1979-prog/JSBAE/pull/29), base: `feat/newsflow-api-news-search`
- Windows Actions: [38928630262 — SUCCESS](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38928630262)
- 남은 문제: 실제 계정의 인증·검색·청구 결과는 이번 UI 작업으로 검증되지 않음.

현재 검증 서버의 실제 API·CLI 호출 시도는 0건이다. 사용자 앱(8765)은 재시작하지 않았다. 검증 중 발견한 Provider 변경 취소 후 모델 혼합 표시를 UI 코드에서 수정하고 해당 동선을 Chrome에서 재검증했다.


## 변경 파일

- `src/newsflow/gui/production_routes.py`, `autopilot_routes.py`, `api_settings_routes.py`: 읽기 전용 상태 요약과 저장 결과 안내.
- `src/newsflow/gui/templates/simple_settings.html`, `api_connection.html`, `base.html`: 세 영역 화면·키·예산·진단 대화상자.
- `src/newsflow/static/css/settings.css`, `static/js/production_settings.js`, `static/js/app.js`: 반응형 배치·미저장 표시·취소·키보드·인라인 오류.
- `tests/test_settings_simplification.py`, `test_settings_api_panel.py`, `test_ux_workflow_settings.py`: 설정·승인·보존 계약 및 변경 문구.
- `.github/workflows/settings-simplification-windows.yml`: 변경 범위 Windows 3.12/3.14 CI.
- `docs/reports/settings_ux_simplification_report.md`: 완료 기록.

기존 PR #1~#28과 main은 변경·병합하지 않았다. 최종 구현은 4169eb8이며, 보고서 기록 커밋을 포함한 최종 HEAD는 PR과 완료 응답에 명시한다. 새 화면은 격리 검증용 127.0.0.1:8782에서 확인했고, 사용 중인 8765 앱에는 다음 정상 재시작 때 적용된다. 검증 도중 추가 입력이 발견된 8781 테스트 화면과 데이터는 초기화하지 않고 보존했다.
