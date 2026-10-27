# Rtl 소유권 및 실제 FileLock 호환성 검증

작성일: 2026-10-28 KST. 판정: **CONDITIONAL**.

검증 전용 경계에서 실제 filelock 3.32.7의 Guard-first import와 기본 Windows FileLock 계약을 검증했다. 전체 앱 실행이나 운영 적용 승인이 아니다. 기존 39·32·29 PASS는 이전 증거로 재사용했으며 합산해 신규 결과로 표시하지 않는다.

## 기준과 변경 범위

- 저장소: jsbae1979-prog/JSBAE
- 브랜치: codex/newsflow-core-studios-rebuild-20261027
- 시작 보고 커밋: 297510601be4709b69db9ece264cba501ae15532
- 검증 코드: 11ad046394267bd2589ccff67c37549839f555db
- 추가 파일: tools/native_rtl_filelock/ 및 전용 Windows Actions workflow.
- 기존 tools/native_capability/, native_capability_integration/, native_guard_copy/와 제품 Python/React는 수정하지 않았다.

## 실제 호출과 소유권

RtlDosPathNameToNtPathName_U_WithStatus의 실제 native 할당을 Python 소유 출력 구조체와 별도로 추적한다. native 소유 UNICODE_STRING만 RtlFreeUnicodeString에 전달하며 임의·외부·Python 소유 포인터, 이중 해제, 사용 중 해제와 소유권 불명 상태를 거부한다. 해제 후 caller 필드는 0으로 정리한다.

변환 문자열 자체를 신뢰하지 않는다. 등록된 DOS 경로와 NT 변환 결과를 비교하고, 조상 디렉터리와 파일 anchor를 고정한 다음 실제 NtCreateFile 결과 핸들의 최종 경로·파일 ID·reparse/link 상태를 재검증한다. raw 호출자 포인터를 그대로 native 함수에 전달하지 않는다. bounded native 읽기도 helper 주소·스레드·소유 포인터·길이에 제한한다.

기존 Guard 사본은 바이트 그대로 사용했다. 검증 gate의 별도 사본에 인스턴스별 Rtl 바인딩만 추가했다. 기존 전역 DLL/심볼 표와 파일·네트워크·프로세스·DB 차단은 유지했다. OpenProcess/GetProcessTimes는 패키지 import 선언에 필요한 거부 callable만 제공하며 실제 조회는 허용하지 않는다.

## 실제 패키지와 접점

설치된 filelock 3.32.7을 Guard 설치 후 처음 import했다. 실제 클래스는 filelock._windows.WindowsFileLock이다. 패키지 전체 Python 소스 해시와 주요 메서드 코드 identity를 전후 비교했다. 패키지 파일과 클래스 메서드는 교체하지 않았다.

네이티브 접근에는 검증 전용 고정 facade와 CRT 경계 wrapper를 사용했다. import 문맥·호출 문맥과 출력 구조를 검사하며 facade는 raw DLL/함수 포인터를 공개하지 않는다. 실제 Rtl/NT/잠금 호출을 수행하므로 Fake lock 성공과 구분한다.

CRT descriptor는 실제 open_osfhandle 소유권 이전 뒤 Native CloseHandle 소유 집합에서 제거한다. get_osfhandle 사용 시 등록 descriptor와 파일 identity를 확인한다. 마지막 해제는 os.close이며 native와 CRT 양쪽에서 같은 핸들을 닫지 않는다. 실패·결과 불명은 단계별로 기록하고 자동 재호출하지 않는다.

## 최종 신규 실행 결과

[Windows Actions run 40528900618](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40528900618), job 122275943265. Windows Server 2025 build 26100, Python 3.14.7. UTC 2026-10-27 15:13:56~15:15:25 (KST 2026-10-28 00:13:56~00:15:25).

| 항목 | 실제 결과 |
|---|---|
| 집중 테스트 | **28 PASS / 0 FAIL / 0 ERROR / 0 SKIP** |
| 구성 | 신규 26개 + 영향 범위의 기존 경로 검사 2개 |
| 실제 패키지 | filelock 3.32.7 / WindowsFileLock |
| Guard-first import | PASS |
| acquire(timeout=0), 경합/timeout, context/reentry/release | PASS |
| Rtl native 할당 / 해제 | **26 / 26** |
| 최종 native handle / CRT descriptor / native buffer | **0 / 0 / 0** |
| unresolved native calls / cleanup errors / 잔여 합성 파일 | **0 / 0 / 0** |
| 기본 unlink 실제 성공 | test_26 PASS, 퇴역 경로 재개방 차단 |
| 외부 경로·Junction·handle·PID·DLL·symbol·네트워크·프로세스 | 거부 검사 PASS |
| 실제 패키지 소스/메서드 보존 | 전체 CI Python 소스 21개 및 주요 메서드 identity 불변 |
| 제품 import / native_boundary process launch | false / 0 |

