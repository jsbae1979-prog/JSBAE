# 검증 전용 전체 앱 실행 정책 및 Windows CI 통합 준비

작성일: 2026-10-28 KST. **최종 판정: BLOCKED**.

## 기준과 실제 수행

- 저장소 jsbae1979-prog/JSBAE, 브랜치 codex/newsflow-core-studios-rebuild-20261027.
- 시작 HEAD cf2fdb4684cfab15419d64fbff7847ab86f2457d.
- Windows CI 실행 코드 545f09dab03c68c51c48515d75e6910638128e52.
- 기록/잔여 자원 집계 보완 및 자동 실행 동결 코드 a911be550ddd61f80a324d454728ef6a6550e325. 이 보완본은 구문 검사만 했으며 CI 재실행하지 않았다.
- [실제 Windows CI 40531809814](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40531809814), job 122286346398, Windows Server 2025 / Python 3.14.7.
- React 자산 빌드와 격리 의존성 설치는 CI step PASS. 보안/앱 검사는 Guard 거절로 종료했고 artifact 업로드도 파일 없음으로 실패했다. 빌드 성공을 앱 동작 성공으로 표시하지 않는다.

## 앱 초기화 정적 확인

src/newsflow/main.py:create_app(98~321)에서 make_engine/migrate, 합성 복구 트랜잭션, FileLock, 서비스 생성, static mount가 필요하다. src/newsflow/db/session.py는 WAL/foreign_keys와 Alembic 초기화를 사용한다. Settings의 explicit data_dir·port·secret_key로 기본 PC 경로와 session.key 읽기를 피할 수 있다.

main.py 166~170의 automatic_start=True 분기는 video_ai.start 대신 기존 recover를 사용한다. 175~176의 lifespan scheduler/calendar start는 이번 제한적 검사에서 진입하지 않도록 계획했다. 제품 함수를 patch하거나 import를 앞당기지 않았다. ThreadPoolExecutor 객체 생성과 실제 worker 실행은 구분하며, 제작/예약 worker 시작은 허용하지 않는다.

세부 권한은 EXECUTION_POLICY.md를 참조한다. 기존 Gate·capability의 검증용 사본에 source-pinned AppPolicy 등록 접점만 추가했다. 운영 Guard와 기존 네 폴더는 수정하지 않았다.

## 실제 차단과 증거 한계

확인된 로그는 검증 gate의 **read-outside-verification-roots** 거부다. 실행된 runner의 finally 무결성 검사(line 122)에서 검증 도구 소스를 다시 읽으려다 차단됐다. 이 후속 거부가 먼저 발생한 예외의 기록을 가렸고, 정상 JSON artifact는 생성되지 않았다. 따라서 최초 예외의 정확한 런타임 호출 위치와 자원 정리 완료를 인증하지 않는다.

정적 원인은 명확한 정책 교착이다. 기존 Guard의 read_roots에는 필요한 검증 도구 폴더가 있지만, 새 gate는 workspace·앱 src·Python prefix만 가진다. gate 설치 후 guard_capability/adapter/rtl_boundary/AppPolicy를 import해야 정책을 등록할 수 있는데, 그 검증 소스 읽기가 gate의 허용 범위 밖이다. 두 audit 경계는 동시에 적용되므로 앞쪽 Guard의 허용만으로 통과하지 않는다.

이번 거절을 ntdll/Rtl/FileLock의 새 제품 결함으로 분류하지 않는다. 추가 native 호출이 필요하다는 증거도 없다. 허용 목록 확대·사전 import·다른 진입점·간접 EXE·운영 앱 재사용을 하지 않았다. 같은 실패 경로도 반복 실행하지 않았다.

실패 기록이 가려지지 않도록 traceback 소스 재읽기 없이 frame metadata를 기록하고 무결성 읽기 거절을 별도 기록하는 코드를 준비했다. 잔여 자원이 있으면 최종 성공으로 처리하지 않도록 집계도 보완했다. **이 보완은 compile-only이며 검증됐다고 주장하지 않는다.** 자동 push 실행은 동결하고 workflow_dispatch만 남겼다. 수동 실행도 이번에 요청하지 않았다.

