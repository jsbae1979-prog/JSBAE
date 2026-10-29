# 기존 운영 정리 및 비공개 BAT ZIP 마무리

**최종 판정: CONDITIONAL.** 최신 ZIP2개와 빈 사용자 프로필 초기화·로컬 저장·Start/Stop 경로를 준비하고 분리된 프로필에서 검증했다. 실제 다른 Windows 계정의 최초 실행/새 PC 설치, 배포자 인증서/신뢰 앵커와 라이선스 외부 전달 인수는 완료되지 않았다. 외부 사용자 전달0, 현재 운영본 변경/종료/재시작0이다.

## 1. 기준과 보호 결과

- 브랜치 `codex/newsflow-bat-distribution-prep`, 시작 SHA `91a53a0102849b9e877350a573bb37e2c45b8932`.
- 최종 ZIP 제어코드 SHA `8a1d6322a2dc3aa41311e76f6e37f05ee4ee84c8`. 최종 보고 Git SHA는 브랜치 HEAD로 확인한다.
- 현재 운영 `C:/NewsFlowAI`의 **PID23240 /127.0.0.1:18768** 그대로 유지. 프로그램2881파일과 layout 무변경, 실제 프로필36파일·47개 테이블 무변경, 기사169건 보존.
- 원본169/A/B **103파일** hash/size/mtime 동일. DB·WAL/SHM·DPAPI·OAuth·미디어·이력·복구 백업은 삭제/이전하지 않았다. 현재 잠긴 desktop.lock을 강제로 읽거나 잠금 해제하지 않았다.
- 별도 검증18780은 두 번 정상 Stop하고 최종 포트/세션 해제. 운영18768만 계속 실행 중.
- V3 Lite Service Running, 차단 미관찰. V3 UI 로그 전체를 새로 감사한 것은 아니다. 비활성화·예외·관리자 우회·차단된 EXE 실행0.

## 2. 정리 분류와 실제 삭제

| 분류 | 대상 | 처리 |
|---|---|---|
| KEEP | C:/NewsFlowAI, 실제v1 데이터, 원본169·A/B·암호문·미디어·현재 바로가기·Git소스 | 변경/삭제하지 않음 |
| REMOVE | 이전 pytest filter/profile/unit 합성 임시 폴더3개 | 아래50파일 삭제 |
| DEFER | 구형 run.bat 및 기존 프로그램 최소 복구 파일 | 프로그램 전체 삭제 승인 아님, 그대로 보존 |
| DEFER | 기존 EXE/ZIP 후보·공식 runtime/wheelhouse·FFmpeg 소스/라이선스·이전 복원 증거 | 재현/복구/권리 증거로 보존 |
| DEFER | 이번 포트 안내 보정 전 ZIP2개, 신규 분리 검증 설치/프로필 | 비교 증거로 별도 보존, 사용자 전달 안 함 |
| UNKNOWN | 명확한 합성 fixture로 증명되지 않은 다른 폴더/바로가기 | 광범위 조사·임의 삭제 안 함 |

삭제 공통 상위 경로:
`C:/Users/ching/.codex/visualizations/2026/10/16/01a14359-7240-7522-8c13-8bc085201d78/bat-private-package-candidates-20261028/`

| 실제 삭제 하위 폴더 | 파일 수 | bytes | 복구 필요 |
|---|---:|---:|---|
| filter-tests-01 |13|3,855|없음: demo wheel/합성 Python fixture, 소스·junit 유지 |
| profile-tests-01 |8|627|없음: 소형 가짜 DLL/PYD fixture, 원본 wheel 유지 |
| unit-tests-01 |29|18,708|없음: 단위 검사 생성 ZIP/wheel, 코드·결과 유지 |
| 합계 |**50**|**23,190**|운영·복구 자료0 |

절대 경로를 허용된 상위 경로와 정확히 비교하고 reparse/link·DB·암호문·세션·OAuth 자료가 없음을 확인했다. 각 파일 bytes/SHA-256을 기록한 뒤 삭제 직전에 다시 대조했다. PowerShell의 동일 경로 `Remove-Item -LiteralPath`로만 삭제했다. 파일별 전체 목록은 `CLEANUP_PLAN.json`, 실제 결과는 `CLEANUP_RESULT.json`이다. 구형 실행BAT·운영 프로그램·기존 ZIP은 삭제하지 않았다.

## 3. 최종 ZIP2개

공통 경로:
`C:/Codex/NewsFlowAI-IsolatedReview/bat-private-finish-20261029/packages/`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| NewsFlowAI_v1.0.0.zip |243,232,161|`a3fa66d0f08f0622cf993e1dbb9b1180130c60dcc205b357f8fdc884faadfbd4`|
| NewsFlowAI_Update_v1.1.0.zip |243,168,713|`0e19f694d2b8b88e66a052c186256160bc498b87e9560d25a7b03b414beb0419`|

