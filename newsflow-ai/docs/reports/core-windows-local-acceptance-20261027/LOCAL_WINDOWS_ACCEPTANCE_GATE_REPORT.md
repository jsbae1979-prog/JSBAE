# Windows 11 로컬 통합 검증 실행 경로 확인·최종 인수 보류

**최종 판정: BLOCKED**

현재 자료와 현행 Guard 안에서 허용된 Windows 11 로컬 전체 앱 실행 경로를 확인하지 못했습니다. 사용자의 종료 조건에 따라 앱을 새로 실행하거나 같은 실패 경로를 재현하지 않고 중단합니다. 제품/Guard/의존성/테스트 fixture를 수정하지 않았고 DPI 변경이나 추가 테스트도 수행하지 않았습니다.

## 1. 기준

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 시작 시 로컬·원격 HEAD: `fddca7c5c7b27672837cfbd80114060b5fedc72f`
- 제품·테스트 코드: `dcf7c0dfca79b911c2e84ed9bf3fe0f8090a90ad` — 이번 변경 없음.
- 기존 [Windows 통합 보고서](../core-windows-integration-20261027/WINDOWS_INTEGRATION_REPORT.md), [7 PASS 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497641341), [59 PASS 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497641175), 기존 합성 브라우저 42 PASS 및 전체 Python 회귀 증거 재사용. 모두 과거 실행 결과이며 이번 신규 PASS로 합산하지 않음.

## 2. 차단 원인과 현재 정식 실행 절차

실행 없이 소스와 승인 기록을 확인했습니다.

| 확인 대상 | 근거 | 결론 |
|---|---|---|
| 기존 차단 기록 | `docs/design/studio-v3.0/implementation/REPORT.ko.txt`의 7절: 초기 ntdll DLL 경계 차단, 선행 import 방식의 자동 승인 심사 거절. `FOLLOWUP_REPORT.ko.txt` 6절도 동일 제한 유지 | 이전 거절을 재시도하거나 우회하지 않음 |
| 설치된 filelock | `_windows.py:58`의 `ctypes.WinDLL("ntdll")`, 107줄 이후 NtCreateFile 등 선언 | 네이티브 DLL/심볼 초기화가 필요한 의존성 |
| 현재 로컬 Guard | `step13_guard.py:183`의 고정 허용 라이브러리는 kernel32/crypt32/advapi32. 251~258줄에서 미등록 DLL·심볼 거부. 296줄에서 해당 WinDLL 경계를 설치 | ntdll은 현행 허용 목록에 없음. 기존 차단 기록과 일치 |
| 승인된 전체 Python 앱 검증 fixture | `tools/studio_v3/integration/test_full_app_forms.py:12`는 disposable Windows Actions 전용 조건을 명시적으로 검사 | 로컬 Windows 11 기동 절차로 사용할 수 없음 |
| 기존 로컬 Chrome 도구 | 임시 프로필·소유 Windows Job·합성 요청 응답으로 UI 검증 | 실제 전체 Python 앱 연결을 허용하는 절차가 아님 |

이는 **정적 실행 경로 확인**입니다. 이번에 filelock을 Guard 아래 import해 새 PermissionError를 발생시킨 것이 아니며 새 자동 승인 거절이 있었다고 표시하지 않습니다. 임의의 DLL 전체 허용, import 순서 변경, Guard 없는 직접 실행, Runner 환경 표시 변경, 간접 EXE 실행으로 기동하지 않았습니다.

현재 확인된 정식 허용 범위는 기존 Windows 임시 Runner의 제한된 실제 앱/API 검사와 로컬 합성 UI 검사입니다. 이 두 증거를 합쳐 현재 Windows 11의 실제 TCP 서버↔Chrome 통합 성공으로 간주하지 않습니다.

## 3. 실제 React·Python 연결과 5개 제작실

