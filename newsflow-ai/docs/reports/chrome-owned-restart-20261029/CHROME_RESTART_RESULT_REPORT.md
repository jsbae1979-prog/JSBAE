# 승인된 운영 Stop·Start1회와 Chrome 인증 결과

**최종 판정: BLOCKED — 앱의 정상 재시작·데이터 보존은 확인됐지만 Chrome 인증과 세 제작실 GUI 확인은 완료하지 못했다.** 승인된 정상 Stop1회·Start1회만 수행했다. 추가 재시작·인증 우회·유료 API·SNS 호출은 하지 않았다.

## 1. 실행 결과

| 항목 | 결과 |
|---|---|
| 기준 브랜치/시작 HEAD | codex/newsflow-bat-distribution-prep /f28cb377ec08231a57842269c04d7d01b9c948ec |
| 기존 운영 프로세스 | PID23240,소유 세션 정상 Stop |
| Stop BAT/기존 앱 종료 | 0 /0 |
| 신규 Start | 동일C:/NewsFlowAI·동일v1 프로필·동일18768,READY |
| 현재 프로세스 | **PID3588,18768에서 실행 중** |
| 재시작 횟수 | Stop1회/Start1회,추가0 |
| Chrome 정상 인증 | FAIL:첫 연결 페이지에서 인증 경계 거절 |
| 뉴스·이미지·캐릭터 GUI | NOT VERIFIED |

Start는 현재 실행 중이므로 '최종 종료코드0'이라고 표시하지 않는다. READY와 native query/synchronize handle의 STILL_ACTIVE,실제18768 수신을 확인했다. 구형 프로그램이나 다른 사용자 프로세스를 종료하지 않았다.

## 2. 백업·설정·데이터 보호

Stop 전에는47개 테이블의 내용hash·건수와26개 인증 암호문/미디어의hash·size·mtime을 기록했다. launch.json/layout.json의 원본bytes/SHA와 owner/group/DACL도 비공개 보존했다.

정상 Stop 후,잠금과포트가해제된 신규 프로필을 기존 offline.snapshot으로 일관성 있게 백업했다. **36파일**을 별도 사용자 전용 경로에 저장했고,또 다른 복원 검증 경로에서 기존 restore로 복원했다. 파일index·SHA와47개 테이블의 내용이 원본과 일치했고 SQLite integrity=ok였다. 원본169/A/B를 복원 대상으로 사용하지 않았다.

비공개 보존 경로:
`C:/Codex/NewsFlowAI-IsolatedReview/chrome-owned-restart-20261029/`

- `settings-before/`:전환 전launch/layout
- `stopped-profile-backup/`:정지 상태 프로필 백업
- `restore-verification/`:별도 복원 검증본
- ACL·테이블·암호문/미디어 baseline은 private 자료이며 Git에 넣지 않는다.

이번 시작에서 Edge가 먼저 인증을 소비하지 않도록 openBrowser=false와 해당 layout hash binding만 일시 적용했다. 현재는 **원본bytes·SHA·ACL로 두 파일을 모두 복원**했다. openBrowser=true와 기존외부실행/자동화/복호화 차단이 유지된다. 이 설정 복원이 현재 앱의 인증을 재발급하거나 Edge를 즉시 여는 것은 아니다.

복원한 설정SHA-256:

- launch.json: `8aac22b0a56d37354280168595b674282182425de60db432bb4ce56c9b52b1fd`
- layout.json: `f90b5a0207cb4af92b2b4c37c570d160c53b7bca5dd5231b3b550a218facf011`

## 3. Chrome의 실제 관찰

기존 사용자 Chrome 탭을 준비하고,새 PID의 bootstrap 파일이 이번 Start 후 생성됐고110초 기준 내에 있음을 검사했다. 그 **새 인증 URL로 한 번만** Chrome을 탐색했다. 정상 연결 완료 후 React로 이동하지 않았고,관찰 결과는 다음과 같다.

- 경로는 `/__local/connect`였고 URL fragment가 남아 있었다.
- 페이지 본문은 `Local Windows session authentication required.`였다.
- 정상 CONNECT 페이지의 JavaScript 처리·React 이동이 확인되지 않았다.
- 같은 앱의 **토큰 없는** 정식`GET /__local/connect`를 브라우저 외 읽기 클라이언트에서1회 확인했을 때는200과 정상 연결HTML을 받았다.

