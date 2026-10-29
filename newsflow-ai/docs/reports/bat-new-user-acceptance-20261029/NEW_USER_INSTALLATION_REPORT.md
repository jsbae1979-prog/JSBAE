# Windows 신규 사용자 설치 검증 및 비공개 배포 준비

**최종 판정: CONDITIONAL. 실제 다른 Windows 사용자 설치 판정은 NOT VERIFIED다.** 승인된 별도 Windows 사용자 계정·대화형 세션이 없어 계정 생성·자격증명 요청·관리자 실행·도구 관리용/시스템 계정 사용을 하지 않았다. 동일 계정의 분리 프로필 대체 검증은 PASS다. 외부 사용자 전달은 계속 보류한다.

## 1. 기준·환경·산출물

- 저장소 `jsbae1979-prog/JSBAE`, 브랜치 `codex/newsflow-bat-distribution-prep`, 시작 HEAD `a607b7d03d0c0c3f09bdca11db7bd8bf2c1bd298`.
- Windows11 Pro의 기존 로그인 사용자에서만 수행. 사용 가능한 승인 테스트 세션0. 다른 사용자 암호·토큰을 수집하지 않았다.
- 운영 `C:/NewsFlowAI`, PID23240,127.0.0.1:18768은 실행 상태 그대로다. CIM 조회의 빈 결과를 종료로 판단하지 않고 제한된 native query/synchronize handle로 PID 생존(exit259/STILL_ACTIVE)과 실제 포트를 확인했다. 종료 권한은 요청하지 않았다.
- 실제 현재 Windows 사용자 홈 아래 분리된 `AppData/Local/NewsFlowAI-BAT/portable-v1`, 검증 포트18780, 기존에 압축해제된 동일 후보만 한 차례 추가 실행했다. 실제 운영v1·원본169를 검증 앱에 연결하지 않았다.

재사용한 최초 ZIP:
`C:/Codex/NewsFlowAI-IsolatedReview/bat-private-finish-20261029/packages/NewsFlowAI_v1.0.0.zip`

- bytes243,232,161,2884파일.
- SHA-256 `a3fa66d0f08f0622cf993e1dbb9b1180130c60dcc205b357f8fdc884faadfbd4`.
- 패키지 제품/제어코드 SHA `8a1d6322a2dc3aa41311e76f6e37f05ee4ee84c8`.
- ZIP hash/CRC/전항목 검증은 직전 승인 증거를 재사용했다. 이번에는 파일 존재·크기와 검증 설치본의 동일 sourceSha를 확인했다. 새 ZIP 생성·전체 압축해제·패키징 재감사0.
- 새 Git 변경은 대체 경계 검사2건과 보고서뿐이다. 배포 ZIP 및 현재 운영 제품 bytes는 변경하지 않았다.

## 2. 신규 설치 항목별 결과

