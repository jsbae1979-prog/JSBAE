# Windows 제한 네이티브 어댑터 보안 검증 결과

- 최종 판정: **CONDITIONAL**
- 승인 범위의 제한 구현·Windows CI 보안 검사: **PASS**
- Windows 11 호스트의 기존 Guard 연동: **NOT VERIFIED**
- 전체 Python 앱 실행: **BLOCKED / 이번 단계에서 실행 금지**
- 실제 OS DPI: **NOT VERIFIED / 변경하지 않음**

## 1. 브랜치와 실행 기준

저장소: `jsbae1979-prog/JSBAE`

작업 브랜치: `codex/newsflow-core-studios-rebuild-20261027`

시작 HEAD/기술 검토: `5ddb76b745b66f9e9e1d0f57ce84691aeef5a334`

최종 검증 코드: `4774553264b19cd4fc7b63f272a00b521f4acdb9`

보고서 저장 커밋은 이 파일의 Git 이력에서 확인한다. 보고서 커밋에는 실행 코드 변경이 없다.

[최종 Windows 보안 CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40509608323)

[기계 판독 가능한 증거 ZIP](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40509608323/artifacts/12736058467)

실행 환경은 GitHub Actions **Windows Server 2025 x64, build 26100, Python 3.14.7**이다.
Windows 11 로컬 전체 앱이나 운영 프로세스를 실행한 결과가 아니다.
현재 PC에서는 소스 검토, Python 3.14.7 문법 검사, 기존 Guard/filelock 해시 및 Git 변경 범위만 확인했다.
호스트에서 NTDLL 테스트나 과거 차단 경로를 재실행하지 않았다.

## 2. 신규 파일과 운영 연결 여부

| 파일 | 역할 |
|---|---|
| `tools/native_capability/adapter.py` | 제한된 실제 네이티브 잠금 기능, 경로/핸들/상태 검증 |
| `tools/native_capability/verification_gate.py` | 승인된 CI 검증 전용 실행 경계 |
| `tools/native_capability/test_capability.py` | 합성 보안 테스트 39개 |
| `tools/native_capability/run_verification.py` | Windows CI 전용 진입점·증거·정리 |
| `tools/native_capability/README.md` | 허용/차단 및 신뢰 경계 설명 |
| 저장소 `.github/workflows/newsflow-native-capability.yml` | 이 검증만 실행하는 CI |
| 이 보고서 폴더 | 해시, 테스트 ID, 실행 이력, 최종 결과 |

위 도구를 제품 모듈, 운영 Guard, filelock, 앱 진입점에 **연결하지 않았다**.
새 검증 경계 설치 → adapter import → 고정 DLL 바인딩 순서를 테스트했다.
이 새 경계는 CI의 검증 도구만 보호하며, 기존 호스트 `step13_guard.py`를 대신하지 않는다.
기존 Guard 아래에서 이 어댑터가 허용된다는 주장은 하지 않는다.

## 3. 호출별 정책

| 검토 호출 | 정책 및 실제 검증 범위 |
|---|---|
| NtCreateFile | **제한 구현**. 소유 디렉터리 핸들에 상대적인 검증된 단일 이름만 사용. 접근권한·공유·생성·재분석 옵션 고정. 기존 파일 덮어쓰기·삭제·절대 NT 객체 경로 없음 |
| RtlDosPathNameToNtPathName_U_WithStatus | **BLOCKED**. 핸들 상대 이름이므로 필요 없음. 호출자 NT 경로·변환 버퍼 제공 안 함 |
| RtlFreeUnicodeString | **BLOCKED**. Python이 소유한 Unicode 버퍼만 사용하므로 native 할당·free 불필요 |
| RtlNtStatusToDosError | **제한 구현**. 내부 NTSTATUS 정수의 오류 코드 변환만 사용 |
| GetFileInformationByHandle | **제한 구현**. 등록된 소유 핸들의 형식·reparse 속성·파일 ID·링크 수 확인 |
| LockFileEx | **제한 구현**. 소유 파일 핸들, offset 0의 1바이트, exclusive + fail-immediately. 0~2초 범위의 유한 대기 |
| UnlockFileEx | **제한 구현**. 동일 소유 핸들과 고정 범위, 잠금 소유 스레드만 해제 |
| OpenProcess | **BLOCKED**. 제한 잠금 원시 기능에 실제 필요성이 확인되지 않아 구현·호출 안 함 |
| GetProcessTimes | **BLOCKED**. 프로세스 조회를 제공하지 않음 |

지원 내부 호출은 `CreateFileW`, `GetFinalPathNameByHandleW`, `CloseHandle`뿐이다.
전체 DLL/함수 포인터/원시 핸들을 외부 API 결과로 제공하지 않는다.
System32의 고정 DLL 경로만 사용하고 실행 증거에 SHA-256을 기록했다.
이 값은 이번 Runner 바이너리의 식별 기록이며 다른 PC의 동일 바이트를 보장하는 기준값은 아니다.

