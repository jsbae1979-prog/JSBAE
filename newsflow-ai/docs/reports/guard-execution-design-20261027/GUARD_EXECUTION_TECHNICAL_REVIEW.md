# Windows Guard 차단 원인·정식 실행 경로 기술 검토

**최종 판정: CONDITIONAL — 분석·실행 설계 작성 완료. 현재 로컬 전체 앱은 BLOCKED, 실제 DPI는 NOT VERIFIED.**

이번 단계는 읽기 전용 분석과 설계입니다. Guard/제품/패키지/import 순서를 변경하거나 앱·테스트·DPI 변경을 실행하지 않았습니다. 아래 권장안은 실행 승인이 아닙니다.

## 1. 기준·증거 수준

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 시작 로컬·원격 HEAD: `2cb13fa4fa25dc931ed404e427e9ce175da1987a`
- 기존 제품 코드: `dcf7c0dfca79b911c2e84ed9bf3fe0f8090a90ad` — 변경 없음.
- 기존 [Windows 통합 보고서](../core-windows-integration-20261027/WINDOWS_INTEGRATION_REPORT.md), [로컬 인수 차단 보고서](../core-windows-local-acceptance-20261027/LOCAL_WINDOWS_ACCEPTANCE_GATE_REPORT.md), Windows 앱/API 7 PASS·집중 CI 59 PASS·합성 브라우저 42 PASS를 재사용했습니다. 새 실행 결과로 합산하지 않습니다.
- 설치 버전은 해당 Python 3.14.7 환경의 distribution metadata를 읽어 **filelock 3.32.7**로 확인했습니다. filelock 자체를 import하지 않았습니다.
- 과거 차단 요약은 `docs/design/studio-v3.0/implementation/REPORT.ko.txt` 7절 및 `FOLLOWUP_REPORT.ko.txt` 6절입니다. 최초 원시 Python traceback과 당시 설치 버전 메타데이터는 이번 검토에서 재확보하지 못했습니다. 따라서 현재 버전과 과거 실행 버전이 같다고 확정하지 않습니다.
- 두 기존 JSONL 이벤트 파일에서도 해당 최초 ntdll 거절 기록은 발견되지 않았습니다. 이 사실은 과거 거절이 없었다는 뜻이 아닙니다. 현재 설치 코드와 정책의 직접 충돌은 아래와 같이 정적으로 확인했습니다.

## 2. 실제 import·초기화 경로와 차단 규칙

```text
src/newsflow/main.py:17  from filelock import FileLock, Timeout
  -> filelock/__init__.py:16  from ._descriptor import ...
  -> _descriptor.py:10-11  Windows 분기에서 ._windows import
  -> _windows.py:58  ctypes.WinDLL("ntdll")
  -> 설치된 Guard의 _guarded_windll
  -> step13_guard.py:256-258 미등록 DLL 거부
```

`main.py`의 이 import는 `create_app()` 호출·서버 listen·DB 작업보다 앞선 모듈 초기화 단계입니다. 같은 패키지는 `video/service.py:18`, `character/service.py:15`, `creation/top_three_feeds.py:14`, `gui/curation_routes.py:9`에서도 재사용합니다.

현재 `_SYSTEM_DLLS`는 `step13_guard.py:183`에서 **kernel32/crypt32/advapi32**만 고정하고, 184~187줄의 서명 목록만 제공합니다. `_GuardedDLL.__getattr__` 253~255줄은 미등록 심볼을 `unapproved-native-symbol`로 거부하고, `_guarded_windll` 256~258줄은 미등록 DLL을 `unapproved-native-DLL`로 거부합니다. raw ctypes 로딩/심볼 audit 경로도 170줄에서 `unapproved-native-execution`으로 거부합니다.

따라서 Guard를 먼저 설치한 정상 import 경로의 `WinDLL("ntdll")`는 현재 정책과 양립하지 않습니다. 이는 현재 코드에 대한 정적 판정이며, 이번 실행에서 새 PermissionError를 재현한 결과라고 표현하지 않습니다.

### 로딩·심볼 바인딩과 실제 OS 호출의 구분

