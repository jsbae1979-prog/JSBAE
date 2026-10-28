# BAT 실행 인수·기존 운영 전환 준비 보고

2026-10-29 KST. **최종 판정: CONDITIONAL — 준비 조사 완료, 실제 운영 전환은 BLOCKED.** 실행·종료·삭제·업데이트는 수행하지 않았다.

## 1. 기준과 현재 운영 상태

- 개발 브랜치 `codex/newsflow-bat-distribution-prep`, 조사 기준/원격 HEAD `eab156829453fdd6ec865cc2fcfc32ef6c9b4066`.
- 기존 운영 체크아웃은 `codex/newsflow-local-d4dc20f`, Git HEAD `027644730c04b6b977baa9c4ede3eeb56115e61b`. 기존 로컬 변경/미추적 항목 250개를 보존하며 정리 대상으로 확정하지 않는다.
- 2026-10-27의 기존 운영 적용 증거는 제품 `08bfec12f71fbe10b2bf2b7df4a2b8efd4283ba8`의 173개 소스 hash 일치를 기록한다. 당시 Git ref는 별도로 보존됐다. **역사적 적용 증거이며 현재 전체 소스 재감사·현재 실행 중 제품 SHA 확정이 아니다.**
- 이번 조회 시점의 운영 포트8765는 LISTEN 없음, 지정한 Python/NewsFlow 프로세스 이름 조회 결과도 없음. Win32_Process의 이름/PID/부모PID/실행파일 경로 속성만 사용했고 명령행·환경변수·메모리는 읽지 않았다. 운영 앱을 시작·종료하지 않았다. 첫 제한된 CIM 조회 실패는 정식 읽기 조회로 해소했으며 앱 실행 오류로 집계하지 않는다.
- 기존 `run.bat`는 `.venv/Scripts/python.exe`를 우선해 `tools/windows_launcher.py` → `newsflow.main`으로 연결된다. 프로젝트 pyvenv.cfg는 Python3.14.7, 시스템 site-packages 비활성이다. 구형 launcher에는 Python3.12 fallback도 있지만 이번 작업에서 실행하지 않았으며 배포 런타임은3.14.7 단일 기준이다.
- 운영 기본 데이터는 `%LOCALAPPDATA%/NewsFlowAI`. 새 후보 계약은 `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1`; 새 프로필은 아직 없고 이번에 만들지 않았다.

## 2. 데이터·인증·예약·백업 보존

- SQLite DB/WAL/SHM, 뉴스·대본·프로젝트·분석, outputs/tts/trash/media, 로컬 백업과 별도 운영 백업을 KEEP한다. 휴지 보관된 영상도 삭제 후보가 아니다.
- DB는 WAL0 및 비-reparse 확인 후 `mode=ro&immutable=1`, `query_only`로 허용 테이블의 **수량만** 조회했다. 앱/ORM/migration을 호출하지 않았다. DB/WAL/SHM의 크기·mtime은 전후 동일하다. 본문·제목·출처 URL·설정 값·계정·토큰·ledger 내역은 출력/저장하지 않았다. 개인 수량·절대 경로 증거는 로컬 별도 자료에만 보관한다.
- 현재 base DB의 제작예약/실행기록/게시예약 테이블은0건이고 `NewsFlow*` Windows 예약작업도 조회0건이다. 다른 이름의 작업이나 과거 설정 기반 예약까지 없다고 확장하지 않는다. 스케줄러를 실행하지 않았다.
- DPAPI 파일5개 및 로컬 session.key의 **위치·크기·권한 속성만** 확인했다. 키 값·OAuth 토큰·DPAPI 내용/복호화/파일 hash는 읽지 않았다. 파일 존재를 실제 공급사 인증 성공으로 판단하지 않는다. 별도 OpenAI 키·OAuth 활성 토큰 저장 위치/상태는 NOT VERIFIED이다.
- 프로필/DB/인증파일8개 대상의 ACL은 상속 상태이며 현재 사용자/System/Administrators 외의 상속 항목도 있다. **다른 사용자 접근 차단을 PASS로 확정할 수 없다.** 실제 effective access·계정 관계 검증은 NOT VERIFIED이며 이번 범위에서 ACL을 수정하지 않았다. 기존 CI 격리 PASS를 이 운영 폴더 ACL의 결과로 대체하지 않는다.
- 운영 프로젝트의 backups, 별도 NewsFlowAI-backups, IsolatedReview 운영 백업의 backup-B/관련 증거를 보존한다. 백업 A/B의 내용·복구 무결성은 기존 증거를 재사용하며 이번에 원본을 열거나 다시 복원하지 않았다. 보호 파일을 전부 재해시하지 않았으므로 현재 전체 바이트 무변경을 새 감사로 주장하지 않는다. 보존 근거는 무쓰기 작업 범위와 DB 메타데이터 대조다.