| 항목 | 상태 | 근거·범위 |
|---|---|---|
| ZIP해제 | PASS, 기존 증거 재사용 | 동일 최초ZIP2884파일 안전해제·CRC/항목hash 인수 |
| Start BAT | PASS, 이번 추가 실행 | 기존 분리 설치본18780 READY, 운영18768 불사용 |
| 내장Python3.14.7 | PASS | launcher가 정확한 bundled interpreter/version으로 초기화; 설정 화면3.14.7 표시 |
| 별도Python/Node/FFmpeg 설치 불필요 | PASS, 기존 구조/실행 증거 재사용 | 내장runtime·의존성27개·React dist·tools 바이너리. 사용자 설치/다운로드0 |
| 사용자 데이터·SQLite 최초 생성 | PASS, 기존 동일 계정 분리프로필 증거 재사용 | 최초 실행 전 없던portable-v1 생성. 실제 다른 Windows 계정 최초 생성은 NOT VERIFIED |
| 현재사용자 ACL | PASS, 이번 읽기 확인 | owner=currentSID, protected DACL, currentSID/SYSTEM/Administrators 이외 ACE 없음 |
| 실제 다른 사용자 NTFS/API 접근 거절 | NOT VERIFIED | 실제 다른 Windows 사용자 세션이 없음 |
| DPAPI/키 격리 | 구조·미유입 PASS / 실제 cross-account NOT VERIFIED | 검증프로필 .dpapi0/OAuth 연결0; 실제 복호화0. 기존28 PASS 및 다른 WindowsServer 계정 증거를 Windows11 새 결과로 승격하지 않음 |
| 기본 브라우저 자동 열기 | PASS, 기존 증거 재사용 | Edge accepted·발급23.5초 내 정상 일회용 인증 소비 |
| React 홈·뉴스/이미지/캐릭터 제작실 | PASS, 기존 GUI 증거 재사용 | 이번 홈 정상인증·저장된 합성초안 재조회도 확인 |
| TOP3/라이브러리/설정 | PASS, 이번 추가GUI | 아래 상세 참조 |
| 합성 초안·기본값 저장 | PASS, 기존 증거 재사용 | 외부API 없는 이미지 초안1개·기본값 저장. 이번에도 그 기록 유지. 중복 시험 레코드0 |
| FFmpeg 합성 | PASS, 기존 실행 증거 재사용 | ZIP내ffmpeg/ffprobe0,144×256·30fps·0.2초 무음MP4. 이번 재제작0 |
| 정상Stop·재실행/설정 보존 | PASS | 기존2주기·저장 보존 증거 재사용, 이번 추가 Start/Stop1주기 모두0 |
| V3활성 상태 | PASS | V3 Service Running, 이번 실행 차단 미관찰. 전체 보안 로그 재감사0 |

이 표의 같은 계정 별도 프로필 결과는 **실제 신규 Windows 계정 인수로 대체하지 않는다.** OS 계정 생성/전환, 관리자 권한, 보안 해제/예외 등록, 운영 데이터로 테스트한 사실이 없다.

## 3. 이번에 새로 확인한 항목

- 정상 one-time bootstrap을 통해 실제 IAB에서 인증된 React 홈을 확인했다. token/URL fragment/cookie를 보고서·로그에 출력하지 않았다.
- TOP3 뉴스 이미지 탭이 선택되고 빈 분석 상태·독립 결과3칸·비활성 제작 버튼이 표시됐다. 운영169건/실제TOP3/예시 뉴스를 끌어오지 않았다.
- 라이브러리가 이전 합성 이미지 초안1개를 '초안 저장/미리보기 파일 없음'으로 표시했다. 실제 생성 이미지로 위장하지 않았다.
- 샘플 콘텐츠 필터0개. 권리 미확인 샘플12개는 계속 ZIP에 없다.
- 설정 화면은 portable-v1 경로,Python3.14.7,API키 미설정,OAuth 계정 미등록을 표시했다. 운영 비밀값 유입/노출이 없었다.
- 현재 사용자 profile ACL은 읽기 전용으로 확인했다. 실제 다른SID 접근을 시험했다고 주장하지 않는다.
- 신규 **합성 단위 검사2 PASS**: foreign ownerSID marker와 foreign programRoot marker를 거절하고 DB/marker를 변경하지 않는다. Windows API/ACL을 mock한 이 검사는 실제NTFS/DPAPI cross-account 시험이 아니다.
- 검증본 Stop BAT0, 앱0, credentialBoundary nativeCipherRequests0, session삭제/18780해제. 테스트에서 잠시 보류한 자동브라우저 설정은 기존true bytes로 복원했다. 현재 운영 앱은 종료하지 않았다.

신규 제품 FAIL0/ERROR0. 기존13 PASS·최초설치/FFmpeg/자동열기/재실행을 신규 실행 횟수로 합산하지 않았다. 전체Python회귀·Guard감사·디자인·샘플 원본 검사·패키징 반복0. 제품 수정0, 테스트2건만 추가했다. 실제 다른 계정 미확보는 제품 실패가 아니라 미검증 조건이다.