| 단계 | filelock의 동작 | 의미 |
|---|---|---|
| import | `_windows.py:58` ntdll 로드, 107~153줄의 함수 서명 바인딩 | 아직 잠금 획득 전에도 DLL·심볼 접근이 필요 |
| 잠금 획득 | `_acquire` → `_open_non_reparse_fd` → `_nt_open` → 경로 변환·NtCreateFile·handle 정보 확인·LockFileEx | 합성 lock 파일을 실제로 열고 한 바이트 잠금 |
| 잠금 해제 | UnlockFileEx 및 fd/handle 수명 종료 | 자식에게 handle이 누출되거나 외부 handle을 닫아서는 안 됨 |
| 잠금 소유자 판별 | `_identity.py`의 OpenProcess/GetProcessTimes | 선언은 import 중, 실제 조회는 소유자 판별 함수 실행 때 발생 |

필요한 ntdll 심볼은 `NtCreateFile`, `RtlDosPathNameToNtPathName_U_WithStatus`, `RtlFreeUnicodeString`, `RtlNtStatusToDosError`입니다. kernel32의 `GetFileInformationByHandle`, `LockFileEx`, `UnlockFileEx`, 별도 `_identity` 경로의 `OpenProcess`, `GetProcessTimes`도 현재 허용 목록에 없습니다. `CloseHandle`은 이미 허용되지만 Guard 소유 handle만 닫도록 제한돼 있습니다.

**ntdll 하나만 추가하면 전체 앱이 실행된다고 결론 내릴 수 없습니다.** 이 목록은 설치 코드에서 확인한 후보 집합이며, 다른 의존성의 후속 호출까지 포함한 완성된 실행 허용 목록은 아닙니다.

## 3. 현재 Guard의 보호 범위

| 경계 | 현재 규칙·위치 | 유지해야 할 성질 |
|---|---|---|
| 파일 | `path/check_file:21-38` — UNC·ADS·해석 불가 경로 거부, resolve 후 읽기 허용 목록, 쓰기는 합성 ROOT 내부이며 PROJECT 쓰기 금지 | 새 네이티브 경로로 Python 파일 통제를 우회하지 않음 |
| DB | `database_path:40-55`, SQLite authorizer 299~312 — 합성 DB, URI 키·mode·cache 제한, ATTACH 검사, native extension 금지 | 운영 DB 및 다른 DB로 우회 접근 불가 |
| 네이티브 파일 | 198~231 — canonical handle 경로, 소유 handle, 이동·reparse 검증, 제한된 삭제/닫기 | NT 경로·핸들에도 동일하거나 더 강한 통제 필요 |
| 프로세스 | 89~109/168~175 — 고정 바이너리·해시·인자·cwd·환경 검사, 등록된 Python/Node/PowerShell 어댑터, Popen/네이티브 프로세스 생성 연계 | shell·임의 Python·임의 EXE·환경 키 유입 금지 |
| 네트워크 | 149~161 — 외부 IP/DNS와 운영 포트 8765 거부, loopback만 허용 | 현재 규칙이 모든 loopback 서비스나 Chrome 배경 통신을 격리한다고 주장하지 않음 |
| 비밀값 | 232~249 — 합성에서 생성한 DPAPI ciphertext 및 제한된 토큰 조회 | 운영 암호문 복호화·임의 토큰·계정 접근 금지 |

filelock은 새 방식에서 Python `open` audit를 직접 발생시키고, 최종 reparse point를 handle 기준으로 확인합니다. 이 기존 안전장치를 제거하거나 SoftFileLock/잠금 없는 방식으로 바꾸는 것은 해결안이 아닙니다. 중간 디렉터리 junction 문제는 라이브러리 자체 설명에도 별도 전제가 있으므로 Guard의 경로·handle 검증으로 계속 다뤄야 합니다.

## 4. 기존 실행 경로의 존재와 현재 사용 자격

