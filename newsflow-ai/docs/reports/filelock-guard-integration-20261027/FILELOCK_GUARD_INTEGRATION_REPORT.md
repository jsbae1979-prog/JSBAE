# Guard·filelock 연동 적합성 검증 결과

## 판정

**CONDITIONAL** — 검증 전용 통합 계층의 제한된 계약과 보안 검증을 완료했다.
**변경 없는 upstream filelock + 기존 Guard의 실제 직접 연동은 BLOCKED**다.
Windows 11 로컬 전체 앱과 실제 OS DPI는 실행하지 않았다.

## 1. 기준과 브랜치

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 시작 HEAD: `3f568113e4252b5a643144a5388358e4f74f22fe`
- 최종 검증 코드: `48c93e55cf37baaac03e1541871400f1bc376125`
- 환경: GitHub Actions Windows Server 2025 x64 build 26100 / Python 3.14.7
- [최종 CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40512952761)
- [증거 아티팩트](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40512952761/artifacts/12736959284)

이 문서를 추가하는 커밋은 보고서 전용이며 실행 코드 변경이 없다.
현재 PC에서는 소스·메타데이터·지문과 문법만 확인했다. filelock이나 전체 앱을 import/기동하지 않았다.

## 2. filelock 실제 계약과 차이

실제 설치 버전은 **3.32.7**이다. CI에서도 동일 버전을 별도 설치한 후
패키지를 import하지 않고 8개 소스의 정규화한 AST 지문을 비교했다. **8/8 일치**했다.

정확한 비교표: [FILELOCK_CONTRACT_DELTA.md](FILELOCK_CONTRACT_DELTA.md)

주요 차이는 원시 CRT descriptor, 재진입 counter/컨텍스트, 무한 대기·스레드 공유,
marker/lease 소유자 정보, 기존 잠금 파일의 재사용·삭제 및 GC 정리다.
기본 WindowsFileLock의 PID 추적과 marker/lease의 외부 프로세스 조회를 구분했다.
OpenProcess가 기본 잠금 획득에 무조건 필요하다고 결론 내리지 않았다.

이번 세션 계층은 실제 native byte lock 위에 **같은 스레드·유한 대기의 계약 부분집합**을 연결한다.
FileLock/BaseFileLock 대체 클래스가 아니며, upstream runtime 성공을 주장하지 않는다.

## 3. Guard 연결 방식과 안전성

기존 `step13_guard.py`의 고정 DLL/심볼 및 소유 핸들 정책을 읽기 전용으로 대조했다.
정식 capability 등록 API를 찾지 못했다. 해당 Guard는 NTDLL 및 필요한 심볼을 허용하지 않고,
기존 소유 핸들 레지스트리도 새 어댑터의 핸들을 등록할 공개 절차가 없다.

따라서 기존 Guard의 내부 allowlist/ctypes/핸들 테이블을 수정·덮어쓰거나 우회하지 않았다.
기존 Guard 파일을 실행하거나 사전 import로 filelock을 통과시키지도 않았다.

현재 가능한 연결은 **별도 Windows CI의 기존 verification_gate → native adapter → 신규 VerificationRegistry**다.

- gate 설치 후에만 capability 등록
- 허용 capability 이름 1개, 등록된 합성 이름·경로만 사용
- raw DLL/함수 포인터/OS 핸들/CRT fd/PID 기능을 public 결과로 제공하지 않음
- 기존 네이티브 어댑터·verification_gate는 **수정 0**
- upstream와 제품 모듈 import는 새 CI 진입점에서 추가 차단
- 지원 불가 계약은 CompatibilityBlocked로 거부; 잠금 없는 대체나 raw DLL proxy 없음
- native/파일·네트워크·프로세스 보호 정책을 더 넓히지 않음

이것은 신뢰 가능한 검증 하네스의 제한 API다. 악성 Python reflection을 막는 OS 격리로
주장하지 않으며, Windows 사용자의 운영 파일 권한을 제거했다는 의미도 아니다.

## 4. 신규 통합 계층 파일