## 3. 보존·교체·제거 후보 분류

| 대상 | 분류 | 실행 조건/보호 |
|---|---|---|
| 기존 운영 소스·run.bat·.venv | KEEP | 신규 운영본 실행/데이터 보존/복구 인수 전 보존. 전체 repo 삭제 금지 |
| 기존 실행 진입점·프로그램 코드 | REPLACE (미래 조건부) | 현재 교체0; 새 운영본 인수와 별도 운영 전환 승인 후 프로그램 파일만 대상 |
| 사용자 DB·ledger·키·OAuth·DPAPI·설정·미디어·trash·백업 A/B | KEEP | 제거 후보 제외; SID가 다른 계정으로 DPAPI 암호문 자동 이전 금지 |
| 기존 EXE Setup/Update 후보·최종 BAT ZIP2개·원본 wheel/생성 증거 | KEEP | 추가 EXE 개발/실행·재압축·교체·삭제0 |
| 이번 패키징의 미완료 packages 및 SUPERSEDED packages-final | REMOVE CANDIDATE | 비운영 중간 산출물에 한정; 최종 후보/증거 확보 및 별도 삭제 승인 후에만 지정 경로 정리 |
| 구형 Python312 테스트 도구·validation-temp/output·기존 integration candidate | UNKNOWN | 공유 의존성·소유권·사용자 데이터 포함 여부 미확정. 폴더 일괄 삭제 금지 |
| IsolatedReview/운영 백업 루트·기존 dirty/untracked 파일 전체 | KEEP / UNKNOWN | 백업/개인 미디어/미완료 개발 혼재 가능. 전체 루트를 삭제 후보로 삼지 않음 |

안전한 제거 절차는 ① 실제 새 실행/데이터·복구 인수 ② 제거 범위와 소유권·보존 목록 대조 ③ 필요한 백업의 복구 가능성 확인 ④ 정확한 경로/파일 목록으로 별도 승인 ⑤ 해당 목록만 제거다. 현재는 어떤 단계의 실제 삭제도 시작하지 않았다.

## 4. 기존 ZIP 상태와 최신 코드 차이

| 기존 파일 | bytes | SHA-256 | 확인 결과 |
|---|---:|---|---|
| NewsFlowAI_v1.0.0.zip | 232213326 | `0228c117409c94b2d70ce0957633a8457f156e017b1a90fef422e7e980ef93d2` | 기존 hash 일치, 2874파일 |
| NewsFlowAI_Update_v1.1.0.zip | 232150098 | `18b5369709d7bc6c506becac8b72087746d5d6460a6b8e390013c5aa9661a765` | 기존 hash 일치, 2874파일 |

동일한 packages-browser 후보를 그대로 사용한다. 이번에는 요청된 ZIP SHA-256과 중앙 디렉터리의 구성 존재만 확인했고 전체 CRC/member hash·wheel·패키징 테스트를 재실행하거나 ZIP을 재생성하지 않았다. runtime/product/site-packages/React/FFmpeg/FFprobe/라이선스 포함 증거는 기존 보고서와 index로 확인했다.

후보 조립 기준 `3b3598f4f6a0b9d3c04e92bb75efae026216fdc2`와 현재 `eab1568` 사이 제품 src/React diff는0이며 이후는 보고 자료다. 따라서 **현재 개발 제품 코드·React와 ZIP 후보의 알려진 소스 차이0**이다. 두 후보의 제품은 동일하고1.0.0/1.1.0 metadata·README만 다르므로 실제 서로 다른 제품 버전 업데이트 성공을 의미하지 않는다. 운영 적용본은 위 역사적08bfec1 증거와 별개이며 ZIP을 운영에 적용하지 않았다.

