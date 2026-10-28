# BAT 비공개 배포 전환 준비 및 실행 차단 보고

2026-10-28 (Asia/Seoul). **최종 판정: BLOCKED. 준비 자료만 완료했으며 BAT 실행본·배포 ZIP을 제작하거나 실행하지 않았다.**

## 1. 기준·작업 범위

- 시작 HEAD `66c80be58205a6c52e4428fc4fb9171fe9734f3f`.
- 준비 브랜치 `codex/newsflow-bat-distribution-prep`. 기존 `codex/newsflow-private-installer-updater` 및 설치/업데이트 후보를 그대로 보존한다. 기존 EXE 방식의 추가 구현은 중단한다.
- 이번 변경은 이 보고서·전환 계약·상태 JSON뿐이다. 제품/런타임/React/설치기/Guard 코드는 변경하지 않았다.
- 기존 V3 차단 분석은 반복하지 않았다. 근거는 [기존 V3 증거 보고서](../winerror5-analysis-20261028/V3_BLOCK_EVIDENCE_ADDENDUM.md)를 재사용했다.

## 2. BAT 실행본을 만들지 않은 이유

사용자가 확인한 V3 Lite의 동일 NewsFlowAI-Candidate.exe 실행 차단 6건과 기존 WinError5 증거가 존재한다. 차단 사실은 확인됐고 오탐 여부는 미확정이다. 이 상태에서 동일 앱을 BAT/Python으로 다시 포장해 다른 진입점으로 실행하여 차단을 피하는 작업은 수행하지 않는다. 이는 사용자에게 새 확인을 요구하는 자동 승인 심사 거절이 아니라, 이미 확인된 보안 차단을 우회하지 않기 위한 실행 범위 제한이다.

BAT 배포 방식 자체를 금지하거나 Python 공식 바이너리가 위험하다고 판단한 것은 아니다. 다만 포맷을 바꾼 것이 보안 판정을 해결했다는 근거가 될 수 없다. 안랩 공식 검토·정식 보안 정책 절차로 해당 앱의 실행 허용 여부가 정리된 뒤 허용된 실행 경로에서 기술 구현·검증을 진행해야 한다. 단순한 사용자 재승인이나 다른 위치/계정/환경에서의 우회 실행을 해결 조건으로 제시하지 않는다.

따라서 런처 BAT, 앱 코드가 담긴 새 ZIP, 내장 Python을 이용한 앱 실행은 이번에 제공하지 않았다. 작동하지 않는 BAT나 빈 ZIP을 완성품처럼 만들지도 않았다.

## 3. 실제 코드에서 확인한 전환 차이

| 항목 | 현재 코드/자료 | BAT 전환 시 필요한 범위 |
|---|---|---|
| 기존 내부 진입점 | `tools/distribution/app_entry.py`는 frozen 실행만 허용하고 `_MEIPASS` 자산 경로 사용 | 단순 확장자 변경·BAT에서 기존 EXE 대신 source 실행으로 대체했다고 완료 처리 불가. 정식 허용 후 별도 패키지 진입 계약 필요 |
| 기존 런타임 준비 | `tools/private_distribution/prepare_runtime.py`는 PyInstaller 빌드를 준비함 | 독립 설치 없이 사용하는 Python3.14.7 런타임 ZIP은 아직 확보·구성·검증하지 않음 |
| 현재 프로필 | `src/newsflow/distribution/windows_profile.py:distribution_profile`의 `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1` | 사용자 예시 경로로 임의 이전하지 않음. 기존 운영 경로 자동 채택도 금지. 명시적 호환/분리 정책 필요 |
| 포트 | `reserve_user_socket`은 `127.0.0.1:0`을 bind하여 실행마다 OS 할당, 8765 거부 | 요청된 “포트 사용 중이면 안내, 임의 다른 포트 이동 금지”와 그대로 같지 않음. 지정 포트 예약/충돌 안내 계약 필요 |
| 로컬 인증 | `local_access.py`의 bootstrap·세션 cookie·Host/Origin 보호 | 토큰을 BAT 인자/콘솔/로그에 출력하지 않고 재사용해야 함 |
| 종료 | `launch.py`의 SIGBREAK 및 서버 수명 정리 | 별도 Stop BAT가 소유 프로세스를 안전하게 식별하는 기능은 새로 검증 필요. PID 이름만으로 종료 금지 |
| 업데이트 검증 | `updates.py:validate_update`가 서명된 매니페스트·EXE Authenticode·파일명 .exe 계약을 요구 | .zip suffix만 허용하는 변경은 충분하지 않음. ZIP 전체 hash와 서명된 manifest 결속·전체 내용 검증 필요 |
| 현재 배포자 신뢰 | `publisher-trust.json`: `updatesEnabled:false`, certificate pin 빈 값 | 실제 신뢰 앵커 없으므로 ZIP 업데이트 역시 차단 유지. ZIP 안의 자체 제공 키/해시만 신뢰 금지 |
| 복구 | `offline.py`의 잠금·버전 순서·백업·journal·확정 실패 복구 | 원리와 기존 테스트 재사용 가능. 실제 ZIP 트랜잭션/새 payload 건강 확인은 미구현·미검증 |
| React/FFmpeg | 기존 정적 자산·소스 빌드·호환 검사 증거 존재 | 새 배포 ZIP에 포함하고 실행한 결과가 아님 |

이는 새 기능/보안 감사가 아니라 전환에 직접 관계된 파일만 읽은 결과다. 배포 프로필 경로가 현재 운영 프로필과 다르다는 기존 계약도 유지한다. 운영 경로 내용은 조회하지 않았다.

