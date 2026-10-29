# 실제 설치본 브라우저 자동 열기 설정 적용·집중 검증

**최종 판정: ACCEPTED — 사용자가 명시 승인한 두 설정 적용과 실행 동선 범위.** 실제169 데이터의 쓰기 활성화·기본 운영 전환·기존 프로그램 종료/교체/삭제·실제 API/SNS·외부 배포는 수행하지 않았다.

## 1. 기준과 변경 파일

- 개발 브랜치 `codex/newsflow-bat-distribution-prep`, 시작 HEAD `9453ff9c66f8a5f6e70cbed52698b67731ab73c1`.
- 실행 설치본 `C:/NewsFlowAI`. 설치된 프로그램/React/의존성 바이트는 이전 인수본 그대로다. 기존 코드 구현 SHA04d04aa를 바꾸지 않았다.
- 사용자별 실제 launch 위치는 `<CURRENT_USER_HOME>/AppData/Local/NewsFlowAI-BAT/launch.json`이다. 프로그램 루트에 새 launch.json을 만들지 않았다.
- 실제 변경 파일은 위 **launch.json**과 **`C:/NewsFlowAI/app/layout.json`** 두 개뿐이다.

| 파일 | 적용 내용 | 변경 전 SHA-256 | 변경 후 SHA-256 |
|---|---|---|---|
| launch.json | `openBrowser: false` → `true` | `9ccc460d37998f4d1c18f691b8cdcd2a86dcd8321ec63214bda01042902b2cf0` | `775265e4edaaecc995b93654d9f834cb73bdab4b970504111d8c1f6fe2552d47` |
| app/layout.json | 위 설정 bytes의 `validationConfigSha256` 결속 | `9a26cd00a7d708feed8edd72e395b991b2f22befef479a4092191dc86fb7de28` | `5e7a9eab07ce8be43d8686154edf87a260f9fe169f76aa2303ad70561b033e3d` |

준비된 승인 후보와 현재 파일을 먼저 대조했다. launch의 다른 필드와 layout의 다른 필드는 모두 동일했다. **readOnly=true, decryptCredentials=false, profileKind=restored-private-validation, 포트18768, updatesEnabled=false**를 유지했다. 원래 파일 identity/ACL을 유지하는 쓰기로 적용하고 flush/fsync 후 재검증했다. 새 사용자 승인을 근거로 적용됐으며 이번 단계에 자동 심사 거절은 없었다.

## 2. 변경 전 백업·복구 준비

두 원본 파일을 별도 사용자 전용 비공개 `browser-setting-acceptance-20261029/before-change/`에 보존했다. 위 변경 전 SHA-256과 실제 백업 파일 hash가 같음을 적용 전과 실행 검증 후 확인했다. 원본 ACL/owner/group 보안 설명자도 비공개로 기록했고, 적용 후 및 재실행 후 정확히 같았다.

실제 파일 백업·전체 launch/layout bytes와 ACL 설명자는 GitHub에 올리지 않는다. 불일치나 파일 쓰기 오류가 생기면 두 백업 bytes로 되돌리도록 적용 명령에 롤백 경로를 두었으며 이번에는 롤백이 필요하지 않았다. 실제169 DB·키·미디어·기존 백업A/B를 복구하거나 덮어쓰지 않았다.

## 3. 실제 BAT 실행·브라우저·정상 인증

| 실제 설치본 집중 확인 | 결과 |
|---|---|
| 1차 Start | READY, 고정127.0.0.1:18768 |
| 기본 브라우저 자동 열기 | Edge의 NewsFlow AI Studio 새 탭 확인 |
| 정상 브라우저 인증 | 발급39.2초 내 bootstrap 재사용403: 이미 정상 브라우저가 일회용 인증을 소비함 |
| 인증 없는 GUI 요청 | 403 유지 |
| 1차 Stop | Stop BAT0 / Start BAT 최종0 |
| 2차 Start·설정 보존 | 자동 열기와 동일 설정/해시 결속 유지 |
| 재실행 브라우저 | Edge의 NewsFlow AI Studio 새 탭 재확인 |
| 재실행 정상 인증 | 발급24.6초 내 bootstrap 재사용403 |
| 2차 Stop | Stop BAT0 / Start BAT 최종0 |
| 최종 소유 앱/18768 listener | 0 / 0 |