권리 미확인 샘플12개는 ZIP에서 제외된 상태다. 기존 샘플/사용자 복사본은 보존했다. FFmpeg 소스7개·recipe·고지는 포함하되 실제 제공 조건/최종 라이선스 clearance를 이번에 재감사하거나 배포 승인하지 않았다.

## 5. 실행·업데이트를 막는 조건과 한 번의 향후 인수 준비

- **실행 BLOCKED:** Start/Stop dispatcher는 계속 거절(exit2)하며 live 프로세스/정상 종료 어댑터 미연결이다. 내장 Python의 실제 DLL/COM/import·앱·GUI 실행은 NOT VERIFIED이다. 기존 V3 차단 사실을 BAT/Python 진입점으로 재실행해 회피하지 않았다. OS/보안 제품의 정상 실행 허용 조건 확인과 별도 실제 실행 승인이 먼저다. AhnLab 공식 접수를 요구하거나 진단을 반복하지 않는다.
- **업데이트 BLOCKED:** 실제 배포자 인증서/외부 신뢰 앵커/서명이 없다. Update 거절(exit3), SHA-256만으로 배포자 신뢰 인정0. 실제 업데이트/backup/restore/migration 실행0이다.
- **운영 전환 BLOCKED:** 별도 합성 실행 인수, 새 프로필 데이터 분리, 기존 자료 보존/복구·권한 확인, 별도 운영 전환 승인이 남았다. 운영 포트8765가 비어 있어도 테스트용으로 사용하지 않는다.

허용 조건 확보 후 별도 검증에서 한 번에 진행할 묶음: 내장 Python → 앱 import → 새 합성 프로필의 로컬 인증 → 명시한 고정 loopback 테스트 포트(8765 금지, 충돌 시 중단/자동 변경 금지) → React GUI → Fake 뉴스 쇼츠·Instagram 피드 이미지·캐릭터 쇼츠 → 로컬 FFmpeg 합성 → 소유 테스트 프로세스의 정상 종료·재실행 → 저장/재조회·실패/결과 불명 및 보존·복구 확인. 이는 **실행 계획이며 이번 실행 결과가 아니다.** 실제 유료 API/SNS는 포함하지 않는다.

## 6. 신규 확인·기존 증거·종료

| 이번 확인 | 결과 |
|---|---|
| ZIP2개 기존 SHA-256 일치·구성 목차 | PASS (읽기 전용 비교) |
| 후보 기준 대비 최신 제품/React 변경 | PASS: 0 |
| DB 읽기 전용 수량 조회 및 DB/WAL/SHM size·mtime | PASS: 동일 |
| 운영 프로세스/8765 | 조회 시 수신/지정 앱 프로세스0; 정상 종료·실행 PASS로 집계하지 않음 |
| 운영 ACL의 사용자 간 실효 격리 | NOT VERIFIED: 추가 상속 항목 존재 |
| BAT/내장 Python/제작/GUI/FFmpeg/재실행 | NOT VERIFIED / 미실행 |
| 실제 서명 업데이트·운영 전환 | BLOCKED |

새 단위/회귀 테스트0, 신규 앱 실행0, 신규 테스트 FAIL/ERROR 없음(미실행). 기존78 PASS·31 PASS·30 PASS·산출물16 PASS만 재사용하고 신규 결과로 합산하지 않는다. CI/설치/FFmpeg 기존 증거도 과거 자료다.

GitHub main `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`, PR35 head `75626f74cc1bfe750d24132e44019bcda478247b`, open/Draft/미병합을 읽기 전용으로 확인했다. 이번 변경은 준비 보고/비민감 증거만 지정 개발 브랜치에 보존한다. 제품·BAT·운영 코드/프로세스/포트/키/DB/미디어/백업/EXE/ZIP·V3·ACL 변경0, 실제 API/OAuth/SNS·외부 사용자 배포0이다. 운영 파일의 내용·절대 경로·개인 자료는 GitHub에 올리지 않는다.

**준비 결과 CONDITIONAL, 실제 운영 전환 BLOCKED.** 추가 실행·정리 없이 종료한다.