따라서 앱/포트/정식 연결 endpoint는 준비돼 있으나 Chrome 연결 요청이 LocalAccess 경계에서 거절됐다는 사실까지 확인했다. **Host/Origin/Fetch-Site/중복 헤더 등 어떤 세부 조건이 실패했는지는 현재 증거로 확정하지 않는다.** 브라우저 출처 문제라고 추측해 허용목록을 넓히지 않았다.

최초 전달 전 유효기간 검사는 통과했다. 이후 진단에서 파일 생성 후160.7초 경과를 확인했다. 처음부터 토큰이 만료돼 실패했다고 단정하지 않는다. 만료 후 토큰을 서버에 다시 보내는 시험은 하지 않았다.

Chrome의 현재 주소는 fragment 없는 `/studio/dashboard`로 정리했으며 인증 요구 상태다. 이 정리 탐색은 토큰을 전송하지 않는다. 쿠키 복사,Edge 세션 이동,Origin/CSRF/CSP 완화,추가 bootstrap 발급,두 번째 Stop/Start는0이다.

## 4. 진단 중 출력 사고

Chrome 결과를 관찰하면서 브라우저 제목을 출력했고,거절 페이지의 제목에 일회용 인증값이 포함돼 있어 **도구 출력에1회 나타나는 실수**가 있었다. 성공 여부를 확인하기 위해 title을 출력한 것이며,이를 정상 처리나 무노출로 보고하지 않는다.

해당 값은120초 유효기간이 지난 것을 메타데이터로 확인했고 재사용하지 않았다. 현재 주소에서fragment를 제거하고 관련 임시 변수를 정리했다. 실제값·전체인증URL은 보고서·Git·스크린샷에 넣지 않았다. 이미 생긴 도구 출력이 삭제됐다고 주장하지 않는다. API키·쿠키·DPAPI평문은 출력하지 않았다.

이후 상태 캡처는 fragment가 제거된 화면만 사용했다. 로컬 증거:
`chrome-owned-restart-20261029/chrome-after-restart.png`

## 5. 보존 대조 결과

| 대상 | 재시작 전후 결과 |
|---|---|
| SQLite | integrity=ok,47개 테이블의 내용hash·건수 모두 동일 |
| 기사/AI처리/대본/영상/이미지게시물 | 기존169/48/6/7/3건 보존 |
| DPAPI 암호문6개+미디어20개 | 26파일hash·size·mtime 동일 |
| 원본169/A/B DB | 기존SHA `238d0aea41bc1377a29b9a1eb4b30f43e9d38ad39bba22e8a2fe31d7e6726287` 모두 동일 |
| 프로그램·React 코드 | 변경0 |
| local auth/Origin/CSRF/DPAPI/ACL | 정책 완화0,임시 설정의원본bytes/ACL복원 |
| 예약·외부실행 | 기존비활성/차단 유지 |
| 실제 공급사API·유료생성·OAuth·SNS |0 |
| 기존프로그램/DB/미디어/백업삭제 |0 |
| main/PR35·외부배포·무서명업데이트 |변경/실행0 |

Stop 시 기록된 credentialBoundary도 nativeCipherRequests0였다. 이번 작업에서 저장된 실제키를 복호화하지 않았다. 실제데이터 시험레코드도 추가하지 않았다.

## 6. 최종 판정과 다음 조건

정상 Stop,백업·복원 검증,신규 Start READY,포트유지,설정원복,DB·암호문/미디어·A/B보존은 확인됐다. **Chrome 인증1항목은 실패,세 제작실은 미검증**,일회용값 진단출력 사고1건을 별도로 기록한다. 이를 전체PASS나GUI성공으로 표시하지 않는다.

현재 앱은 PID3588/18768에서 계속 실행 중이지만 이번 Chrome 세션은 인증되지 않았다. 재시작 전 브라우저 세션도 새 세션에서 유효하다고 가정하지 않는다. 승인 횟수를 넘기는 자동 재시작으로 복구하지 않았다. 데이터복구는 필요하지 않았고,원복한설정과검증된 정지백업은 보존했다.

다음에는 **토큰 없는 Chrome 정식 연결 요청의 거절 조건을 먼저 확인**해야 한다. 쿠키·토큰원문을 기록하지 않고 원인을 확인한 뒤에만 필요한 최소 수정/정상 인증 동선을 결정해야 한다. Origin완화·인증우회·막연한 재시작 반복을 해결책으로 제시하지 않는다. 추가 재시작이 필요하면 별도 사용자 승인이 필요하다.

이 보고서와 비민감 집계만 개발 브랜치에 보존하고 종료한다. 유료 API 연결 준비·키등록·실제 생성·SNS·운영제품교체 등은 추가 실행하지 않는다.