모두 `newsflow-ai/tools/native_capability_integration/` 아래에 있다.

| 파일 | 내용 |
|---|---|
| contract_bridge.py | 등록된 합성 세션, 재진입/컨텍스트, 실패/불명/정리 상태와 journal |
| contract_probe.py | 설치 메타데이터와 소스 AST 읽기 전용 비교 |
| contract_snapshot.json | 호스트 실제 3.32.7 소스 지문·함수 줄 번호·기존 Guard 심볼/함수 목록 |
| test_contract_bridge.py | 신규 24개 집중 검사 |
| run_integration.py | Guard-first CI 진입, 선택된 기존 8개 검사, 증거·정리 |
| README.md | 지원/차단 및 신뢰 경계 |

저장소 `.github/workflows/newsflow-native-contract.yml`은 이 검증만 실행한다.
제품 Python/React, migration, 운영 Guard, filelock 패키지는 변경하지 않았다.

## 5. 집중 검증 결과

**32 PASS / 0 FAIL / 0 ERROR / 0 SKIP**

- 신규 계약/보안 **24 PASS**
- 영향 범위의 기존 보안 **8 PASS**
- 기존 39개 전수 재실행, 전체 Python 회귀, UI/디자인 감사: 수행 안 함
- 기존 39 PASS·7 PASS 앱/API·59 PASS CI·42 PASS 합성 UI는 과거 증거로 재사용하며 합산하지 않음

| 항목 | 실제 검증 결과 |
|---|---|
| Guard-first | gate 설치 → 어댑터 binding → registry 순서 PASS; upstream/product import 0 |
| 재진입/컨텍스트 | 중첩 1회 해제 후 peer 실제 잠금 경합 유지, 최종 해제 후 획득 PASS |
| timeout/nonblocking | 실패한 세션 counter 복원, 기존 소유 세션 불변 PASS |
| 실제 잠금 성공 직후 결과 불명 | native LockFileEx 성공 후 오류 주입. peer 경합으로 실제 잠금 유지 확인. held=null/physical_lock_state=UNKNOWN 기록 및 자동 재실행 거부 PASS |
| 명시적 불명 정리 | 소유 핸들의 명시적 close 후 peer 획득 PASS. 정상 Unlock 성공으로 표시하지 않음 |
| unlock 실패 | 논리 소유권/counter 유지, 물리 상태 UNKNOWN, journal 보존 및 재획득 거부 PASS |
| unlock 후 close 실패 | 미잠금 + cleanup_required 상태, peer 획득 가능, 명시적 close PASS |
| 본문 오류 + 해제 오류 | 원본 본문 예외를 release 예외의 context에 보존 PASS |
| journal 실패 | 성공으로 표시하지 않고 신규 실행 차단; 명시적 정리 PASS |
| 저장 기록 재사용 | JSON 기록만으로 capability 발급/자동 잠금 재획득 불가 PASS |
| 경로/핸들/PID | 주입된 경로·외부/위조 핸들·더미 외부 PID·Junction·최종 경로 불일치 거부 PASS |
| DLL/심볼 | raw WinDLL과 registry의 native symbol/descriptor/PID export 거부 PASS |
| 정리 | native 핸들 **0**, 합성 자료 잔여 **0**, 정리 오류 **0**, 추가 자식 프로세스 **0** |

물리 잠금 상태와 논리 소유 counter를 구분했다.
결과 불명 시 false/0으로 확정하지 않고 UNKNOWN/null을 보존한다.
자동 재요청·외부 소유 잠금 파괴·프로세스 종료는 구현하지 않았다.
journal 쓰기 자체가 실패하면 영속 보존 성공을 주장하지 않으며, 메모리 상태를 차단하고
명시적 정리가 필요하다.

이번에 다시 실행한 기존 테스트는 정확히 다음 8개다:
test_01_guard_first, test_02_real_exclusive_lock_and_release,
test_05_raw_and_forged_handles, test_20_external_PID_blocked_before_OS,
test_21_raw_DLL_blocked, test_27_parent_junction_is_denied,
test_31_handle_path_mismatch_is_denied, test_33_failed_unlock_preserves_state.