## 신규 결과와 기존 증거

| 항목 | 이번 결과 |
|---|---|
| Python 소스 구문 검사 | PASS — 코드 실행/보안 테스트가 아님 |
| React 자산 빌드 | CI step PASS — 자산 응답/GUI 실행 아님 |
| 신규 보안 테스트 9개 | NOT VERIFIED — 실행 결과 확보 못함 |
| 신규 집중 테스트 PASS | 0건 — 기존 결과 합산 없음 |
| Guard 경계 초기화 | BLOCKED 1건 |
| CI job | FAIL 1건 — 제품 테스트 assertion FAIL과 구분 |
| create_app / 앱 내 FileLock / SQLite | BLOCKED 또는 NOT VERIFIED |
| React 정적 응답·주요 읽기 API | NOT VERIFIED |
| native handle / CRT descriptor / buffer | 잔여 0 인증 불가 |
| 테스트 프로세스·합성 파일 정리 | 정상 정리 증거 없음; NOT CERTIFIED |
| Windows 11 로컬 GUI / OS DPI | NOT VERIFIED / 변경 없음 |

이전 FileLock 28, Guard·CRT 29, 통합 32, 네이티브 39, Windows 앱/API 7, 집중 CI 59, 합성 브라우저 42 PASS는 **이전 증거로만 재사용**했다. 현재 통합본 성공이나 신규 결과로 합산하지 않는다. 신규 제품 회귀 유무도 이번 앱 미검증 결과만으로 확정하지 않는다.

## 보존

운영 Guard SHA-256 d59add898d2e3d846932705a94354810a8a4a4fb394da5193b717949fc43a6d9, native_boundary SHA-256 85738677846fbc86b0169d41854e616b94ef674849e3f7190d4c3452ede628fa가 기존값과 일치한다. 설치된 filelock 18개 소스 파일도 기존 기준과 일치한다.

시작 HEAD 대비 src/frontend 및 기존 네 검증 도구 폴더의 Git diff는 비어 있다. PR #35는 Draft/open/미병합, HEAD 75626f74cc1bfe750d24132e44019bcda478247b를 유지한다. main과 운영 브랜치는 수정하지 않았다. 기존 untracked validation/도 보존했다.

운영 앱 제어·운영 DB/ledger/설정/키/OAuth/미디어/백업 접근·변경, 로컬 전체 앱, DPI 변경, 유료 API 및 SNS 호출을 수행하지 않았다. 운영 데이터의 실시간 byte 불변을 새로 전수 검사한 것은 아니다. 기존 보존 증거와 이번 미접근 범위를 구분한다.

## 남은 최소 승인 조건

새 native 권한이 아니라 **정책 등록 전 필요한 고정 검증 소스 파일의 읽기 권한**이 우선이다. 허용 후보는 source hash가 고정된 native_app_policy/{guard_capability.py,app_policy.py}, native_capability/adapter.py, native_rtl_filelock/rtl_boundary.py다. 필요 파일의 정확한 범위·SHA-256을 사전에 검토하고, 검증용 gate 사본에만 제한적 읽기 capability를 등록하는 방식에 별도 승인이 필요하다. 이번에는 적용하지 않았다.

그 후에도 Windows CI에서 신규 보안 경계와 create_app가 실제 통과해야 한다. 미검토 native 호출이 나오면 다시 중단해야 하며 자동 허용하지 않는다. Windows 11 로컬 GUI는 CI 결과와 별개의 정식 로컬 실행 승인·정책·합성 경로·포트/자원 종료 증거가 확보된 후에만 검토할 수 있다. 실제 OS DPI 변경 승인도 별개다.

이번 작업은 차단 상태와 구현·증거를 보존하고 종료한다. 운영 전환이나 추가 실행을 하지 않는다.
