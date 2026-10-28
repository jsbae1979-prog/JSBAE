# 실제 다른 제품 두 버전의 설치·업데이트 실패 복구 검증

## 이번 구현

- 이전 제품 source: `9a54ec8e26f33ae6312b3d5eb80715b9a7f01342`.
- 신제품 source: 이 작업 브랜치의 CI-tested code commit, 실행 결과 JSON에 고정.
- 실제 차이: 신제품은 current-user ACL profile, per-launch local HTTP 인증,
  동적 전용 포트, bundled SAPI 동작을 포함하는 packaged desktop entry다.
  이전 제품은 당시의 정상 `newsflow.main.run` packaged entry다.
  단지 Setup 버전 문자열 또는 build timestamp만 바꾼 비교가 아니다.
- 최초2회 실제 이전 EXE 초기 실행에서 UnicodeEncodeError가 발생했다.
  frozen interpreter는 PYTHONUTF8 환경변수만으로 보정되지 않았다.
  이후 두 후보의 PyInstaller spec에 동일한 ('X utf8',None,'OPTION')을
  적용했다. 과거 product source는 그대로이며, 이전 후보도 이 packaging
  delta를 포함하므로 과거 배포 EXE와 byte-identical인 검증이라고 주장하지 않는다.
- 프런트엔드는 두 source에서 같음을 Git diff로 먼저 확인한 뒤 생성된 dist를
  재사용한다. 과거 제품의 Python source/entry를 신제품으로 덮지 않는다.
- 현재 제품에는 `--no-browser`만 추가했다. 기본 실행은 기존처럼 브라우저를
  연다. CI에서는 브라우저 자동 열기만 생략하며 local auth/CSRF/Origin/ACL/
  media hash/cost/publishing 정책은 그대로다. 임의 CLI operation은 거부한다.
- 기존 PyInstaller6.22.3/Windows Python3.14.7/고정 FFmpeg를 재사용해 두 제품을
  각각 빌드한다. 두 EXE digest 및 source commit을 따로 기록한다.
- 기존 Inno 구조를 재사용한 CI 전용 side-by-side slots 설치 정의다.
  이전 제품을 덮어쓰지 않는 candidate staging, 합성 target 파일의 Windows
  공유 위반에 의한 실제 복사 실패 주입,
  active pointer 전환 실패 및 복구를 검증한다.

## 검증 데이터/보안

모든 설치본/프로세스/사용자 profile은 Runner TEMP의 새 소유 디렉터리다.
프로세스 환경은 최소 OS 변수와 합성 LOCALAPPDATA/HOME/APPDATA/TEMP로
새로 구성한다. 실제 API 키/OAuth/DPAPI/운영 미디어를 전달하지 않는다.
이전 제품의 지원되는 NEWSFLOW_DATA_DIR 옵션으로 신제품의 합성 profile과
동일 경로를 지정해 데이터 보존을 비교한다. 기본 경로 변경 migration은
검증하지 않았으며 별도 미검증 조건이다.

실제 초기화한 SQLite app_settings에 합성 marker/샘플 상태를 저장하고,
별도 합성 settings/media 및 native DPAPI sentinel·session.key를 비교한다.
실제 공급사 키 등록이나 계정 인증이 아니다. DB 물리 바이트가 아니라
관련 logical rows를 비교하며 SQLite WAL 정리로 인한 차이를 손실로 단정하지 않는다.
실제 제품 scheduler는 빈 DB·disabled sources·등록 작업/비밀값 없음 상태로
초기화되며 생성/게시/예약 실행을 요청하지 않는다. 이 준비가 외부 네트워크
전체 OS 차단을 구현했다는 뜻은 아니다.

정상 종료는 CTRL_BREAK와 기존15초 경계를 사용한다. 강제 정리가 필요하면
forced_cleanup:true 및 실패로 남긴다. 상태 파일과 원래 EXE 보존만으로
복구 성공을 주장하지 않고 이전 앱의 HTTP 준비·종료/포트 해제를 확인한다.
신제품에서는 인증 bootstrap 페이지200/익명 API403까지 확인한다.
로그·DB·암호문·EXE·Setup은 GitHub artifact에 업로드하지 않으며
검증 상태/파일 hash 등 비민감 JSON만 보존한다.

## 확대한 주장 금지

이는 CI 전용 기술 후보 설치/복구다. 실제 공개 배포용 서명 updater는
기존처럼 비활성 상태이고 signature verifier를 바꾸거나 unsigned 예외를
제품에 추가하지 않았다. active.json 전환은 이번 기술 검증 도구의 동작이며
이미 사용자에게 배포된 updater의 자동 복구라고 표시하지 않는다.

오류 주입은 **신제품 앱을 처음 실행하여 DB migration하기 전**에 수행한다.
따라서 post-migration DB restore, 전원 차단, 실행 중 binary 교체, 실제 서명
apply, default profile 이동, Windows11 fresh user 설치는 NOT VERIFIED다.
서로 다른 package의 실제 install/start/rollback 범위와 위 잔여 항목을 구분한다.
최종 실행/실패/복구 결과는 CI_EVIDENCE.json 및 recovery-results.json을 따른다.