네트워크/DNS 차단의 기존 39 PASS 증거는 변경 없는 verification_gate에 대해 재사용했다.
이번 단계에서 네트워크 probe를 반복하지 않았으며 실제 API 호출은 없다.

첫 검증 `74e109b`도 [32 PASS](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40512311931)였다.
검토 중 물리 결과 불명의 표시를 더 엄격하게 보완하고, 실제 OS 성공 직후 오류 사례를 강화한
`48c93e5`에서 같은 32개를 재검증했다. 별도 합계 64개 또는 신규 32개로 계산하지 않는다.
기존/신규 FAIL·ERROR 및 추가 skip/xfail은 없다.

## 6. 기존 정책·운영 자료 보호

[POLICY_PRESERVATION.json](POLICY_PRESERVATION.json)에 변경 범위와 해시 비교를 기록한다.

- 기존 Guard SHA-256 유지:
  `d59add898d2e3d846932705a94354810a8a4a4fb394da5193b717949fc43a6d9`
- 설치된 filelock Python 소스: 기존 baseline과 동일
- 기존 native_capability 폴더: 기준 HEAD 대비 변경 0
- 제품/프런트엔드/DB schema/진입점: 변경 0
- 운영 앱 종료·재시작·포트 점유·운영 Guard 실행/변경: 없음
- 운영 DB·설정·키·토큰·미디어·백업: 테스트 입력 사용/수정 없음
- 운영 DB 등의 새 전수 해시 검사는 하지 않았고 기존 보존 증거를 재사용
- Windows 11 전체 앱 실행·실제 DPI 변경·유료 API·SNS: 없음
- PR #35 Draft·미병합 및 기존 head 유지, main/운영 브랜치 변경 없음
- 기존 `validation/`과 로컬 자료 보존; reset/clean/stash/force push 없음

## 7. 실제 전체 앱 실행 가능 여부와 남은 차단

**현재는 실행 불가(BLOCKED)이며 실행하지 않았다.**

1. 기존 Guard에 정식 검증용 capability 등록 훅이 없다.
2. 변경 없는 filelock import/NT 경로 버퍼·native 심볼 계약을 연결하지 않았다.
3. CRT descriptor의 소유권 이전·수명·콜백과 실제 upstream의 파일 재사용/기본 정리 계약이 미검증이다.
4. marker/lease의 외부 owner 확인·불명 소유자 회수는 차단 상태이며 필요성도 별도로 확인해야 한다.
5. 같은 스레드/유한 timeout/새 합성 잠금 경로 밖의 계약을 이 계층이 대신하지 않는다.

## 8. 다음 단계에 필요한 최소 승인

다음 중 승인된 범위만 후속 수행할 수 있다.

- **운영 파일과 분리된 검증용 Guard 사본**에 고정 capability 등록 훅을 추가하고,
  기존 파일·DB·프로세스·네트워크 정책이 그대로 유지되는지 비교 검증.
- 해당 훅에서 **변경 없는 filelock 3.32.7의 native/CRT 소유권 접점**을 검증용으로 연결해
  import, 실제 FileLock acquire/release, 필요한 descriptor·정리 계약만 Windows CI에서 검증.
  Rtl 경로 버퍼 할당/free는 소유권 장부·정확히 한 번 해제 등 경계를 먼저 입증해야 한다.
  임의 PID 조회는 자동 승인하지 않으며 불필요하면 계속 차단.

이는 운영 Guard 수정이나 로컬 전체 앱 실행 승인이 아니다.
실제 전체 앱·Windows 11 로컬 검증·DPI는 별도 승인 단계로 남긴다.
현 계층의 테스트 성공만으로 앱 실행을 허용하지 않는다.

## 9. 종료

검증 전용 계층·소스 계약 비교·집중 CI·보존 증거를 지정 브랜치에 저장하고 중단한다.
운영 반영, PR #35 변경, main 병합, 추가 기능 개발 또는 전체 앱 실행을 이어서 수행하지 않는다.
