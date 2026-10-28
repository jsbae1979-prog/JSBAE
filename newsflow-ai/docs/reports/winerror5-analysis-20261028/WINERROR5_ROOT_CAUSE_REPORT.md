# WinError 5 집중 진단 및 비공개 후보 재확인

2026-10-28. **최종 판정: BLOCKED.** 후속 사용자 증거로 V3 Lite 실행 차단 6건을 반영했다. 오탐 여부와 개별 WinError 5 요청·원본 차단 기록의 완전한 대응은 미확정이다. 제품 코드나 보안 정책을 추측으로 변경하지 않았다. Windows의 네이티브 CreateProcess가 기존과 동일한 EXE·경로·일반 토큰에서도 WinError 5를 반환했다.

## 0. 후속 V3 증거 반영

사용자가 V3 Lite의 Program Execution Notification/행위 기반/클라우드 평판 기반/상태5014 실행 차단6건(2026-10-28 19:53~20:56)을 직접 확인했다. 이를 근거로 **V3 실행 차단 사실 확인(사용자 제공 증거)**으로 갱신한다. 원본 개별 기록·전체 경로·SHA-256 대조 자료는 미첨부이므로 일대일 인과 대응과 오탐 여부를 확정하지 않는다. 이전 조사의 미확정 판단은 아래에 이력으로 남기고, 현재 판단은 [V3 증거 추가 보고서](V3_BLOCK_EVIDENCE_ADDENDUM.md)를 따른다. [안랩 분석 요청 준비](AHNLAB_ANALYSIS_REQUEST_PREPARATION.md)도 작성했으며 외부 제출·추가 실행은 하지 않았다.

## 1. 기준과 범위

- 브랜치 `codex/newsflow-private-installer-updater`, 시작 HEAD `eb1d115ccb0a0de77fcd51645305967f39492de9`.
- 기존 Windows CI 45 PASS, 설치/제거/재설치/보존 19 PASS, FFmpeg 7 PASS를 과거 증거로 재사용했다. 재실행 결과로 표시하지 않는다.
- 제품 UI·제작 엔진·API·DB schema·설치/업데이트 코드는 변경 0. 별도 진단 도구와 비민감 관찰 자료만 추가했다.
- 일반 사용자 수준 TokenElevation=0, Medium integrity(RID8192)에서 수행했다. 관리자 실행·예외 등록·전역 ACL/보안 완화는 없다.

## 2. 실패 파일·프로세스·단계

정확한 기존 합성 실패 경로를 같은 설치 파일로 복원했다.

`%TEMP%/nfpu-20261028/w3/Local/Programs/NewsFlowAI-Private/slots/1.0.0/NewsFlowAI-Candidate.exe`

이미지 SHA-256: `f3e24a91e7585089f95ac2e69063b1afb8e8a1e020c2786293d8bc66e0e955c4`.

| 호출 | 부모 PID | 자식 PID | 결과 |
|---|---:|---|---|
| 같은 경로 복원 Inno Setup | 77584 | 설치 도우미 실행 | exit 0, 비승격 |
| Python3.14.7, 기존 ApplicationName 자동 해석 | 94496 | 생성되지 않음 | PermissionError / WinError5 / errno13, 0.498초 |
| 같은 파일명을 ApplicationName으로 명시 | 59416 | 생성되지 않음 | 같은 WinError5, 0.515초 |

프로세스 생성 요청은 `NewsFlowAI-Candidate.exe --offline-runtime-check`였다. 이는 앱의 기존 읽기 전용 런타임 검사다. 두 경우 모두 shell을 쓰지 않았고 같은 경로/해시/일반 토큰을 유지했다. 경로 길이는 121자다. 실행 파일명 해석을 명시해도 해결되지 않았으므로 인자 처리 코드를 고치지 않았다.