각2884파일. 최초 ZIP은 NewsFlowAI/ 접두사, 업데이트 ZIP은 프로그램 상대 경로다. CRC와 모든 항목의 SHA-256/경로/파일 크기를 검사했고 기존 업데이트 ZIP 검증기로도 확인했다. SHA는 무결성 정보이며 배포자 진위 증거가 아니다.

공식 내장 CPython3.14.7 AMD64·고정 의존성27개·현재 운영본의 React/Python 제작 엔진·FFmpeg/FFprobe·라이선스/대응 소스 자료를 재사용했다. runtime/wheel 재다운로드·전체 패키징 감사·디자인 재검증은 하지 않았다. 운영 프로그램 inventory에 등록된 파일만 읽어 별도 staging으로 복사하고 변경된 제어코드·BAT 설명·README·layout/connection만 갱신했다. 현재 C:/NewsFlowAI에 그 코드를 쓰지 않았다.

DB·API키·OAuth·DPAPI·사용자 설정/미디어/백업·로그·세션·권리 미확인 샘플12개는 ZIP에 없다. 신뢰 앵커도 ZIP에 넣지 않았다. GitHub에는 코드·보고서·비민감 manifest/결과만 올리며 ZIP/DB/키/비공개 baseline을 올리지 않는다.

1.0.0과1.1.0 후보는 같은 최신 제품 코드에 릴리스 메타데이터만 다르다. 실제 기능 버전 간 업데이트 실행 증거로 표시하지 않는다.

## 4. 사용자별 최초 실행과 포트

기존 실제 복원 프로필용 모드를 그대로 전달하면 다른 사용자에게 실행되지 않으므로 **portable-local-operation** 경로를 별도로 추가했다.

- ZIP해제 → Start BAT → 내장Python `-I -B` → 현재 Windows 홈의 `AppData/Local/NewsFlowAI-BAT/portable-v1` 생성 → owner-only ACL/무작위 설치ID/프로그램 경로 marker → 로컬 인증 → 기본 브라우저 → React.
- 운영 데이터v1, 원본NewsFlowAI 및 기존launch.json은 채택하지 않는다. 임의 프로필/명령 입력이나 기존 다른 프로그램 경로 채택을 거절한다. 다른 폴더로 옮겨 같은 프로필을 조용히 재사용하지 않으므로 설치 위치를 유지해야 한다.
- `connection.json`은 schemaVersion/port/openBrowser만 허용하는 비밀값 없는 연결 파일이다. 기본 예시18780. 운영PC18768을 모든 PC에 강제하지 않는다. 사용자/관리자는 앱 정지 후 유효한 포트를 명시할 수 있고 충돌 시 안내 후 거절한다. 자동 변경/8765/LAN 바인딩 없음.
- 이 파일만 immutable program inventory hash 밖의 사용자 연결 설정으로 취급한다. ZIP 전송 무결성 manifest에는 포함한다. 경로 정책은 이 정확한 파일명 하나만 추가했고 임의JSON/DB/키 허용은 추가하지 않았다.
- Start/Stop 소유권·동일 프로세스 handle/생성ID/SID/설치ID·정상 종료 정책과 LocalAccess/CSRF/Origin을 재사용한다. 다른 계정/운영 프로세스 종료 권한은 추가하지 않았다.
- 현재 후보는 로컬 초안/설정 저장과 조회만 제공하고 실제 유료 생성/OAuth/SNS·예약 자동 시작은 차단한다. 사용자별 키 저장/실제 공급사 연결 성공을 검증했다고 주장하지 않는다.

## 5. 신규 집중 검증

**신규 단위 검사13 PASS**: 최초 실행/경로/명시 포트10, ZIP 연결파일/릴리스2, 실제 PortInUseError 안내 정규화1. 기존78/31/15/56/44 PASS 등은 재사용했고 새 실행 수로 합산하지 않았다.

