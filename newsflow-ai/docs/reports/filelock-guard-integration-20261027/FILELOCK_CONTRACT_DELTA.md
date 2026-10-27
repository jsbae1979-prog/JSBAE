# filelock 3.32.7과 검증 어댑터의 계약 차이

비교 기준: 호스트 설치 소스 8개와 CI 설치 filelock 3.32.7의 AST 지문이 모두 일치했다.
이 결과는 소스 계약 식별이며, upstream 패키지를 실행한 호환성 시험 결과가 아니다.
원본 패키지·운영 Guard·기존 39 PASS 어댑터는 수정하지 않았다.

소스 위치는 설치된 `filelock/` 아래 상대 경로다. 정확한 함수별 줄 번호와 지문은
`tools/native_capability_integration/contract_snapshot.json`에 보존했다.

| 계약 | 실제 설치 소스 | 기존 제한 어댑터 | 이번 검증 계층 / 판정 |
|---|---|---|---|
| import | `__init__.py:15-19` → `_descriptor.py:10-11` → `_windows.py:58-59`; marker/lease/identity도 eager import | 고정 DLL 바인딩만 제공; raw WinDLL 대리 객체 없음 | upstream 사전 import/모듈 대체 안 함. 기존 Guard 직접 연결 **BLOCKED** |
| 실제 파일 잠금 | `_windows.py:155-172` exclusive 1-byte offset 0 | 동일한 실제 LockFileEx/UnlockFileEx 원시 잠금 | 두 개의 독립 핸들로 실제 경합·해제 확인 **PASS** |
| descriptor | `_descriptor.py:16-74`, `_windows.py:274` CRT fd와 native handle 소유권 이전. 호출자는 descriptor 소유 | 등록된 opaque capability만 제공 | raw CRT fd, lock_descriptor, on_acquired callback 노출 **BLOCKED** |
| 재진입 | `_api.py:983-1069,1099-1130` counter 증가, 중첩 release에서는 OS 잠금 유지 | 같은 capability 재진입은 거부 | 같은 스레드 세션에서 counter 관리, outer lock 유지 검증 **PASS (부분집합)** |
| acquire context | `_api.py:944-960,1069,1430-1452` acquire가 proxy 반환, with는 추가 획득하지 않음 | 없음 | acquire proxy·일반 with·중첩 with 검증 **PASS (부분집합)** |
| timeout | `_api.py:983-1069` 음수는 무한 대기, blocking/cancel/poll 지원 | 유한 0~2초만 허용 | 명시적 유한 대기/nonblocking만 **PASS**. 무한 대기·cancel/poll 옵션 **BLOCKED** |
| 스레드/Singleton | `_api.py:349-445,649-725` 기본 thread-local; shared instance와 singleton 지원 | 소유 스레드만 해제 | cross-thread 사용/설정, singleton **BLOCKED**. 같은 스레드 기능만 검증 |
| 잠금 소유자 정보 | 기본 WindowsFileLock은 BaseFileLock의 현재 PID/descriptor 추적. `_marker.py:8,81-96` 및 `_identity.py:61-103`의 marker/lease는 별도 owner/process 정보 | 다른 PID 조회 없음 | OpenProcess/GetProcessTimes를 기본 잠금에 필요한 것으로 확대하지 않음. marker/lease/stale recovery **BLOCKED** |
| unlock 실패 | `_windows.py:201-209`, `_api.py:1119-1130` descriptor/counter 유지 | 성공 전 owner 상태를 지우지 않음 | 논리 소유권과 counter 유지. 물리 결과 불명은 UNKNOWN, 자동 재요청 차단 **PASS** |
| unlock 후 close 실패 | `_windows.py:201-214`, `_api.py:1122-1126` 이미 풀린 잠금을 다시 held로 만들지 않음 | 닫기 실패 시 소유 핸들 유지 | depth 0 + cleanup_required, peer 획득 가능, 명시적 정리 검증 **PASS** |
| 경로/파일 생성 | `_windows.py:215-321` FILE_OPEN_IF, 파일 존재/재사용, CRT 변환, NT 경로 버퍼 할당/해제 | 새 direct-child .lock만 등록, 상위 디렉터리 고정, 열린 핸들 최종 경로/ID 확인 | 안전 경계를 확장하지 않음. 일반 기존 파일/경로와 Rtl 변환/free 계약 **BLOCKED** |
| 해제 후 파일 삭제 | `_windows.py:211-213` preserve_lock_file=False이면 unlink 시도; 실패는 허용 | 등록 anchor가 파일을 scope 종료까지 보유 | stable synthetic 파일 유지만 제공. default unlink와 동일하다고 주장하지 않음 **BLOCKED (기본 전체 계약)** |
| GC 정리 | `_api.py:973-981` best-effort force release | scope 명시적 close | 명시적 registry/session close만 검증. upstream GC finalizer 호환 **NOT VERIFIED** |
| 결과 불명·복구 | upstream 계약을 임의 변경하지 않음 | 파일 잠금 원시 상태만 관리 | acquire/unlock 불명, journal 실패, cleanup 상태를 분리. saved journal은 capability가 아님. 자동 재획득 없음 **PASS (검증 세션)** |
| 비동기/RW/fork/soft fallback | upstream의 별도 계약 | 미제공 | **BLOCKED / 미검증**, 대체 구현 안 함 |

제품 `src/newsflow/main.py:86,337-338`은 FileLock.acquire(timeout=0) 컨텍스트를 사용한다.
이번 부분집합은 이 형태의 의미를 검증했지만 제품의 FileLock 객체·import·경로·정리 계약을
대체하지 않았다. 따라서 제품 실행 가능 판정으로 확대하지 않는다.