기존 frozen launcher의 실패 호출은 `private_entry.main → subprocess.Popen`이다. 이전 진단 빌드의 줄 번호는 119이며, 이후 소스의 줄 번호와 혼동하지 않는다. 직접 Python에서도 같은 거부가 재현되어 frozen 부모에만 국한된 현상으로 볼 수 없다.

**직접 확정한 원인 경계:** Windows가 프로세스 생성 요청을 거부했다. **초기 조사 당시 미확정:** 거부 제품/정책. **후속 갱신:** 사용자가 동일 대상 EXE의 V3 실행 차단을 확인했다. 파일명과 시간대는 부합하므로 WinError 5와 강한 연관성이 있지만 V3 원본 경로/해시·개별 시각을 직접 대조한 것은 아니다. Defender/Guard 등 추가 원인 관여나 오탐 여부는 확정하지 않는다.

## 3. 파일·토큰·잠금·컨텍스트 대조

| 확인 | 관찰 |
|---|---|
| 파일/상위 경로 소유자 | 호출 사용자와 일치 |
| DACL | 현재 사용자·SYSTEM·Administrators full control, 앱/slots/data 루트 보호 ACL 유지 |
| 실제 파일 핸들 열기 | GENERIC_READ 및 GENERIC_EXECUTE 모두 성공. 이는 프로세스 생성 허용과는 다름 |
| 필수 무결성 레이블 | 명시적 추가 label ACE 없음 |
| 대표 진단 부모 | 비승격 Medium, AppContainer=false, restricted SID 0 |
| 대표 부모의 mitigation | ChildProcess/Signature/ImageLoad/DynamicCode flags 0 |
| 대표 부모의 Job | ActiveProcessLimit=0, LimitFlags=12288. Job을 변경하지 않음 |
| 파일 잠금 | 정확한 EXE 한 개만 Restart Manager에 등록해 조회, holder 0. Shutdown/Restart 호출 없음 |
| 스트림/IFEO | 기본 `$DATA`만 존재, Zone.Identifier 없음, 해당 EXE 이름의 IFEO key 없음 |
| 정적 PE | AMD64 `0x8664`, console subsystem3. 정적 import는 USER32/KERNEL32/ADVAPI32 |
| DLL 검색 경로 | 대표 일반 Python 부모에서 default |

토큰·mitigation 표본의 PID는 JSON에 각각 보존했다. 종료된 이전 frozen 부모의 토큰을 새로 조사했다고 주장하지 않는다. 파일 권한 검사 성공만으로 모든 Windows 실행 정책을 통과했다고 표시하지 않는다.

## 4. 초기 보안 기록 조사와 한계 (후속 사용자 증거는 §0 참조)

- CodeIntegrity/AppLocker/Defender 이벤트 채널은 조회 가능했다. 이전의 “조회 불가 또는 이벤트 없음”을 구분했다. 18:40 이후 질의는 **NoMatchingEventsFound**였다.
- 조회 시 최신 CodeIntegrity 이벤트는 18:13:04.315(id3089), AppLocker/Defender 최신 기록은 2025-01-25였다. 이 자료로 이번 거부 주체를 특정할 수 없다.
- 현재 읽은 AppLocker effective rule collection은 0, VerifiedAndReputablePolicyState는 0이었다. 모든 Windows 실행 정책이 없다는 뜻은 아니다.
- CiTool의 정책 목록 조회는 일반 권한에서 `0x80070005`로 거부됐다. 관리자 재실행이나 다른 경로로 보호 정보를 우회하지 않았다.
- Security Center에 AhnLab V3 Lite와 Windows Defender가 등록돼 있었다. 등록 상태만으로 실제 차단 주체를 판정하지 않는다.
- V3의 인증/설정/격리보관소는 읽지 않았다. 진단 로그에서 합성 앱 이름의 UTF8/UTF16 평문 일치 수와 포맷 메타데이터만 확인했으며 관련 차단 레코드는 확보하지 못했다. 원시 로그를 GitHub에 올리거나 복호화하지 않았다.
- Ahn*/ASD*/V3* Windows 이벤트 공급자는 조회되지 않았다. 초기에는 사용자의 보안 기록 확인도 어려웠다. 이후 사용자가 진단명·분류·검사 방법·5014·차단6건을 제공했으며 §0과 추가 보고서에 반영했다. 원본 개별 기록은 미첨부다.
- computer-use 스킬이 참조하는 guidance의 “Do not automate Windows security or anti-malware apps”에 따라 보안 제품 UI는 자동 조작하지 않았다. 파일/API에 의한 읽기 전용 조사는 수행했다.