화면은 로컬 `bat-new-user-acceptance-20261029-screenshots/`에 보존했다. 포함 데이터는 별도 프로필의 합성 초안뿐이다. 운영 화면·키·OAuth 자료를 캡처하거나Git에 올리지 않았다.

## 4. 운영본·원본·백업 보존

| 대상 | 이번 결과 |
|---|---|
| 운영PID23240 | native 조회STILL_ACTIVE, 전후동일 |
| 운영18768 | 계속수신; 운영앱 Start/Stop/재시작0 |
| 운영layout | SHA동일; 제품코드/React/환경 설정 변경0 |
| 실제DB |47테이블 전후내용hash·건수 동일, integrity=ok, 뉴스169 |
| 설정·암호문·미디어 등 |36파일hash 동일, 실제키 복호화0 |
| 원본169/A/B DB3개 | 모두 기존 SHA `238d0aea41bc1377a29b9a1eb4b30f43e9d38ad39bba22e8a2fe31d7e6726287` 일치 |
| 기타 A/B 파일 | 기존103파일 보존 증거 재사용; 이번 직접 변경0 |
| 검증18780 |정상Stop 후 수신0/소유session0 |
| 프로그램·기존데이터 삭제 |0. 이번 생성한 중복 junitXML만 동일 보존본과hash 대조 후 정리 |
| main/PR35 |변경/병합0 |

## 5. 오프라인 업데이트·서명

업데이트 ZIP은 기존 그대로다:
`C:/Codex/NewsFlowAI-IsolatedReview/bat-private-finish-20261029/packages/NewsFlowAI_Update_v1.1.0.zip`

SHA-256 `0e19f694d2b8b88e66a052c186256160bc498b87e9560d25a7b03b414beb0419`.

| 준비 항목 | 상태 |
|---|---|
| 버전·supportedFrom·sequence·파일/ZIP 무결성 | 기존 계약/합성증거 재사용 |
| 배포자 서명·독립 신뢰앵커 | 미확보, 업데이트 비활성 |
| 사용자 DB·미디어 백업/실패복원 | 기존 snapshot/rollback 계약·인수 증거 재사용 |
| 다운그레이드/unknown 자동재시도 | 기존 차단 유지 |
| 실제 signed updater 연결 | 미완료: 인증서뿐 아니라 연결 어댑터/health/사용자 지정포트 보존·프로그램경로/marker 호환성 검증 필요 |
| 이번 실제 업데이트 | 실행0, 인증서 발급·구매0, 무서명 허용0 |

서명되지 않은 ZIP의 SHA만으로 배포자 진위를 확인했다고 판정하지 않는다. 실제 인증서 저장소 전체 수집이나 개인 인증서 취득은 하지 않았다.

## 6. FFmpeg·샘플 및 최종 배포 판정

기존FFmpeg바이너리·라이선스 고지·대응소스/빌드 자료를 ZIP에 포함한 증거를 재사용했다. 대응 소스 제공 체계와 재배포 적합성 최종 인수는 미완료 상태를 유지하며, 이번에 새로운 법률 검토나 완료 판정을 하지 않았다.

권리 미확인 샘플12개는 ZIP에서 제외돼 있다. 원본 권리상태를 true로 변경하거나 샘플을 대체하지 않았다. 실제유료API/OAuth/SNS0.

**비공개 사용자 전달 가능 여부: 아직 보류.** 남은 조건은 승인된 실제 Windows11 별도 사용자/새PC 환경에서의 설치·cross-account NTFS/API/DPAPI·포트 동시 사용 인수, 배포용 서명·신뢰앵커 및 실제업데이트 연결 인수, 라이선스 외부전달 최종확인이다. 계정이 없는 상태에서 시스템 계정을 사용하거나 관리자 권한으로 계정을 만들지 않는다.

이번 범위의 대체 검증과 결과 보존은 완료했다. 실제 외부 전달·운영 앱 교체/종료/재시작·데이터 이전/삭제·유료API/SNS·무서명업데이트·PR병합을 진행하지 않는다.
