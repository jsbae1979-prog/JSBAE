# Windows11 최종 GUI·DPI·제작 기능 통합 검증

최종 판정: **BLOCKED — 실제 Windows11 제품 인수 미완료**.

현재 PC에서 새 로컬 FFmpeg 합성은 **4 PASS / 0 FAIL / 0 SKIP**입니다. 그러나12개 제품 화면의 실제 로컬 React–Python 연결, 샘플3개 플레이어 재생, 실제 OS DPI 검증은 완료하지 못했습니다. 이 결과를 과거 CI 성공으로 대체해 PASS로 표시하지 않습니다. 제품·Guard 수정이나 새 보안 개발·전체 회귀 없이 이번 허용 범위를 종료합니다.

## 1. 실제 Windows 환경 및 브랜치

- Windows **11 Pro / 26H2 / 10.0.26300.9711 / 64비트**. 읽기 전용 CIM `Win32_OperatingSystem.Caption`으로 Windows11을 확인했습니다. HKLM의 레거시 `ProductName=Windows 10 Pro` 문자열만으로 OS를 판정하지 않았습니다.
- 실행 Python **3.14.7**. 실제 현재 PC에서 FFmpeg를 실행했습니다. GitHub Runner 결과가 아닙니다.
- 시작/제품 기준 HEAD `5a8a622748464897033a49e421725812267245d9`. 관리 완료본 `4580e8943a6e3a19d83ccad34995412f39bc21fa`를 포함한 상태를 유지했습니다. 두 완료 브랜치의 원격 SHA도 동일했습니다.
- 별도 결과 보존 브랜치: `codex/newsflow-windows11-final-validation-20261028`. 이 보고 커밋 외 제품/테스트 소스 변경0. 기존 `validation/` 미추적 폴더 유지.
- [환경 근거](evidence/WINDOWS_ENVIRONMENT.json) · [요약 JSON](evidence/VALIDATION_SUMMARY.json).

## 2. 로컬 앱 실행 경계

현재 지시로 Windows11 로컬 검증에 대한 사용자 승인은 존재합니다. 남은 문제는 이미 작성된 정식 검증 실행기가 현재 PC용으로 구현되어 있지 않다는 점입니다.

- `tools/studio_v3/integration/test_full_app_forms.py:12`는 Windows Actions 임시 환경만 허용합니다.
- `tools/native_app_policy/run_app_policy.py:15–16`도 실제 CI 여부를 확인하고, PC에서 CI를 가장하지 말도록 명시합니다.
- 기존 로컬 Guard에서 filelock의 ntdll 경계가 차단된 증거와, 후속9PASS가 **CI 한정 초기화/읽기 ASGI** 검증이라는 기록을 재사용했습니다. 운영 Guard나 제품 경로를 확장한 성공 증거가 아닙니다.
- 기존 소스 읽기 간소화/CI 성공은 유효하지만, 로컬 TCP 서버·전체 수명주기·저장/생성 명령이 허용된 정식 경로가 추가된 것으로 해석하지 않았습니다.
- CI 표시를 위조하거나 검사 삭제, 사전 import, 다른 앱/EXE·운영 앱 재사용으로 우회하지 않았습니다. 알려진 차단을 재현하기 위한 전체 앱 기동도 **0회**입니다. 새 filelock PermissionError나 자동 승인 거절이 발생했다고 보고하지 않습니다.

## 3. 12개 화면 GUI

| 화면 | 이번 Windows11 실제 앱 GUI | 기존 증거와 구분 |
|---|---|---|
| 홈 대시보드 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 콘텐츠 제작 홈 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 뉴스 쇼츠 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 캐릭터 쇼츠 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 독립 AI 이미지 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 뉴스 TOP3 이미지 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 뉴스 스튜디오 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 자동화 센터 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 라이브러리 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 게시 스튜디오 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 성과·비용 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |
| 설정·관리 | **BLOCKED** | 기존 캡처·Windows CI 재사용, 이번 로컬 앱 미실행 |

표의12개 BLOCKED는 **하나의 공통 실행 경계 때문에 미실행된 화면 목록**입니다.12개 테스트를 실행해 실패했다는 뜻이 아닙니다. 새 제품 화면 캡처를 만들지 않았으며, 기존 CI 캡처를 이번 Windows11 캡처로 이름 바꾸거나 재분류하지 않았습니다.

[기존 원본·전후 비교](../core-studios-final-match-20261028/visual-comparison-final.html) · [기존 실제 CI 캡처](../core-studios-final-match-20261028/after/) · [화면 상태 JSON](evidence/GUI_SCREEN_MATRIX.json).

## 4. 핵심 제작 동선·관리 기능