| 항목 | 이번 결과 | 재사용 가능한 기존 증거 |
|---|---|---|
| 로컬 전체 Python 앱 기동 | BLOCKED | Windows Server 2025 임시 Runner 앱/API 7 PASS |
| 실제 Chrome↔로컬 Python 연결 | NOT VERIFIED | React 자산 제공 및 합성 브라우저 증거와 별도 |
| 뉴스 스튜디오 → TOP 3 → 대본 → 영상 준비·저장·재조회 | NOT VERIFIED — 이번 실앱 동선 미실행 | 기사/분석/대본 ID, 출처, Revision·409·무승인 제작 차단의 이전 Windows 검사 |
| 뉴스 쇼츠 대표 동선 | NOT VERIFIED | 기존 저장·복원·미리보기·승인 검사 |
| 캐릭터 쇼츠 대표 동선 | NOT VERIFIED | 기존 참조 PNG·스토리·상태 DTO 및 표시 수정 단일 Chrome PASS |
| 독립 이미지 대표 동선 | NOT VERIFIED | 기존 초안·설정 snapshot·Fake 결과·재사용 검사 |
| 뉴스 TOP 3 이미지 대표 동선 | NOT VERIFIED | 기존 부분 실패·결과 불명·중복 방지·파일 보존 검사 |
| 뉴스 스튜디오 대표 동선 | NOT VERIFIED | 기존 수집 자료/분석 연결·검색·출처 검사 |

이번 단계에서 실행할 수 없었던 항목을 실패한 제품 기능으로 단정하지 않으며, 기존 기능 감사를 반복하지 않았습니다.

## 4. 실제 Windows OS DPI

| 배율 | 결과 |
|---|---|
| 100% | NOT VERIFIED |
| 125% | NOT VERIFIED |
| 150% | NOT VERIFIED |
| 200% | NOT VERIFIED |

허용된 로컬 전체 앱 실행 경로가 없어 실제 앱에 대한 DPI 인수를 진행하지 않았습니다. OS 배율, 해상도, 사용자 세션, 로그아웃 상태를 변경하지 않았습니다. viewport/CSS zoom/devicePixelRatio/합성 캡처를 실제 OS DPI 검증으로 표시하지 않습니다. 따라서 각 배율의 잘림·가로 넘침·한글 줄바꿈·9:16 미리보기·주요 버튼·승인 모달은 계속 미검증입니다.

## 5. 신규 실행 집계·보존

- 신규 테스트: **PASS 0 / FAIL 0 / SKIP 0**. 기존 동일 검사를 반복하지 않음.
- 로컬 전체 앱 실행 경로: **BLOCKED**.
- 실제 앱 연결·5개 제작실·OS DPI: **NOT VERIFIED**.
- 테스트 앱 기동 0, 운영 앱 제어 0, Guard/제품/의존성/승인 fixture 수정 0, 실제 유료 API·OAuth·SNS 0.
- 운영 DB·ledger·설정·키·토큰·미디어·백업 A/B를 읽거나 쓰거나 테스트 입력으로 사용하지 않았음. 운영 파일의 전후 전체 해시를 새로 검사한 것은 아님.
- 읽기 전용 포트 관측에서 운영 앱의 기존 PID 55740이 8765에 유지됐고 테스트 포트 18765 리스너는 0. 현재 관측 시각은 `readonly-port-observation.json` 참조.
- 홈·콘텐츠 제작 홈·제품 소스·보호 화면은 변경하지 않음. 기존 `validation/` 미추적 자료 보존, reset/clean/stash/force push 없음.
- main·PR #35·운영 브랜치 변경 없음. 보고서와 비민감 실행 경로 증거만 작업 브랜치에 보존.

## 6. 필요한 승인 조건

1. **보호 정책을 유지하는 정식 로컬 전체 앱 검증 절차의 제공 또는 명시적 승인·보안 검토**가 필요합니다. 허용할 진입점, 런타임, 네이티브 호출 범위 및 경로/핸들 소유권 통제가 문서화돼야 합니다. 이번 지시는 Guard 예외 추가·정책 완화의 승인이 아니므로 아무 변경도 하지 않았습니다.
2. 그 절차는 운영 포트/DB/키/미디어와 분리된 합성 프로필, 실제 공급사·스케줄러·자동 게시 차단, 테스트 프로세스의 식별·정리 조건을 포함해야 합니다. 승인이나 환경 표시만으로 기존 보안 심사를 우회할 수 없습니다.
3. DPI 검증은 해당 앱을 정식으로 실행할 수 있는 대화형 Windows 환경에서 해야 합니다. 로그아웃 또는 운영 환경 변경을 수반하면 **실행 전 별도 승인**이 필요합니다. 이번에 세션 변경이나 새 격리 환경을 구축하지 않았습니다.
4. 실제 유료 AI·OAuth·SNS·운영 적용·재시작·배포·PR 병합은 위 승인과 별개이며 계속 미승인입니다.

정식 실행 경로가 없는 현재 조건에서는 최종 Windows 11 인수를 승인할 수 없습니다. 사용자의 지시에 따라 추가 개발·반복 테스트 없이 차단 보고로 종료하고 다음 지시를 기다립니다.