패키지 경계 NtCreateFile 카운터는 21이며 setup anchor/ancestor 열기는 포함하지 않는다. lock/unlock 카운터 20/15에는 fault injection 시도가 포함되므로 모두 성공한 OS 호출 수로 해석하지 않는다. CRT 경계 호출은 113회다.

정상 release와 오류 후 명시적 자원 정리를 구분했다. unknown fault-injection 경로 2개는 자동 재호출 금지 상태 기록을 유지한다. 삭제 후 퇴역 경로 1개도 새 파일 세대로 자동 재사용하지 않는다. 둘 다 잔여 열린 자원이 아니다.

[CI artifact 12744554677](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40528900618/artifacts/12744554677), ZIP SHA-256:
`b170733e7775d6bfc0f2edffe510c7556d1f149f7d03d9c0c2a8cfb59be20324`.

테스트 ID와 전체 기계 판독 증거는 TEST_CASES.md, SECURITY_TEST_RESULTS.json에 보존했다. 초기 사전 검증 실패와 중간 27 PASS도 CI_EXECUTION_HISTORY.json에 별도 기록했다.

## 호환 범위와 남은 차단

- 등록된 합성 파일, 동일 스레드, 유한 timeout(0~2초), 기본 Windows FileLock만 검증했다.
- 동일 파일 경합·timeout, context 종료, 재진입, release, CRT 이전, preserve_lock_file 및 기본 삭제 시도를 검증했다.
- anchor를 유지하면 Windows sharing으로 unlink가 거부되고 실제 패키지가 오류를 억제하여 파일이 남는다. 이 경우 재사용과 identity 보존을 검증했다.
- 별도 사례에서는 실제 FileLock 소유 descriptor가 잠근 상태에서만 anchor를 퇴역시킨 후 release에 따른 실제 파일 삭제를 검증했다. 그 경로 세대는 영구 퇴역 처리하여 재개방을 차단한다. 삭제 후 자동 파일 재생성까지 호환한다고 주장하지 않는다.
- descriptor callback, 무한 대기, lifetime/cancel/stale recovery, owner PID 복구, async/RW/다중 스레드 등 나머지 패키지 모드는 이 단계에서 허용하지 않았다.
- unknown lock/unlock 결과를 주입한 합성 경로 2개는 재호출 금지 기록으로 격리된다. 이는 살아 있는 핸들·버퍼가 아니며 임의로 정상 상태로 덮지 않는다.
- trusted 검증 harness의 제한 경계다. 적대적인 Python reflection을 막는 OS 격리 보장을 하지 않는다.
- **전체 앱 NOT EXECUTED / NOT AUTHORIZED**. 현재 gate는 socket·process·SQLite 실행도 막으므로 이 검증기를 전체 앱 실행기로 사용할 수 없다. 로컬 Windows 11 전체 앱과 실제 OS DPI는 NOT VERIFIED다.

## 초기 CI 실패와 수정

첫 실행 40525860869는 native/Guard/테스트 실행 전에 borrowed contract_snapshot.json의 raw 해시 불일치로 중단됐다. 테스트 FAIL/ERROR 집계가 아니라 사전 검증 실패다.

원인은 Windows 체크아웃의 JSON LF→CRLF 변환이었다. 원본 LF SHA-256은 bcd4ed2e9ef123103d78b727f62542818fb2a210b45090a5dc945ce77cd694b8, CI CRLF SHA-256은 556fc14cfb483df3439444a9b836e21770bcf7b66be6b688316d952ba527aa40이다. 오프라인 줄바꿈 변환으로 동일 값을 확인했다.

이 메타데이터 JSON 하나는 CRLF→LF 정규화 후 검사하도록 수정했다. 모든 실행 코드의 byte SHA 검증은 유지했다. d1b5968의 CI 40526957854는 27 PASS였다. 최종 실행과 서로 합산하지 않는다.

## 보존과 다음 승인

PC에서는 소스 읽기·구문 검사·Git 작업만 수행했다. 운영 Guard SHA-256 d59add898d2e3d846932705a94354810a8a4a4fb394da5193b717949fc43a6d9와 native_boundary SHA-256 85738677846fbc86b0169d41854e616b94ef674849e3f7190d4c3452ede628fa가 기존값과 일치했다. 설치된 filelock의 18개 Python 파일 해시도 기존 기준과 모두 일치했다.

운영 앱·DB·ledger·키·OAuth·미디어·백업을 테스트 입력으로 사용하거나 변경하지 않았다. 운영 데이터의 새 전수 해시 검사를 수행한 것은 아니며 기존 보존 증거를 재사용한다. PR #35와 main을 변경하지 않았다. 기존 untracked validation/도 보존했다. 유료 API·SNS·전체 앱·DPI 실행은 없었다.

다음 단계에는 사용할 패키지 옵션·파일 세대 재등록·앱별 최소 파일/DB/localhost 경계를 정하고 검증 전용 앱 실행 절차를 별도 승인해야 한다. 이번 결과만으로 운영 Guard나 제품 진입점을 연결하지 않는다. 전체 앱 실행·운영 전환·DPI 변경은 수행하지 않고 여기서 종료한다.