| 사용자 동선 | 이번 결과 | 재사용 근거 |
|---|---|---|
| TOP3→대본→간편설정→미리보기→제작 준비→저장/Revision | **BLOCKED** | 기존 제작실22PASS, 단 Windows Server2025 ASGI/Chrome 증거 |
| 샘플 캐릭터→스토리→장면/스토리보드→견적·제작 준비 | **BLOCKED** | 기존 참조 선택·작업 보존·결과불명 생성 차단 증거 |
| 샘플 프롬프트→이미지 초안→Fake 생성→결과/재사용 | **BLOCKED** | 기존 제작실22PASS·샘플API9/GUI21PASS |
| TOP3→공통설정→3독립 결과→문구 검토→저장 | **BLOCKED** | 기존1080×1350 Fake3개·승인/중복 요청 보호 증거 |
| 뉴스 검색→저장 분석→TOP3→제작실 이동 | **BLOCKED** | 기존 분석 건수 불변·실제 기사/대본 연결 증거 |
| 자동화 예약·상태/라이브러리/게시 검토·승인/비용/키 설정 | **BLOCKED** | 기존 관리Chrome15PASS, 운영 키·예약·계정 미사용 |

저장·Revision·견적·비용/게시 승인·결과불명 보호를 변경하지 않았습니다. 이번에 실제 앱에서 새 저장/승인/숨김/재시작 테스트를 수행했다고 주장하지 않습니다.

## 5. 샘플12개 및 실제 재생

- 기존 패키지 매니페스트에 **이미지9개 + MP4 3개**가 등록된 상태를 재사용했습니다. 샘플 원본/매니페스트/사용자 복사본 변경0. 이미지 디코딩·전체 해시/원본 ZIP 검사를 반복하지 않았습니다.
- 패키지의 MP4 3개만 별도 합성 폴더에 복사하여 읽기 전용 재생 페이지를 준비했습니다. 운영 미디어는 입력으로 사용하지 않았습니다. [입력 목록](evidence/PLAYBACK_INPUTS.json).
- 운영 Chrome에는 `127.0.0.1:8765` 페이지가 연결되어 있어 조작하지 않았습니다. 별도 파일 미리보기는 브라우저 보안 심사에서 **file: 프로토콜 불허**로 거절됐습니다. [실제 거절](evidence/BROWSER_POLICY_REJECTION.json).
- 거절 후 주소 방식 변경, 다른 브라우저/실행 도구, 원시 브라우저 명령으로 같은 결과를 얻으려는 우회를 하지 않았습니다. 요청이 거절된 것은 외부 공급사 호출이나 새 네트워크 전송 성공이 아닙니다.
- 따라서 **샘플 MP4 3개 이번 실제 재생은 BLOCKED**입니다. 기존 재생·이동·복사·숨김·재실행 증거는 과거API9/GUI21PASS로만 유지합니다. 현재 PC 앱에서의 복사·숨김/복원·재실행 상태 보존은 **NOT VERIFIED**입니다.
- 기존 메타데이터상 샘플 영상은720×1280·12초·무음 슬라이드이며 편집 원본이 없습니다. 실제 완성 AI 쇼츠 또는 최신 뉴스로 표시하지 않습니다. 사용권·상업 이용/재배포 미확정 상태도 유지합니다.

## 6. 실제 Windows OS DPI

| OS 배율 | 이번 실제 제품 GUI 판정 | 근거 |
|---|---|---|
| 100% | **NOT VERIFIED** | 저장된 WindowMetrics AppliedDPI96만 확인. 활성 모니터 배율/제품 시각 검증의 증거가 아님 |
| 125% | **NOT VERIFIED** | 설정 창 미확보, 배율 미변경 |
| 150% | **NOT VERIFIED** | 동일 |
| 200% | **NOT VERIFIED** | 동일 |

Computer Use로 Windows 설정 앱을1회 열었으나 `launched app did not expose a targetable window` 결과였습니다. 재조회에도 대상 창이 없었습니다. 기존 설정 프로세스는 이번 작업 이전부터 존재하여 종료하지 않았습니다. 현재 모니터별 배율이나 배율 변경 시 로그아웃 필요 여부를 확인할 수 없었습니다. 운영 세션 영향이 있는 전역 배율/레지스트리 값은 변경하지 않았습니다.

브라우저 viewport·CSS zoom·devicePixelRatio를 OS DPI 검증으로 사용하지 않았습니다. 기존1920×1080/1366×768 캡처는 그대로 과거 브라우저 해상도 증거입니다.

## 7. 새 로컬 FFmpeg MP4

전체 앱 실행과 독립적인, 허용된 미디어 작업만 수행했습니다. 새 Guard를 개발하거나 기존 정책을 수정하지 않고 **기존 step13j_final Guard/네이티브 실행 경계의 바이트가 동일한 검증 사본**을 사용했습니다. 기존 기술 빌드의 해시 고정 ffmpeg.exe/ffprobe.exe만 허용하며 외부 네트워크/8765/운영 경로/임의 실행을 허용하지 않았습니다. filelock·제품 앱·DB·키를 import/실행하지 않았습니다.

| 신규 검사 | 결과 |
|---|---|
| 합성3장면(장면당10초) FFmpeg 연결 | **PASS** |
| 1080×1920 / 30fps / 약30초 | **PASS** |
| 새 MP4 전체 스트림 디코딩 | **PASS** |
| 2/12/22초 프레임의3장면 순서·색상 | **PASS** |