| 경로 | 존재 | 현재 목표에 사용 가능한가 |
|---|---|---|
| Windows Actions 승인 fixture | 존재. `test_full_app_forms.py:12`는 disposable Windows Actions 전용 조건 | 앱/API 검사에는 허용. 현재 Windows 11 대화형 앱·실제 DPI를 대신하지 못함 |
| 로컬 합성 Chrome/정적 UI | 존재. 검증된 Node/Chrome 경계·임시 프로필·소유 Job | 합성 UI에는 허용. 실제 Python 전체 앱 연결 경로 아님 |
| 기존 해시 고정 native child bridge | 존재. 고정 lock/oauth_bind/preview_boundary/entrypoint 및 제한된 module 모드, 바이너리/티켓/소스 해시·소유 Job 검사 | **현재 사용 자격 미확정**. 그대로 실행하지 않음 |

기존 `native_child_bootstrap.py:25`는 **click._winconsole, filelock, colorama.win32를 Guard 설치 전에 import**하고, Guard 설치는 35~36줄입니다. 지정 Guard 프로젝트도 현재 요청한 checkout과 일치하지 않습니다. Guard/bootstrap/boundary 해시는 해당 과거 설정과 일치하지만, 해시 일치가 현재 프로젝트·최신 사용자 제한의 실행 승인을 증명하지는 않습니다.

따라서 이전 보고서의 “사용 가능한 정식 로컬 경로 없음”은 **실행 도구가 전혀 존재하지 않는다는 의미가 아니라, 현재 프로젝트·사전 import 금지 조건·보호 정책과 양립한다고 입증된 경로가 없다는 의미**로 구체화합니다. 이 bridge의 과거 승인 범위를 현재 전체 앱 기동 권한으로 확대하지 않습니다. 환경 표시 변경, Guard 없는 직접 기동, EXE 실행으로 대체하지 않습니다.

## 5. 방안 A/B/C 비교

| 방안 | 구현 가능성 | 보안·운영 영향 | 필요한 승인 | 실제 DPI | 롤백 |
|---|---|---|---|---|---|
| **A. 현행 Guard·패키지·import 경로 그대로** | 현재 전체 앱에는 불가. 허용된 ASGI/합성 UI 범위만 가능 | 정책·운영 영향 없음 | 기존 범위 재사용은 가능하나 전체 앱 권한이 생기는 것은 아님 | 현재 불가 | 변경 없음 |
| **B. 검증용 최소 네이티브 capability 어댑터를 별도 승인** | 조건부 가능. DLL 이름 추가가 아니라 경로·인자·handle·PID 수명 검증이 필요. 실제 호환성·안전성은 아직 미검증 | 잘못 만들면 NtCreateFile이 파일 경계를 우회하거나 OpenProcess가 외부 PID를 조회할 수 있음. 정확한 wrapper·negative 검증 필요. 운영 파일·Guard 본체 보호 유지 | 테스트 전용 호환 계층 구현·보안 검토·검증 범위의 명시적 승인. 이후 별도 전체 앱 실행 승인 | 앱 실행 경로가 검증된 후 가능. 운영 세션에 영향이 있으면 별도 승인 | 이전 Guard/bridge/config의 해시 기준으로 복원·예외 제거, 소유 테스트 프로세스만 종료. 잠금 보유 중 교체 금지 |
| **C. 운영과 분리된 승인 Windows 테스트 환경/절차** | 기존 CI는 즉시 재사용 가능하지만 Windows 11 대화형 DPI가 아님. 별도 대화형 Windows 11 환경은 확보·허용 절차가 필요 | 폴더 분리만으로 접근 차단 아님. 같은 Guard·filelock 조합이면 동일 문제. 보호 정책을 없애는 대안으로 쓰지 않음 | 해당 환경·프로필·외부 통신 차단·프로세스 수명·정식 진입점 승인. 동일 Guard를 쓰면 B의 적합성 검토도 필요 | 독립 대화형 세션/모니터의 실제 OS 배율을 확인할 수 있을 때만 가능 | 소유 세션·프로세스·합성 자료 정리, 변경한 테스트 설정만 복원. 운영 앱·데이터에는 rollback 실행하지 않음 |

C를 이유로 Sandbox/Hyper-V·계정·ACL·방화벽 구성을 지금 새로 구축하지 않습니다. 어떤 가상화 도구도 필수 전제로 정하지 않습니다. 승인된 환경이 이미 있으면 우선 재사용합니다.