| 새 실행 확인 | 결과 |
|---|---|
| 최초ZIP 안전 압축해제·파일 구조 | PASS:2884파일, 사용자 DB/샘플 없음 |
| 내장 Python·native DLL·의존성 | PASS:3.14.7/27개 dist-info, 실제create_app READY |
| 사용자 프로필·DB·로컬 인증 | PASS: 이전에 없던 별도portable-v1 생성, 원래v1 사용0 |
| React 홈·뉴스쇼츠·이미지·캐릭터 | PASS: 정상 bootstrap으로 IAB 실제DOM 확인 |
| 로컬 초안·기본값 저장 | PASS: 이미지 초안1개·기본값 저장, 생성 결과로 위장 안 함 |
| FFmpeg/FFprobe | PASS:ZIP내 바이너리로144×256/30fps/0.2초 무음 합성, 모두0 |
| 첫 Stop | PASS:Stop0, 앱0, nativeCipherRequests0 |
| 재실행·브라우저 자동 열기 | PASS:Edge accepted, 발급23.5초 내 정상 bootstrap 소비 확인 |
| 재실행 데이터·설정 | PASS: 초안1개·settings 전체 내용 hash 동일 |
| 두 번째 Stop·자원 | PASS:Stop0/앱0,18780 listener0/session0 |
| 중복 Start/충돌 | PASS: 같은 포트에서 거절, 자동 대체포트/강제 종료 없음 |
| 무서명 업데이트 | PASS:실제cmd 종료3, 업데이트 적용0 |
| V3 | 활성 서비스 유지, 이번 정상 실행 차단 미관찰 |
| 실제 다른 Windows 계정/신규PC | **NOT VERIFIED**: 같은 계정의 별도 빈 프로필 검증임 |
| 새 OS DPI/실제 유료 생성/OAuth/SNS | **NOT VERIFIED / 미실행** |

화면 증거는 비공개 테스트용 합성 데이터만 포함하며 로컬 `bat-private-finish-20261029-screenshots/`에 보존했다. 기존 사용자 데이터가 있는 운영 화면을 캡처하거나 올리지 않았다.

### 발견·보정·잔여 표시

1. 새 connection.json을 기존 payload 정책이 거절했다. 정확한 경로1개만 등록하고 추가 검사2건으로 보정했다.
2. 실제 포트 충돌은 안전하게 거절됐으나 내부 `PortInUseError` 이름만 표시했다. 사용자 안내와 기존 no-fallback 코드로 정규화했고 새 검사1건 통과. 현재 운영본에는 적용하지 않았다.
3. 샘플 제외 시 기존 UI가 범용 '기본 샘플을 읽지 못했습니다'와 빈 갤러리를 표시한다. 서버/API는 정상이고 내 작업을 차단하지 않는다. 예제 데이터를 넣거나 승인 디자인을 바꾸지 않았다. **잔여 MINOR: 의도된 샘플 제외 전용 안내 문구는 별도 보완 가능.**
4. 검증 도구가 충돌의 기존 내부 오류명을 예상 코드와 다르게 가정해 assertion1회가 났다. 실제 충돌은 거절됐고 검증본을 정상 Stop했다. 또 최초 보존 기준 수집에서 활성 desktop.lock 읽기 거절이 있어 잠긴 파일은 읽지 않고 SQLite RO/프로그램 inventory 기준으로 바꿨다. 강제 잠금 해제/보안 완화 없음. CLI 작업 디렉터리 오류와 도구 구문 오류는 정정했고 제품 결과로 합산하지 않았다.

**최종 미해결 제품 FAIL0/ERROR0**, 발견된 정책 경로·충돌 안내2건은 보정 완료. 위 도구 오류와 샘플 안내 제약을 숨기지 않는다. 전체 Python/보안/GUI/라이선스 감사를 반복하지 않았다.

## 6. 업데이트·권리·배포 조건

Update BAT는 실제 배포자 인증서/신뢰 앵커가 없어 종료3으로 거절한다. manifest는 unsigned이고 자동 활성화하지 않는다. 기존 버전/sequence·서명·ZIP hash·사용자 데이터 백업·실패 rollback·unknown 재시도 금지 계약/합성 증거를 재사용하며 이번 실제 업데이트/실패 복구를 새로 실행하지 않았다. 실제 updater 연결은 아직 비활성이다. 서명된 업데이트 활성화 전에는 사용자 지정 connection.json 포트 보존과 새 버전 프로그램 경로/프로필 marker 호환성도 집중 검증해야 한다. 인증서 확보만으로 이 연결 검증이 완료되는 것은 아니다.

Python/의존성/FFmpeg 고지와 기존 대응 소스·빌드 자료는 포함했으나 새로운 법률상 적합성 완료를 주장하지 않는다. 실제 Authenticode/배포자 인증서/신뢰 앵커, FFmpeg 대응 소스 제공의 최종 인수, 새 계정/새PC 검증은 외부 전달 전 조건으로 남는다. 권리 미확인 샘플12개는 제외했고 원본 권리상태는 변경하지 않았다.

비공개 ZIP 보존·검증 준비는 완료했다. **현재 운영본 교체·종료/재시작·기존 전체 프로그램 삭제·DB/키 삭제·실제API/SNS·외부 전달·무서명 업데이트·main/PR35 병합0.** 현재PC18768 운영본은 그대로 실행 중이고 검증본18780은 정지 상태다.