네이티브 호출의 감사 이벤트는 등록된 함수 주소·원래 인자·활성 호출 문맥이 모두 맞을 때만 통과한다.
일반 메모리 읽기·임의 주소 호출·추가 DLL/심볼 및 재바인딩은 거부한다.
바인딩 시 주소 기록에 한해 고정 ctypes 변환을 사용하며, 경로 버퍼에는 소유 버퍼 주소만 사용한다.

## 4. 경로 보호

1. 검증 실행기가 임시 폴더에 빈 `scope-<random>` 폴더를 새로 만들고 일회성 grant를 발급한다.
2. 일반 절대 DOS 경로만 허용하고 UNC·ADS·Device·상대/drive-relative·부모 이동·모호한 이름·예약 이름은 거부한다.
3. grant의 경로가 발급 시점 값과 달라지면 거부한다.
4. 볼륨 루트부터 scope까지의 각 상위 디렉터리를 이전 소유 핸들에 상대적으로 열고 실제 최종 경로와 reparse 여부를 검사한다.
5. 이 상위 경로 핸들은 scope의 안전 검증을 위한 **고정된 메타데이터/통과 권한**이며, 외부 파일 내용 읽기·쓰기 권한이 아니다. 삭제 공유를 제공하지 않아 활성 scope와 상위 경로 교체를 막는다.
6. 파일 생성은 고정된 최종 디렉터리 핸들 아래에서만 수행한다. 문자열 검사 후 외부 위치에 먼저 생성하는 방식이 아니다.
7. 등록 시 새로 생성된 빈 direct-child `.lock` 파일만 허용한다. 같은 경로의 기존 파일·hardlink는 열거나 자르지 않고 거부한다.
8. 실제 파일 핸들의 최종 경로, 볼륨/파일 ID, 링크 수 1, 파일 크기 0을 확인하고 재열기·잠금 때 다시 검사한다.

Junction/재분석 테스트는 모두 합성 대상만 이용했다. 운영 경로를 negative test로도 열지 않았다.
중첩 잠금 경로, 기존 소유자 파일 재사용, 비ASCII 상위 경로 등 이 좁은 규칙 밖은 현재 **미지원/차단**이다.
허용 경계를 넓혀 전체 filelock 계약을 흉내 내지 않았다.

## 5. 핸들·잠금·PID 보호

- opaque capability 객체를 소유 레지스트리와 대조한다. 외부 정수, 위조 객체, 다른 scope, 닫힌 capability는 네이티브 호출 전에 거부한다.
- 내부 native 핸들도 별도 등록 목록에 있어야 info/lock/unlock/close가 가능하다.
- 등록 anchor 및 디렉터리 핸들은 scope 종료 때까지 보관한다.
- 실제 LockFileEx 두 핸들 경합·유한 timeout·해제 후 재획득을 검증했다. 잠금 없는 대체 구현은 없다.
- 잠금 해제/close 실패 시 성공 상태로 바꾸지 않는다. 이미 잠근 핸들의 정리는 소유권을 확인한 고정 해제/close만 수행한다.
- 이 API는 재진입을 명시적으로 거부한다. 설치된 filelock을 수정하지 않았으며 drop-in 호환성을 주장하지 않는다.
- 프로세스 조회·종료·쓰기·주입·잠금 소유자 강제 해제 기능은 없다. 외부 PID 검사는 더미 숫자를 API에서 거부하는 방식이며 실제 외부/운영 PID를 조회하지 않았다.

신뢰 경계: 이 모듈은 **검토된 신뢰 가능한 Python 테스트 하네스의 제한 API**다.
Python reflection, 비공개 속성 조작 또는 악성 확장을 막는 OS 보안 경계가 아니다.
테스트는 경로/핸들 정책을 입증하지만 현재 Windows 사용자 자체의 운영 파일 접근권한을 제거하지 않는다.

## 6. 신규 테스트 결과

**39 PASS / 0 FAIL / 0 ERROR / 0 SKIP**. 전체 앱 회귀 집계가 아니다.

| 검증 영역 | 근거 |
|---|---|
| 실제 잠금·경합·timeout·해제 | test_02, 03, 08, 09, 25 |
| 소유권·외부/닫힌 핸들·grant | test_04~07, 18, 35, 37, 39 |
| 외부/UNC/ADS/Device/상대/모호한 경로 | test_11~17 |
| 실제 Junction/reparse/hardlink | test_26~30 |
| 최종 핸들 경로/파일 ID 불일치 | test_31, 32; 신뢰 하네스의 메타데이터 fault injection |
| unlock/close 실패 상태 보존 | test_33, 34; 신뢰 하네스의 실패 주입 |
| PID·DLL·심볼·임의 함수 호출 차단 | test_19~22, 36, 38 |
| 네트워크/DNS·프로세스 실행 차단 | test_23, 24; OS 호출 전 감사 단계 거부 |
| gate-first 순서 | test_01 및 evidence의 gate_events |

최종 증거:
- 남은 native 핸들: **0**
- 정리 실패: **0**
- 증거 파일 작성 전 합성 자료 잔여 항목: **0**
- 테스트 중 adapter 소스 해시: 전후 동일
- 자식 프로세스 생성: **0**. 시도한 negative subprocess 요청은 감사 단계에서 거부
- 외부 요청: **0**. 외부 테스트 IP와 DNS negative probe도 실제 연결/조회 전에 거부
- 새 skip/xfail: **0**
- 모든 테스트 ID: `SECURITY_TEST_CASES.md`, 상세 증거: `SECURITY_TEST_RESULTS.json`