## 6. 권장안 — B의 명세·보안 검토 우선, DPI 영향이 있으면 C 결합

현재 Guard를 그대로 둔 채 전체 앱을 실행하는 A는 확인된 import 충돌을 해결하지 못합니다. B의 좁은 검증용 capability 설계를 먼저 검토하는 것이 기존 경로·동일한 앱/패키지 계약을 유지하는 최소 후보입니다. C는 운영 세션 보호와 대화형 DPI 조건을 개선할 수 있지만 단독으로 네이티브 정책 충돌을 해소하지 않습니다.

다음 조건을 만족하는 **설계 후보**이며 구현·실행 가능성을 이미 검증한 것은 아닙니다.

동일 Windows 사용자 프로세스 안의 Python audit/래퍼는 OS 권한을 제거하는 장치와 같지 않습니다. 네이티브 함수 참조 누출이나 검증 계층을 거치지 않는 호출 가능성도 검토해야 합니다. private 속성 이름이나 서명 목록만으로 완전 격리를 입증할 수 없으며, 동등한 경계를 입증하지 못하면 B를 채택하지 않고 승인된 C 환경의 추가 통제를 검토해야 합니다.

1. Guard는 앱·의존성 import 전에 설치합니다. filelock을 미리 import하는 기존 bridge를 해결책으로 사용하지 않습니다. 앱 import 순서 우회·raw DLL 반환·ntdll 전체 허용·전역 정책 완화 없음.
2. DLL은 검토된 System32 경로와 고정된 심볼/서명만 바인딩합니다. 앱이 바꾸는 argtypes나 임의 포인터/심볼을 권한으로 신뢰하지 않습니다.
3. `NtCreateFile`은 등록된 합성 lock 경로에만 사용합니다. DOS↔NT 경로, RootDirectory/OBJECT_ATTRIBUTES/UNICODE_STRING, 접근·share·create flags를 검증하고 실제 열린 handle의 canonical 경로를 다시 확인합니다. UNC/device/ADS/외부 root·부모 junction·최종 reparse·임의 객체 접근은 거부합니다.
4. `GetFileInformationByHandle`, `LockFileEx`, `UnlockFileEx`, `CloseHandle`은 검증된 파일 handle만 처리합니다. 정확한 한 바이트 범위·offset·lock 수명·CRT fd로의 소유권 이전·닫힘·재사용을 추적합니다. 이미 열려 있는 외부 handle은 허용하지 않습니다.
5. 경로 변환으로 만든 Unicode buffer만 해제하고, 임의 메모리 해제나 권한 확장 함수는 허용하지 않습니다. NtCreateFile 이외의 일반 NT 기능을 묶어 허용하지 않습니다.
6. OpenProcess/GetProcessTimes는 실제 필요성이 확인된 경우에만 **소유 테스트 Job에 등록된 PID**와 고정 query/synchronize 권한으로 제한합니다. 외부·운영 PID, 쓰기·종료·주입은 금지합니다. 조회 불명 소유자는 임의로 죽은 것으로 처리해 잠금을 깨지 않습니다.
7. 기존 파일/DB/DPAPI·프로세스·비용·Origin/CSRF·결과 불명 경계를 유지합니다. 현재 프로젝트에 대한 명시적 허용 목록·해시·티켓을 검토해야 하며, 오래된 private config를 덮어써 재사용하지 않습니다.
8. 네트워크는 테스트 127.0.0.1:18765와 정확한 내부 event-loop socketpair 범위만 검토합니다. 실제 provider는 Fake로 주입하고 스케줄러·자동 게시·유료 worker를 시작하지 않습니다. Node/Chrome 자식의 외부 통신은 별도 통제·검증 대상이며 Playwright mock만으로 OS 전체 egress 차단을 주장하지 않습니다.
9. 소유 Windows Job·정상 종료 신호·프로세스/포트 정리를 명시합니다. 강제 cleanup은 정상 종료 PASS와 구분합니다. 운영 앱은 제어하지 않습니다.

전체 앱 초기화에서 다른 미등록 호출이 발견되면 해당 호출만 중단·기록하며 일반적인 native 예외를 자동 추가하지 않습니다. 현재 후보 목록은 전체 앱의 완결된 허용 목록이 아닙니다.