산출물: [synthetic-3-scenes-30s.mp4](media/synthetic-3-scenes-30s.mp4). 무음 색상 카드3장면입니다. AI Provider/음성·자막 포함 완성 제작 결과나 NewsFlow 앱 작업 이력으로 표시하지 않습니다. 파일 생성/규격/디코딩/순서는 검증됐지만 **플레이어 실제 재생과 제품의 제작 엔진 통합은 NOT VERIFIED**입니다.

[새 미디어 검사 결과](evidence/LOCAL_FFMPEG_RESULT.json) · [기존 실행 경계 재사용](evidence/MEDIA_EXECUTION_PROVENANCE.json).

| 첫 장면 | 둘째 장면 | 셋째 장면 |
|---|---|---|
| ![첫 장면](media/frame-1.png) | ![둘째 장면](media/frame-2.png) | ![셋째 장면](media/frame-3.png) |

## 8. 결과 집계와 발견 사항

- **신규 실행 테스트: 미디어4 PASS / 0 FAIL / 0 SKIP**. 유료 API·SNS0, Guard 거절0. 결과 JSON에 명령별 정상 종료 코드가 있습니다.
- **BLOCKED 경계:** 로컬 전체 제품 GUI 실행 경로, 브라우저 file: 재생 정책. 제품 결함으로 확정한 새 FAIL은 없습니다. GUI 미실행 때문에 신규 제품 회귀가 없다고 확정하지도 않습니다.
- **NOT VERIFIED:** 실제 제품12화면의 현재PC 기능/재실행, OS DPI4종, 샘플 사용자 상태의 현재PC 재검증, 로컬 앱을 통한 제작/플레이어.
- 환경 한계/도구 정책을 제품 결함으로 수정하지 않았습니다. 제품 React/CSS/Python/API·Guard·fixture 변경0. skip/xfail 추가0.

## 9. 프로세스·운영 보호

- 제품 앱/서버/브라우저 새 프로세스를 실행하지 않았고 운영 Chrome 탭을 열어 읽거나 조작하지 않았습니다. 새 로컬 서버/DB/8765 접속0.
- 미디어 helper Python과 FFmpeg/ffprobe 자식 명령은 모두 정상 반환했습니다. 강제 종료0. 합성 파일은 증거로 보존했습니다. 기존 OS설정 프로세스·운영 NewsFlow 프로세스를 종료하지 않았습니다.
- 운영 DB·ledger·키·OAuth·설정·미디어·백업은 열거나 테스트 입력으로 사용하지 않았습니다. 이를 확인하려고 운영 DB/키를 새로 읽거나 해시 검사하지 않았습니다.
- 소스 Git diff0(제품/기존 도구/테스트). 홈·콘텐츠 제작 홈·핵심/관리 화면·샘플 원본 변경0. PR35 Draft/open/unmerged 및 두 완료 브랜치 보존. main·PR·운영 배포 변경0.
- 이번 변경은 이 보고 폴더의 새 합성 산출물·환경/차단/테스트 증거뿐입니다. 기존 `validation/`은 그대로 유지합니다.

## 10. 재사용 증거 및 남은 배포 차단

기존 제작실 Chrome22PASS / 관리 Chrome15PASS / 샘플API9PASS·GUI21PASS / 제작실 집중CI59PASS를 재사용합니다. [제작실 결과와 전후 비교](../core-studios-final-match-20261028/CORE_STUDIOS_FINAL_MATCH_REPORT.md) 및 [관리 결과](../management-ui-final-polish-20261028/MANAGEMENT_UI_FINAL_POLISH_REPORT.md)를 보존했습니다. 이것들을 이번 Windows11 신규 PASS로 합산하지 않았습니다. 전체 Python 회귀·Guard 감사·디자인 원본 감사·샘플 무결성 검사는 반복하지 않았습니다.

남은 조건은 다음과 같습니다. 새 기능/보안 Step을 자동 생성하거나 이번에 구현하지 않습니다.

1. 현재 사용자 승인과 별개로, CI 위장/Guard 완화 없이 합성 프로필과 소유 프로세스만 다루는 **정식 Windows11 로컬 전체 앱 실행 절차의 구현·허용 여부 확정**이 필요합니다. 현행 CI-only 실행기나 초기화/읽기 정책의 범위를 임의로 확장하지 않습니다.
2. 실제 디스플레이 설정 접근과 운영 세션에 영향을 주지 않는 DPI 확인이 필요합니다. 저장된96DPI만으로 인수할 수 없습니다.
3. 샘플 재생은 사용자의 직접 확인 또는 정식 허용된 재생 환경이 필요합니다. 이번 브라우저 정책 거절을 URL/실행 도구 변경으로 우회하지 않습니다.
4. 기존 샘플 상업·배포 라이선스, 실제 계정 권한/과금·SNS·새 PC 설치/업데이트 검증은 별도 기존 배포 차단으로 유지합니다. 이번 실제 호출·설치·게시 승인이 아닙니다.

**실제 Windows11 최종 제품 인수는 보류합니다. 운영 배포·PR 병합·실제 유료 API·SNS 실행 없이 결과 보고로 종료합니다.**