앞선 검증 시도도 보존했다.

| 코드 / CI | 결과 | 원인 및 처리 |
|---|---|---|
| 7951adc / 40508484217 | 0 PASS, 37 ERROR | 새 검증 경계가 허용 대상 호출 감사 이벤트까지 거부. 운영 Guard 변경 없음 |
| 9b654b5 / 40508963320 | 0 PASS, 39 ERROR | 경로 버퍼의 ctypes.cast 자체가 문맥 밖 호출로 차단. 소유 버퍼 addressof로 최소 수정 |
| 60551c4 / 40509291808 | 보안 39 PASS, CI FAIL | top-level 합성 Junction 정리 실패. 성공으로 숨기지 않음 |
| 4774553 / 40509608323 | 보안 39 PASS, CI SUCCESS | Junction 자체만 제거하고 잔여 핸들·파일 0 확인 |

추가된 2개 테스트는 원시 함수 주소 호출 거부와 내부 native 핸들 소유권 검사다.
전체 Python 회귀, UI 감사, PNG 검증, 기존 실패 경로의 호스트 재실행은 수행하지 않았다.

## 7. 기존 증거 재사용

다음은 기존 결과이며 이번 신규 결과에 합산하지 않는다.

- Windows 앱/API **7 PASS**: [40497641341](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497641341)
- Windows 집중 CI **59 PASS**: [40497641175](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40497641175)
- 합성 브라우저 **42 PASS**: 기존 rebuild 보고서의 증거 재사용
- 이전 Guard 기술 검토 및 `NATIVE_CALL_REVIEW.json` 보존

## 8. 기존 Guard·운영·Git 보호

`HOST_POLICY_BASELINE.json`과 `HOST_POLICY_AFTER.json`에서 기존 호스트 Guard와 설치된 filelock Python 소스 해시를 비교한다.

기존 Guard SHA-256:
`d59add898d2e3d846932705a94354810a8a4a4fb394da5193b717949fc43a6d9`

- 기존 Guard 파일·정책: **변경 0**
- 설치된 filelock 소스: **변경 0**
- 제품 Python/React/CSS/진입점/migration: **변경 0**
- 운영 앱 종료·재시작, 운영 포트 사용: **수행 안 함**
- 운영 DB·설정·키·토큰·미디어 및 백업 A/B: **테스트 입력으로 사용하거나 변경하지 않음**
- 운영 DB 등의 새 전수 해시 검사는 하지 않고 기존 보존 증거를 재사용했다. 실행 중인 운영 앱 자체의 데이터 변경까지 새 해시 불변으로 단정하지 않는다.
- 실제 유료 API·OAuth·SNS: **수행 안 함**
- PR #35: Draft/open/미병합, head `75626f74cc1bfe750d24132e44019bcda478247b` 유지
- main·운영 브랜치: 수정·병합·push 안 함
- 기존 `validation/` 및 로컬 변경: reset/clean/stash 없이 보존

## 9. 남은 차단과 승인 조건

1. 이 어댑터는 현재 filelock의 DLL 접근 인터페이스를 대신하지 않는다. 기존 Guard를 둔 로컬 전체 앱은 계속 **BLOCKED**다.
2. 기존 Guard의 정식 capability 등록/호출 경계와 filelock 실제 descriptor/재진입/소유자 메타데이터 계약의 별도 통합 검토가 필요하다. 이번 단계에서 해당 연결을 추가하지 않았다.
3. 프로세스 identity 조회가 실제로 필요해지면 소유 테스트 Job/PID 등록을 먼저 입증해야 한다. 현재 OpenProcess/GetProcessTimes는 모든 PID에 대해 차단 상태다.
4. Windows 11 호스트 native 동작, 전체 React/Python 앱 실행, 실제 OS DPI는 미검증이며 별도 승인 없이는 실행하지 않는다.
5. 되돌림은 이 검증 전용 신규 도구/CI만 정상 revert 커밋으로 제거하면 된다. 운영 적용이 없어 운영 DB/앱의 롤백 작업은 필요 없다. 지금 revert나 reset을 수행하지 않았다.

**현재 승인 범위의 제한 구현·보안 시험은 완료했다. 기존 로컬 전체 앱 차단이 해소됐다는 판정은 하지 않으며, 여기서 실행을 중단한다.**

## 10. 기술 근거

- [Microsoft NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile): 소유 RootDirectory 상대 이름 사용
- [Microsoft LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex): 별도 핸들 간 실제 경합과 고정 byte-range lock
- [Microsoft GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew): 열린 핸들의 최종 경로 조회
- [Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew): 삭제 공유와 rename 제약

공식 API 설명과 이번 테스트 관측을 구분했다. 구현 경계는 소스·테스트 증거로 평가했으며 문서만으로 실행 PASS를 부여하지 않았다.
