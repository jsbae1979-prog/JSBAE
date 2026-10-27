# 검증용 Guard 사본·filelock 접점 통합 검증

## 최종 판정

**CONDITIONAL**

- 실제 검증용 Guard 사본 설치·capability 등록·CRT/Python 소유 버퍼의 제한 접점: **PASS**
- 변경 없는 filelock 3.32.7 전체 import/실행: **BLOCKED**
- filelock의 Rtl 경로 변환·native free 계약: **BLOCKED**
- 전체 Python 앱: **실행하지 않음 / 이번 승인 범위 밖**
- Windows 11 로컬 앱·실제 OS DPI: **NOT VERIFIED / 변경 없음**

이번 결과는 filelock 전체 호환성이나 운영 실행 승인이 아니다.

## 1. 브랜치와 검증 기준

- 저장소: `jsbae1979-prog/JSBAE`
- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`
- 시작 HEAD: `65c9d469bd7c58e1908d2f5fd4b03d5f769c5df6`
- 최종 검증 코드: `b9fa0426cb676c20c1223359e92e2548b63b0e02`
- CI: Windows Server 2025 x64 build 26100 / Python 3.14.7
- [최종 Windows CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40518651508)
- [검증 아티팩트](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40518651508/artifacts/12741400473)

이 보고서를 추가한 커밋은 보고서 전용이며 실행 코드를 변경하지 않는다.
호스트에서는 소스 읽기·문법/AST·해시 검사만 수행했다. Guard 사본의 실제 설치와 native/CRT 실행은 CI에서만 수행했다.

## 2. Guard 사본과 정확한 변경 범위

신규 검증 도구: `newsflow-ai/tools/native_guard_copy/`

| 자료 | 설명 |
|---|---|
| guard_original.py | 원본 Guard의 바이트 동일 사본; 실행하지 않는 비교 기준 |
| guard_verification.py | 실제 CI에서 설치한 검증용 사본 |
| native_boundary_original.py | 기존 Guard installer가 필요로 하는 의존 파일의 바이트 동일 사본 |
| guard_copy.patch | 원본 대비 변경 diff |
| GUARD_COPY_PROVENANCE.json | 원본/사본 SHA-256과 AST 비교 결과 |
| SOURCE_HASHES.json | CI에서 다시 확인한 검증 코드 지문 |

SHA-256:
- 원본 Guard: `d59add898d2e3d846932705a94354810a8a4a4fb394da5193b717949fc43a6d9`
- 최종 실행 사본: `9446556de593c9d59d11a9b2260a5ecb4d4be1e55fe7e2d8bcc45c9626438257`
- 원본 실행 경계 의존 파일: `85738677846fbc86b0169d41854e616b94ef674849e3f7190d4c3452ede628fa`

논리 변경은 두 dispatch 지점과 세 개의 등록 helper로 제한했다.

1. audit 앞에 등록된 capability 이벤트 확인 1개
2. _guarded_windll 앞에 검증된 private binding 확인 2개 문장
3. register_verification_capability / _verification_capability_event / _verification_private_binding 추가

기존 모든 나머지 함수·클래스 AST와 기존 모듈 초기화 문장은 동일하다.
기존 install 함수, 파일/DB/프로세스/네트워크 검사, DLL/심볼 전역 테이블을 변경하지 않았다.
원본 바이트는 CRLF와 마지막 빈 줄까지 보존했으며 실행 사본만 LF로 저장했다.
Git 형식 예외는 원본 fixture 및 diff 문맥에 한정되고 코드/보안 검사 규칙 완화가 아니다.

의존 native_boundary.py는 CI 임시 폴더에 그대로 배치했다.
그 안의 bootstrap/앱 코드 문자열은 실행하지 않았다.
child 실행 설정은 만들지 않았고 실제 launch 수는 0이었다.

## 3. Capability 등록 방식

실제 순서:
1. fresh Runner 임시 경로와 합성 설정 생성
2. 실제 Guard 사본 install
3. 기존 verification_gate install
4. 실제 클래스 동일성·소스 SHA가 확인된 capability를 일회성 등록
5. 기존 native adapter의 고정 binding 실행

사전 filelock import, import 순서 우회, Guard 비활성화 또는 운영 Guard 교체는 없다.
NativeRegistration의 클래스 이름만 흉내 낸 객체는 실제 클래스 객체 동일성 검사에서 거부되며,
private loader를 받기 전에 차단된다. Guard 설치 전 등록과 중복 등록도 거부한다.

native private binding은 기존 adapter의 검증된 initializer와 해당 스레드의 단일 binding 문맥에서만 허용한다.
정확한 System32의 kernel32.dll/ntdll.dll과 기존 8개 고정 함수 바인딩만 사용한다.
DLL 해시 읽기도 그 두 파일과 binding 문맥으로 제한한다.
NTDLL을 일반 허용 목록에 추가하지 않았다.

공개 API로 DLL·함수 포인터·raw handle·CRT fd를 반환하지 않는다.
공개 ctypes.WinDLL("ntdll"), kernel32의 미등록 OpenProcess, raw CRT 호출은 계속 거부된다.
내부 raw DLL 객체는 기존 native adapter의 고정 binding 내부에서만 사용한다.

CRT 요청은 등록된 boundary 객체, 현재 소유권 이전 요청, 정확한 handle/flags 또는
등록된 descriptor와 일치해야 한다. 소유 native handle이라는 사실만으로 임의 CRT 이전을 허용하지 않는다.

이 모델은 검토된 신뢰 가능한 Python 하네스의 capability 경계다.
비공개 속성 조작·악성 reflection을 막는 OS 보안 격리로 주장하지 않는다.

## 4. CRT descriptor 소유권 검증

구현: `descriptor_boundary.py`, 등록/감사: `guard_capability.py`

- 기존 잠금 scope에 등록된 새 합성 파일만 핸들로 연다.
- 열린 핸들의 실제 최종 경로·파일 ID·링크 수·reparse 여부를 확인한다.
- open_osfhandle 성공 전에는 native 장부가 소유한다.
- 성공 후 native 소유권을 제거하고 CRT descriptor 장부로 이전한다.
- 이후 잠금에 필요한 native handle은 등록 fd를 검증한 뒤 일시적으로만 빌린다.
- CRT 소유 핸들은 Native CloseHandle로 닫을 수 없다. os.close(fd)가 descriptor와 underlying handle을 정리한다.
- token이 닫히거나 통지가 실패해도 이미 정리된 descriptor를 다시 닫지 않는다.
- 실제 1바이트 LockFileEx 경합·유한 timeout·재진입·UnlockFileEx 의미를 유지한다.

소유권 이전 후 _close가 underlying handle도 닫는 의미는 [Microsoft _open_osfhandle 문서](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)와 대조했다.
Python의 open_osfhandle/get_osfhandle 감사 이벤트와 O_NOINHERIT는 [Python msvcrt 문서](https://docs.python.org/3.14/library/msvcrt.html)를 참고했다.
문서만으로 PASS를 주지 않고 실제 CI 핸들 이전과 잠금 경합으로 검증했다.

실패/결과 불명 처리:
- CRT 이전을 시작하지 않은 합성 실패: native 소유 핸들만 정리
- CRT 이전이 확정된 뒤 통지 실패: descriptor 장부를 보존하고 같은 버퍼로 재요청 차단
- close 전 합성 실패: 기존 descriptor 보존, 새 잠금 실행 차단
- close 확정 후 통지 실패: 소유권을 이미 제거한 상태 유지, stale token의 재닫기 차단
- OS 잠금 성공 직후 오류: 실제 peer 경합을 확인하고 자동 잠금 재요청 차단, 명시적 소유 descriptor 정리 후 peer 획득 확인
- unlock 실패: 논리 depth와 소유권 유지; 자동 재획득 차단

CRT 호출/반환 사이의 **완전히 관측할 수 없는 예외**는 안전한 소유자를 추정하지 않는다.
unresolved transfer/close로 격리하고 자동 닫기·재시도·검증 성공을 차단한다.
이 불확실한 실제 CRT 오류를 일부러 발생시켜 위험한 정리를 시도하지 않았다.
이번 PASS는 정상 이전과 알려진 전/후 실패 주입에 대한 결과이며, 모든 비동기 중단 상황의 완전한 회복 증명은 아니다.

## 5. 경로 버퍼 검증과 Rtl 차이

이번에 검증한 버퍼는 등록 파일의 단일 상대 이름을 담는 **Python 소유 UTF-16 버퍼**다.

- 경로는 scope 등록 목록·직접 자식 규칙을 만족해야 함
- 동기 NtCreateFile 동안 실제 버퍼를 유지
- 사용 중 해제 거부
- 외부/이미 해제된 token·이중 해제 거부
- public API에 포인터/해제 주소 노출 없음
- CRT 이전 후의 통지 불명은 버퍼를 재요청 가능 상태로 바꾸지 않음

이것은 filelock의 RtlDosPathNameToNtPathName_U_WithStatus와 RtlFreeUnicodeString 계약을 대체하지 않는다.
두 Rtl 호출의 native 할당·해제는 **구현/허용하지 않았으며 BLOCKED**다.
RtlFreeUnicodeString을 임의 Python 버퍼에 호출하지 않았다.
native Rtl 소유권 장부가 없는 상태에서 호환성을 임의로 PASS 처리하지 않았다.

## 6. 신규 보안 테스트 결과

**29 PASS / 0 FAIL / 0 ERROR / 0 SKIP**

- 신규 Guard 사본·CRT·버퍼 테스트: 27개
- 기존 영향 범위: 2개 (parent junction, 열린 핸들 최종 경로 불일치)
- 기존 39/32 전체·UI·전체 Python 회귀: 반복 안 함

| 검증 | 판정 |
|---|---|
| 실제 Guard 사본의 Guard-first 순서 | PASS |
| 등록 전/중복/위조 클래스 거부 | PASS |
| 기존 함수 AST·DLL/심볼 테이블 불변 | PASS |
| 실제 CRT 이전·소유권 장부 분리 | PASS |
| CRT 소유 핸들의 native close 거부 | PASS |
| 실제 잠금 경합·timeout·재진입·해제 | PASS |
| 외부 경로·UNC/ADS/Device·외부 핸들/PID 거부 | PASS |
| raw CRT/DLL·미등록 심볼 거부 | PASS |
| Python 소유 버퍼 수명·사용 중 해제·이중 해제 | PASS |
| 실제 OS 잠금 성공 후 결과 불명 재요청 차단 | PASS |
| 알려진 CRT 이전/close 전후 실패와 통지 불명 | PASS |
| 네트워크/DNS·운영 포트·프로세스·DB·프로젝트 쓰기 보호 | PASS |
| 원본 그대로의 filelock 전체 import | BLOCKED (거부 검사는 PASS; 실행 성공이 아님) |
| native Rtl 변환/free | BLOCKED |

최종 자원 상태:
- 소유 native 파일 핸들: **0**
- 소유 CRT descriptor: **0**
- Python 경로 버퍼: **0**
- unresolved transfer: **0**
- 합성 파일/폴더 잔여: **0** (증거 파일 생성 전)
- 정리 오류: **0**
- native boundary child launch: **0**
- 기존 Guard 소유 핸들 장부 잔여: **0**

System DLL과 interpreter의 일반 프로세스 수명 자원을 모두 0으로 셌다는 의미는 아니다.
테스트가 소유한 파일/descriptor/buffer와 합성 산출물에 대한 수치다.

filelock 3.32.7 소스 계약 지문 8/8이 기존 기준과 일치했다.
실제 패키지는 두 Guard 설치 후 마지막 negative probe에서 한 번 import를 시도했고 native binding에서 거부됐다.
그 과정에서 일부 순수 Python 하위 모듈이 로드될 수 있지만, 패키지 전체 import/잠금 실행이 성공한 것으로 보고하지 않는다.
제품 모듈과 전체 앱은 import/실행하지 않았다.

최초 `546c4b2`도 [29 PASS](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40518067937)였다.
실제 클래스 동일성·위조 객체 거부를 강화한 `b9fa042`에서 같은 29개를 재검증했다.
58개 신규 테스트로 합산하지 않는다. 신규/기존 FAIL·ERROR, 추가 skip/xfail은 없다.

## 7. 기존 Guard·제품·운영 보호

[POLICY_PRESERVATION.json](POLICY_PRESERVATION.json) 참조.

- 실제 원본 Guard·기존 실행 경계 파일: 변경 0, 사본과 원본 바이트 일치
- 설치된 filelock 3.32.7: 변경 0
- 기존 native_capability 및 native_capability_integration: 변경 0
- 제품 Python/React/CSS·DB schema·실제 앱 진입점: 변경 0
- 운영 앱 종료·재시작·포트 점유: 없음
- 운영 DB·설정·키·토큰·미디어·백업: 입력 사용/변경 없음
- DPAPI 복호화·실제 API·OAuth·SNS: 수행 안 함
- Windows 11 로컬 전체 앱·DPI 변경: 수행 안 함
- PR #35 Draft·미병합, 기존 HEAD 유지; main/운영 브랜치 변경 없음
- 기존 validation/와 로컬 자료 보존; reset/clean/stash/force push 없음

운영 데이터의 새 전수 해시 검사는 반복하지 않았고 기존 보존 증거를 재사용했다.
실행 중 운영 앱 자체의 데이터 변경까지 이번 작업에서 새로 해시 불변이라고 단정하지 않는다.

## 8. 남은 차단과 전체 앱 실행 승인 조건

현재 정식으로 실행한 경로는 **CI의 검증 도구**뿐이며 앱 launcher가 아니다.

필요 조건:
1. Rtl native 경로 할당/free 또는 정식 upstream 접점의 소유권·입력·수명 규칙을 먼저 입증해야 한다.
2. 변경 없는 filelock의 실제 import, FileLock acquire/release, CRT 소유권 이전·파일 재사용/기본 정리 계약에 대한 **positive** CI 검증이 필요하다. 현재 negative 거부 PASS는 이를 대체하지 않는다.
3. 검증 불가한 CRT 중단/소유권 불명 상태는 계속 BLOCKED로 두어야 한다. 소유자를 추정해 강제 닫거나 다른 FD/PID를 해제하면 안 된다.
4. 전체 앱을 위해서는 승인된 테스트 데이터 경로, loopback 전용 테스트 포트와 worker/스케줄러/실 API·게시 차단을 별도로 확정해야 한다. 현재 capability gate는 socket/process를 전부 차단하므로 앱용 실행 정책으로 사용할 수 없다.
5. Windows 11 로컬 전체 앱 실행은 별도 명시적 승인이 필요하다. 운영 앱 재시작과 DPI 변경은 자동으로 포함되지 않는다.

이번 단계 완료 후 Rtl 허용 범위 확대, 실제 앱 실행, 운영 적용 또는 다음 구현을 자동 진행하지 않는다.