따라서 “보안 제품 오탐이 확정됐다”거나 “서명만 하면 해결된다”고 보고하지 않는다. 도구 자동 승인 심사에서 작업이 거절됐다는 증거도 없다. 관찰한 거부는 Windows 호출의 반환값이다.

## 5. 앱 단계별 결과

| 범위 | 이번 결과 |
|---|---|
| 같은 실패 경로의 일반 권한 설치 | PASS, 기존 후보 그대로 exit0 |
| 앱 정상 시작 | FAIL, 두 명시 방식에서 동일 기존 결함 재현 |
| React GUI 로딩 | NOT VERIFIED: 앱 프로세스 미생성 |
| 앱의 DB/설정/로컬 인증 초기화 | NOT VERIFIED: 앱 코드 미진입. 설치기가 만든 합성 디렉터리와 구분 |
| 설치 폴더 쓰기 시도 | 앱 코드 실행 전 거부. 앱에 의한 쓰기 관찰 없음; 파일 권한을 원인으로 단정하지 않음 |
| FFmpeg/기타 앱 자식 | 앱 자식 PID 자체 없음. 기존 FFmpeg 7 PASS만 재사용 |
| 정상 앱 종료/재실행 | NOT VERIFIED: 시작되지 않은 앱의 종료를 PASS 처리하지 않음 |
| 테스트 설치 정리 | PASS: 정식 uninstaller exit0, 프로그램 폴더 제거, 합성 프로필 보존, force kill 없음 |

현장 확인 5건은 **3 PASS / 2 FAIL / 0 ERROR**로 분리했다. 두 FAIL은 서로 다른 새 결함이 아니라 **기존 WinError5 한 건의 두 재현 방식**이다. ACL/토큰 등 관찰값을 기능 테스트 PASS로 합산하지 않았다. 탐색 중 pywin32의 AccessCheck/GetBinaryType 메서드 미노출은 진단 API 가용성 한계이며 제품 회귀 ERROR로 숨겨 해결한 것이 아니다. 대신 실제 파일 핸들 권한과 정적 PE 정보를 조사했다.

## 6. 수정 파일과 diff

제품 원인을 확인하지 못했으므로 **제품 수정은 적용하지 않았다**. Python 제작 엔진, React, 설정 저장, DB migration, Guard·비용·게시 승인 정책은 그대로다.

추가: `tools/winerror5_diagnostics/inspect_execution.py`와 이 보고서/JSON 증거.

진단 도구는 기본 읽기 전용이며 TEMP 내 기존 합성 fixture, 소유자, 고정 EXE 경로, 기대 해시, 비승격 토큰을 확인한다. 명시적 `--create-process-once`를 줄 때만 동일 읽기 전용 검사 한 번을 요청한다. shell/다른 EXE/관리자 토큰/자동 재시도/자동 강제 종료 경로는 없다. 이번 도구 확인은 기본 inspect 모드로만 실행했고 이미 수집한 두 재현을 불필요하게 반복하지 않았다.

이번에는 전체 Python 회귀, 기존 CI45/설치19/FFmpeg7, 디자인·샘플 권리 감사와 바이너리 제작을 다시 수행하지 않았다. 제품 파일과 후보가 변하지 않았으므로 새 후보 빌드가 필요하지 않았다. skip/xfail 변경은 없다.

## 7. 설치·업데이트 후보