정상 브라우저가 기존 `/__local/connect` 흐름으로 인증한 뒤 React 제목의 Studio 페이지를 연 사실을 창 메타데이터와 일회용 인증 소비로 확인했다. 세션 토큰/fragment URL/쿠키는 출력·Git 저장하지 않았다. 기본 Edge에는 연결된 DOM 검사 채널이 없어 **이번 새 Edge DOM 상세 캡처는 NOT VERIFIED**다. 동일 React 자산·실제 데이터의 기존 GUI 인수 결과를 재사용하며, 현재 모든12화면을 새로 검사했다고 주장하지 않는다.

기존 브라우저의 다른 탭과 공유 Edge 프로세스는 종료하지 않았다. Stop은 신규 앱의 소유 프로세스만 종료한다. 브라우저 탭은 앱 종료 후에도 남을 수 있으며 기본 운영 전환이나 기존 프로그램 종료를 뜻하지 않는다. BAT는 명시적 절대 경로를 cmd로 실행했고 실제 마우스 더블클릭 자체를 검증한 것으로 표시하지 않는다.

## 4. 실제169 데이터·보안 보존

앱 실행 전후47개 데이터 테이블의 모든 행 내용 hash와 건수가 같았다. schema0018, SQLite integrity=ok. 기사169·AI처리기록48·대본6·영상프로젝트7·이미지게시물3이 유지됐다. AI처리기록48을 순수 분석48로 확대하지 않는다(기존 분석29).

암호문6개·미디어20개, 합계 **26파일의 hash·size·mtime이 전후 같았다**. 두 실행의 native cipher 요청0, 실제 DPAPI 복호화0. 사용자 데이터 쓰기 기능을 활성화하거나 편집 요청을 보내지 않았다.

- 기존 LocalAccess·CSRF·Origin·사용자별 ACL은 변경하지 않았다.
- 앱 인스턴스의 scheduler/publishing 자동 시작 차단을 그대로 유지했다.
- 실제 유료 API·OAuth·SNS 호출0, 실제 업데이트0. 무서명 업데이트 차단 유지.
- 원본169 경로·기존0건DB·백업A/B는 이번 변경/복원 대상이 아니었다. 기존56/44 PASS와 보존 증거를 재사용했다.
- 기존 운영 PID3684·12700·15012·26288 네 개 유지,8765 사용·접속·종료/재시작0.
- V3 Service Running. V3 비활성화·예외·권한 우회·차단 EXE 사용0, 이번 실행 차단 미관찰.

배포자 인증서/신뢰 앵커, 실제 프로필 쓰기·기본 운영 전환·유료 생성·게시 승인 상태는 이번 변경으로 달라지지 않는다.

## 5. 결과와 종료 상태

승인된 설정 적용, 백업/ACL/hash, 실제 Start·Stop2주기·재실행 보존·브라우저 정상 인증과 데이터 무변경 확인은 **PASS**, 신규 FAIL/ERROR0이다. 단위/전체 회귀·패키징·Guard/V3 감사는 실행하지 않았다. 과거44 PASS·56 PASS·기존 Start/Stop 증거를 신규 실행 수에 합산하지 않았다.

Windows TCP 표의 종료 직후 일시적 listener 관측은 후속 읽기 조회에서0으로 확인했다. 강제 종료·잠금 해제·추가 앱 실행은 없었다. 신규 앱은 최종 Stop 상태이며 기존 운영4프로세스는 계속 유지된다.

실제 C 설치본에서 Start BAT를 실행하면 기존 읽기 전용169 프로필과18768로 정상 브라우저를 여는 설정이 적용됐다. **실제 데이터 편집/쓰기와 기본 운영 교체가 승인·완료된 것은 아니다.**

Git 변경은 이 결과 보고와 비민감 증거/개발 설명에 한정한다. 실제 launch/layout, DB·키·미디어·개인 baseline/백업 bytes는 올리지 않는다. main·PR35 변경·기존 프로그램 삭제·외부 배포는0회다.
