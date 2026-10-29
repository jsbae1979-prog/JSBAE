# BAT 신규 설치본 Start/Stop 집중 검증

- 최종 판정: **BLOCKED**. 최초 BAT 실행이 제품 앱 초기화 전에 패키지 경로 검사에서 거절됐다. 정상 실행/종료 성공으로 보고하지 않는다.
- 작업 브랜치: `codex/newsflow-bat-distribution-prep`
- 검증 기준 SHA: `1f8448a186f8670e10ec5c4734d11c907ede5634`. 이 보고서와 구현을 보존하는 커밋은 Git 이력을 참조한다.
- 확인일: 2026-10-29 KST. 일반 사용자(비상승) Windows 실행, 공식 CPython 3.14.7 AMD64 사용.
- 후보: `C:\Codex\NewsFlowAI-IsolatedReview\bat-startstop-validation-20261029\NewsFlowAI`
- 새 합성 데이터 경로: 위 후보의 형제 폴더 `SyntheticProfile`. 고정 테스트 주소 `127.0.0.1:18767`. 운영 8765 사용 안 함.

## 직접 차단 원인

기존 `lifecycle.inspect_layout`가 `zip_update.payload_name`의 프로그램 파일 경로 계약을 재사용한다. 새 후보 inventory에 넣은 `app/validation-launch.json`과 `README-VALIDATION.txt`는 기존 계약의 허용 경로가 아니다. 따라서 `nonprogram-or-unverified-sample-payload`로 거절된다. 새 실행기 설정과 기존 패키징 계약을 함께 검증하지 못한 구현 결함이다.

호출 순서: Start BAT → bundled Python `-I -B` → contract_entry.main → windows_live.dispatch → bootstrap/_profile → start → prepare_start → inspect_layout → payload_name 거절. `create_app`, 포트 예약, 세션 파일 생성 전 중단됐다. 합성 프로필에는 `synthetic-install.json`만 남았고 DB·인증 세션은 생성되지 않았다.

**실제 BAT 앱 실행 시도는 1회다.** 거절 후 허용 목록 변경, 경로 이동, 파일 위장, 재실행을 하지 않았다. 후속 검사는 같은 inventory의 거절 경로를 찾는 정적 함수 검사와 프로세스/포트 읽기만 수행했다. Windows 보안 설정은 변경하지 않았다.

## 실행·V3 관찰

- 공식 내장 Python은 실행됐다. 초기 `win32api` import의 DLL 검색 실패는 배포 폴더의 `pywin32_system32`를 `os.add_dll_directory`로 명시 등록해 해결했다. DLL 바이트·PATH·vendor .pth는 변경하지 않았다. 이 probe는 제품 앱을 실행하지 않았다.
- 이후 Python 3.14.7 및 win32api/win32security/win32process/win32event import probe 성공.
- V3 Service는 Running 상태였다. 이 시도에서 WinError 5나 V3 실행 거절은 관찰되지 않았다. 이는 제품 전체 앱에 대한 보안 제품 허용, 오탐 판정 또는 정상 기동을 증명하지 않는다.
- 실행 호스트가 보고한 종료 코드는 **1**이다. dispatcher 소스의 해당 예외 경로는 **2**를 반환한다. 호스트 코드와 BAT/native 코드를 혼동하지 않으며, 이번에는 native 종료 코드를 별도로 수집하지 못했다. 정상 Stop 코드 0은 **NOT VERIFIED**다.

## 이번 구현

1. `windows_live.py`: 별도 검증 후보에만 적용하는 합성 프로필 Start/Stop 어댑터. 운영 프로필 채택 금지, exact Python 3.14.7, 고정 포트, DLL 디렉터리 초기화, 환경 비밀값 미유입 처리.
2. 기존 LocalAccess/Origin/CSRF를 유지한다. 현재 사용자 SID·설치 ID·실행 파일 경로·프로세스 생성 시각·private nonce가 맞는 동일 query/synchronize 핸들에 대해서만 정상 종료를 요청한다. 강제 종료 API는 사용하지 않는다.
3. 유료 생성·게시의 변경 요청을 차단하고 기본값 저장만 허용하는 합성 전용 HTTP 경계. 예약 및 게시 캘린더의 자동 시작은 해당 앱 인스턴스에서만 비활성화한다.
4. `contract_entry.py`: 기존 후보는 비활성 상태 유지, 명시적으로 구성한 합성 검증 후보만 새 어댑터로 연결. 업데이트는 신뢰 정보 미확보로 계속 거절.
5. bundle_assembly controller 목록에 새 모듈 포함. Start/Stop BAT 실제 명령은 유지하고 안내 주석만 갱신했다.