보관 경로: `C:/Users/ching/.codex/visualizations/2026/10/16/01a14359-7240-7522-8c13-8bc085201d78/private-installer-updater-20261028/private-candidates/`. 두 후보는 그대로 보존했으며 이번 작업에서 다시 제작하지 않았다.

| 파일 | 바이트 | SHA-256 | Authenticode |
|---|---:|---|---|
| `NewsFlowAI_Setup_v1.0.0.exe` | 118134171 | `46eb1254658c7498e3ac625bf5e4b023ed01517a496572c50812437ca5596b93` | NotSigned |
| `NewsFlowAI_Update_v1.1.0.exe` | 123583587 | `9f77700f7bddf1e347b00b45642330f9ac485c954014171ef694b2a992f8909e` | NotSigned |

업데이트의 무서명·변조 차단과 복구 구조는 기존 45/19 증거를 재사용한다. 이번에 실제 signed update/migration/업데이트 후 GUI 성공을 새로 확인한 것은 아니다. 실제 배포자 인증서가 없고 무서명 실행 차단을 유지한다. 후보를 사용자에게 전달하지 않는다.

## 8. 데이터·운영·Git 보호

- 실제 NewsFlow 운영 DB·키·OAuth·설정·미디어·백업을 테스트 입력으로 쓰지 않았다. 운영 앱·코드·포트8765를 변경하거나 재시작하지 않았다.
- 읽기 전용 8765 listener 조회는 0개였다. 임의 복구하지 않았다.
- 합성 w3의 기존 프로필은 보존했다. 복원한 프로그램은 정식 제거기로 정리했고 소유 테스트 프로세스 잔여는 0이다.
- 실제 유료 API·OAuth·SNS 호출 0, 외부 파일 전달 0, 보안 예외/ACL/OS 전역 설정 변경 0.
- 기존 미추적 `validation/`과 완료 브랜치를 보존했다. reset/clean/stash/force push는 없다.
- 원격 main은 `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`, PR35는 open/Draft/미병합, HEAD `75626f74cc1bfe750d24132e44019bcda478247b`로 읽기 전용 재확인했다. 두 대상 모두 변경하지 않았다. 새 PR은 만들지 않는다.

## 9. 외부 조건과 재개 조건

1. **갱신:** V3 실행 차단 사실은 사용자 확인 증거로 확보했다. 남은 조건은 6건 원본의 개별 시각·전체 경로·대상 해시와 기존 WinError 5의 대조, 그리고 안랩의 공식 오진/정상성·평판/정책 분석이다. 관리자 실행·보호 해제·예외 등록 없이 분석 요청 준비만 완료했다.
2. 실제 배포자 인증서와 Authenticode/RFC3161 서명 검증. 테스트 인증서를 정식으로 사용하지 않는다. 서명이 이번 WinError5를 해결한다고 단정하지 않는다.
3. FFmpeg 대응 소스 7개·빌드·고지 묶음은 기존 비공개 자료를 유지한다. 실제 제공 및 최종 라이선스 적합성 승인은 미완료다.
4. 샘플12개의 `rightsVerified:false`와 상업적 이용/재배포 권리 미완료 상태를 유지한다.
5. 신규 Windows11 표준 사용자/새 PC의 전체 설치·실행 인수는 NOT VERIFIED다. 현재 비승격 동일 계정의 합성 프로필 결과와 혼동하지 않는다.

V3 차단 증거가 추가됐지만 오진 여부나 공식 조치가 확정되지 않았으므로 앱 코드 변경·권한 확대·반복 실행을 할 근거로 사용하지 않는다. **BLOCKED를 유지하고 이 진단을 종료한다.** 운영 전환·사용자 전달·공개 배포·PR 병합은 수행하지 않았다.

## 공식 API 근거

- [Microsoft CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw): 호출 컨텍스트, 명시적 이미지명, 반환값과 프로세스 초기화의 구분.
- [Microsoft Restart Manager RmGetList](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist): 등록한 리소스 사용자의 조회이며 이번에는 종료 API를 쓰지 않았다.