## 4. ZIP 및 실행·업데이트 결과

| 사용자 요청 항목 | 이번 결과 |
|---|---|
| `NewsFlowAI_v1.0.0.zip` | **NOT CREATED**, 경로/SHA-256 없음 |
| `NewsFlowAI_Update_v1.1.0.zip` | **NOT CREATED**, 경로/SHA-256 없음 |
| 압축 해제 / Start / 내장 Python 앱 실행 / React | NOT VERIFIED; 배포 ZIP 및 실행 경로 미구현 |
| 뉴스·이미지·캐릭터 제작 / FFmpeg | 새 경로 NOT VERIFIED; 과거 기능 증거만 보존 |
| Stop / 재실행 / 소유 프로세스 정리 | 새 경로 NOT VERIFIED; 앱을 실행하지 않았으므로 종료 성공으로 집계하지 않음 |
| 사용자 데이터 분리 / 인증 / 보존 | 기존 코드 계약 재사용 후보. BAT 경로의 실제 인수는 NOT VERIFIED |
| ZIP 업데이트 / 실패 복구 | 미구현·NOT VERIFIED. 신뢰 자료 부재로 실업데이트 BLOCKED |
| V3 활성 상태의 BAT 앱 실행 | **미실행/BLOCKED**, 기존 차단을 우회해 시험하지 않음 |
| 신규 PASS / FAIL / ERROR | 실행 테스트 **0 / 0 / 0**, 기능 성공을 새로 주장하지 않음 |

문서·JSON 형식과 변경 파일 범위만 점검한다. 이를 Windows 통합 테스트 PASS로 합산하지 않는다. CI45 PASS, 설치19 PASS, FFmpeg7 PASS와 이전 현장3 PASS/2 FAIL/0 ERROR는 이전 결과이며 이번에 재실행하지 않았다.

## 5. 샘플·라이선스

신규 샘플 매니페스트 `docs/artifacts/sample-replacement-candidates-v2-20261028/manifest.json`의 기존12개는 rightsVerified=true **0개**, false **12개**다. 이는 기존 플래그 조회이며 파일 hash/디코딩/권리 감사를 반복한 것이 아니다. 현재 자료로 외부 전달용 ZIP에 포함 가능한 샘플12개를 확보했다고 보고할 수 없다. 기존 원본·후보·사용자 복사본은 변경하지 않는다.

권리가 확인된 자산이 생기기 전 외부 전달 패키지에는 미확인 샘플을 제외해야 한다. 이를 빈 목록/샘플 없음 상태와 구분하고 실제 사용자 산출물을 가짜 기본 샘플로 채우지 않는다.

기존 source-built FFmpeg/FFprobe 및 대응 소스7개·recipe·고지 자료를 재사용한다. 이는 GPL/version3·libx264 포함 후보이며 BAT 전환이 재배포 의무를 없애지 않는다. 최종 대응 소스 완전성/제공 및 포함 자산의 배포 권리 미완료 상태를 유지한다. 법적 준수 완료·신규 LGPL 판정은 하지 않았다.

## 6. 기존 후보·운영 보호

아래는 기존 기록의 보관 정보다. 이번에 후보 바이너리를 다시 해시하거나 실행하지 않았다.

보관 폴더: `C:/Users/ching/.codex/visualizations/2026/10/16/01a14359-7240-7522-8c13-8bc085201d78/private-installer-updater-20261028/private-candidates/`

| 파일 | 기존 SHA-256 |
|---|---|
| NewsFlowAI_Setup_v1.0.0.exe | `46eb1254658c7498e3ac625bf5e4b023ed01517a496572c50812437ca5596b93` |
| NewsFlowAI_Update_v1.1.0.exe | `9f77700f7bddf1e347b00b45642330f9ac485c954014171ef694b2a992f8909e` |

두 후보는 기존 NotSigned 상태이며 삭제·교체·재빌드·전달하지 않았다. 운영 앱·포트8765·DB·키·OAuth·설정·미디어·백업에 접근하거나 변경하지 않았다. 기존 개발 Python 환경에 패키지 설치·제거도 하지 않았다. API/OAuth/SNS0, V3 설정/예외/ACL 변경0, 새 앱 실행0, 신규 사용자 배포0. 기존 미추적 `validation/`은 보존했다. PR35/main과 EXE 완료 브랜치는 변경하지 않는다.

## 7. 남은 조건과 종료

1. 기존 앱 차단에 대한 공식 검토/정식 실행 허용 절차. BAT로 바꿔 우회하는 방식은 제공하지 않음.
2. 허용된 패키지 진입점과 Python3.14.7 독립 런타임의 출처·의존성·라이선스·음성 자식 프로세스 계약 확인.
3. ZIP용 배포자 신뢰 앵커·서명된 매니페스트. SHA-256만으로 진위 증명 금지.
4. 승인된 실행 경로에서 지정 포트·소유 정상 종료·실제 ZIP 업데이트/복구·DB 보존 집중 검증.
5. 외부 전달에 필요한 샘플 사용권·FFmpeg 자료 인수. 실제 사용자 전달은 계속 별도 승인 대상.

설계 범위는 [BAT_DISTRIBUTION_CONTRACT.md](BAT_DISTRIBUTION_CONTRACT.md)에 정리했다. **배포 전환 완료나 새 설치 후보 완성으로 보고하지 않고 BLOCKED로 종료한다.** 실제 배포·운영 교체·PR 병합은 하지 않았다.