이번 코드는 검증용 구현이며 **실행 인수가 완료된 배포본이 아니다**. 실제 Stop 프로세스 조회·종료 요청 경로와 앱 초기화 이후 자원 수명은 로컬 실행 성공 전까지 미검증이다.

## 집중 결과

| 항목 | 결과 | 근거/한계 |
|---|---|---|
| 신규 Start/Stop 단위 검사 | 11 PASS | 소유권 불일치·외부 요청·중복 Stop·운영 포트 거부 등 |
| 새 생성/게시 차단 경계 | 4 PASS | 해당 신규 테스트만 추가 실행; 기존 11개 재실행 안 함 |
| 공식 내장 Python 및 DLL 경로 초기화 | PASS | CPython 3.14.7/pywin32 probe, 제품 기동과 구분 |
| 신규 BAT Start | BLOCKED | inventory 경로 계약 거절, 실행 시도 1회 |
| 제품 create_app/고정 포트 바인딩 | NOT VERIFIED | 그 전에 중단 |
| 로컬 인증·React GUI·3개 제작실·TOP 3 | NOT VERIFIED (신규 후보) | 기존 격리 React 15 PASS만 재사용 |
| 정상 Stop/종료 0/재실행 설정 보존 | NOT VERIFIED | 앱을 시작하지 못해 수행 안 함 |
| 테스트 자원 | PASS | 18767 listener 0, 후보 Python 0, DB/세션 없음 |
| 기존 운영 프로세스 | 유지 확인 | 사전 확인 PID 4개가 계속 존재, 종료·재시작 명령 미사용 |

신규 단위 테스트 **15 PASS / 0 FAIL / 0 ERROR**. 실제 앱 실행 결과 **1 BLOCKED**. 두 결과를 합쳐 앱 인수 PASS로 보고하지 않는다. 테스트의 기존 Starlette/httpx 사용 중단 예고 경고 1종은 오류와 구분한다.

기존 15 PASS, BAT 78 PASS, 패키징 31 PASS, 기타 기존 설치·FFmpeg 증거를 재사용했으며 전체 회귀·샘플 재검사·디자인/V3 재진단은 실행하지 않았다.

## 보존 및 남은 조건

- 원본 169건 DB, 별도 운영 DB, WAL/SHM, 키·OAuth·DPAPI·미디어·백업 A/B를 후보에 연결하거나 읽거나 쓰지 않았다. 운영 8765에 접속하지 않았다. 새 후보에 기존 사용자 데이터는 없다.
- 기존 ZIP 2개·EXE 후보·기존 프로그램·운영 소스는 변경하지 않았다. 테스트/문서 변경만 지정 개발 브랜치에 보존한다. main·PR #35는 변경하지 않는다.
- 실제 유료 API, OAuth, SNS, 운영 전환, 사용자 데이터 이전, 외부 배포는 0회다.
- **남은 직접 조건:** 새 검증 설정/설명 파일의 정식 패키지 구조와 inventory 계약을 일치시키는 최소 수정 및 그 조합의 사전 검사. 기존 보안 거절을 우회하는 파일명 변경이나 광범위 허용으로 처리하지 않는다. 이번 시도의 거절 후에는 해당 보정과 앱 재실행을 수행하지 않았다.
- 그 후 BAT Start → 정상 로컬 인증/React → Stop 실제 exit 0 → 재실행 및 합성 설정 보존 검증이 필요하다. 새로운 V3/OS 실행 거절이 나오면 우회 없이 중단한다.
- 기존169 데이터 이전은 별도 호환성/복구 검증·승인 대상이다. 업데이트 신뢰 앵커·배포자 인증서 및 FFmpeg 대응 소스/샘플 권리의 외부 배포 조건도 그대로 남아 있다.

이번에는 실제 신규 설치본 사용 또는 운영 전환이 가능하다고 판정할 수 없다. 거절 확인 후 추가 앱 실행 없이 종료했다.