## 7. 승인 후에만 수행할 검증 설계

이번에 실행하지 않았습니다.

- 정상 lock 획득·경합·timeout·해제·재시작, 기존 once/예약/승인 기록 보존.
- 운영 파일이 아닌 별도 dummy 자료로 경계 밖 경로·UNC·ADS·device·상대 경로·junction·reparse 접근을 거부하는지 확인.
- 외부/닫힌/재사용 handle, 과도한 접근 flags, 등록되지 않은 PID, 잘못된 buffer·lock 범위 거부.
- 기존 SQLite URI/ATTACH·native extension·비합성 DPAPI ciphertext 차단 보존.
- 외부 네트워크·DNS·운영 포트 거부가 실제 접근 전에 이루어지는지 검증. 운영 파일이나 서비스에 실제 접속해 negative 테스트하지 않음.
- 위 안전성 검토가 통과하고 전체 앱 실행 승인이 있을 때만 합성 프로필로 React↔Python 5개 제작실 대표 동선 실행. 유료 생성·SNS는 계속 금지.
- 실제 OS DPI는 독립적인 대화형 Windows 환경에서 측정. viewport/CSS zoom/devicePixelRatio는 대체 증거 아님. 로그아웃·운영 환경 변경이 필요하면 별도 승인 전 중단.

## 8. 필요한 승인 범위·롤백·운영 보호

**다음 승인 후보:** 검증 전용 네이티브 어댑터/정식 Guard-first 진입점의 제한된 구현과 보안 negative 검사. 대상 파일·native 호출·파라미터/경로/handle/PID 통제·롤백 기준을 고정한 뒤 승인받아야 합니다. 이는 운영 Guard 변경·DLL 전체 허용·앱 실행·DPI 변경·실계정 API 승인을 포함하지 않습니다.

**그 다음 별도 실행 조건:** 검토된 어댑터가 실제로 보안 정책을 유지함이 입증되고, 현재 checkout 및 합성 프로필·키 미유입·worker 차단·18765 통신·소유 프로세스 정리 절차가 승인돼야 합니다. 현 단계에서는 시작하지 않습니다.

**롤백 설계:** 기존 Guard/bridge/config/패키지 해시와 원본을 유지한 별도 검증 작업본에서만 변경합니다. 실패 시 소유 테스트 프로세스를 정상 종료하고 필요하면 cleanup을 별도 기록합니다. 잠금을 보유한 상태에서는 Guard/패키지를 교체하지 않습니다. 검증 전용 추가 설정만 되돌리고 운영 DB rollback·운영 앱 재시작·백업 변경을 하지 않습니다. DPI를 승인 후 변경했다면 테스트 세션의 기록된 원래 값만 복원합니다.

## 9. 이번 결과와 미확정 항목

- 설치 버전·현재 import 경로·native 후보 호출·정책 충돌·과거 bridge의 제약은 코드로 확인.
- 과거 최초 raw traceback 및 당시 filelock 버전은 미확보. 현재 코드의 예상 차단 순서를 과거 실제 로그 순서로 단정하지 않음.
- B의 wrapper 안전성과 전체 앱 호환성, C의 실제 대화형 Windows 11 가용성, OS DPI 4개 배율은 **NOT VERIFIED**.
- 현재 조건의 로컬 전체 앱은 **BLOCKED**. 설계 검토 결과는 **CONDITIONAL**.
- 신규 테스트·전체 회귀·UI 재구축·디자인 원본 검사·앱 기동·DPI 변경·Guard/패키지/import 순서 변경·실제 유료 API/OAuth/SNS 모두 0.
- 제품·운영 앱·DB·설정·키·미디어·백업·PR #35·main 변경 없음. 기존 로컬 변경 보존. 문서·비민감 해시 근거만 작업 브랜치에 보존.

[정적 소스 근거](SOURCE_EVIDENCE.json) · [호출별 검토](NATIVE_CALL_REVIEW.json)

분석·설계 제출 후 중단합니다. 실제 해결 코드는 적용하지 않았으며 다음 명시적 승인을 기다립니다.
