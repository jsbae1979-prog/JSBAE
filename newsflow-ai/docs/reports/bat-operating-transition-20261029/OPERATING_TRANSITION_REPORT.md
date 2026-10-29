# 신규 BAT 설치본 실제 로컬 운영 전환

**최종 판정: ACCEPTED — 현재 PC의 기본 실행 진입점 전환과 실제 프로필의 로컬 저장 활성화 범위.** 외부 API·OAuth·SNS 실행, 자동화 재개, 무서명 업데이트와 일반 사용자 배포는 승인·활성화하지 않았다.

## 기준과 최종 실행 상태

- 브랜치 `codex/newsflow-bat-distribution-prep`, 시작 HEAD `5a66c14e7cf444ffc566f7a97479429ca07b7770`.
- 실행 제어 코드 커밋 `a115abc1e878a63af3654600e53f593ca720ec54`. 최종 보고 커밋은 해당 브랜치 Git HEAD로 확인한다.
- 기본 프로그램 `C:/NewsFlowAI`, 데이터 `<CURRENT_USER_HOME>/AppData/Local/NewsFlowAI-BAT/v1`, 고정 loopback `http://127.0.0.1:18768`.
- 최종 신규 운영 앱 **실행 중**, 확인 PID23240. 현재 바탕화면 `NewsFlow AI`, 시작 메뉴 `NewsFlow AI` / `Stop NewsFlow AI`는 신규 Start/Stop BAT를 가리킨다. 바로가기 target/working directory를 저장 후 다시 확인했다. 실제 마우스 더블클릭을 새로 수행한 것으로 주장하지 않는다.
- 기존 운영8765는 닫혔다. 새 앱은8765로 자동 이동하지 않는다. 기존 프로그램·DB와 합치지 않았다.
- 기본 실행 바로가기 지정은 Windows 로그인 자동 시작 등록을 의미하지 않는다. HKCU/HKLM Run/RunOnce, 예약작업, 사용자/공용 Startup에서 NewsFlow 자동 시작 항목0. 이번 자동 시작 등록/삭제0.

## 전환 전 보호·복구

전환 직전 신규 프로필은 정지 상태였다. 기존 `distribution.offline.snapshot`의 SQLite 읽기 전용 온라인 백업을 이용해 **35파일**을 사용자 전용 비공개 경로에 보존했다. 복원 전 파일별 SHA-256과 index를 검증하고, 별도 복원 검증 디렉터리에서 기존 `restore`로 복구했다. 복원본의 모든 파일/index와47개 테이블의 내용 hash·건수가 일치하고 SQLite integrity=ok였다. 실제 프로필에 장애를 주입하거나 원본을 덮어쓰는 복구 실험은 하지 않았다.

비공개 백업은 `C:/Codex/NewsFlowAI-IsolatedReview/operating-transition-20261029/pre-transition-profile/`, 설치 제어파일/설정의 변경 전 bytes는 같은 경로의 `pre-transition-program/`에 있다. DB·암호문·미디어·전체 설정 bytes·ACL·private session은 GitHub에 올리지 않는다.

실패 복구는 신규 Stop의 소유권/종료0 확인 →18768/세션 해제 → 전환 전 신규 프로필 snapshot 복원 → 제어파일/launch/layout 복원 → 새로 추가한 제어모듈2개만 별도 검토 → 기존 실행 진입점 재사용 순서다. 동작 중 DB 덮어쓰기, 원본169/A/B 덮어쓰기, 기존0건 DB 병합, 다른 계정 DPAPI 복호화는 금지한다. 전환은 성공했으므로 실제 롤백은 수행하지 않았다. 백업과 복원 검증본은 보존했다.

## 로컬 쓰기 정책과 변경 범위

별도 `restored-local-operation` 모드만 추가했다. 기존 읽기 전용 모드와 합성 모드는 그대로 남아 있다.

| 항목 | 최종 상태 |
|---|---|
| 실제 프로필 readOnly | false: 로컬 대본·이미지/캐릭터 초안·모델 기본값·설정 저장 경로 허용 |
| 사용자/경로 | 고정 동일 Windows 사용자 경로, 기존 migration marker/installationID/ownerSID 확인 |
| 인증·CSRF·Origin | 변경하지 않은 LocalAccess 및 제품 middleware를 통과 |
| 암호문 | 기존 DPAPI 저장 구현/암호문/ACL 보존. 이번 프로세스의 실제 복호화는 계속 금지 |
| 자동화 | 앱 인스턴스의 scheduler/publishing calendar 자동 start 비활성. 기존 이력 유지 |
| 외부 실행 | collection/live AI/OAuth/SNS/예약 활성화 경로는 계속 차단. 유료 승인·결과 불명 정책을 대체하거나 제거하지 않음 |
| 업데이트 | updatesEnabled=false, 실제 배포자 인증서/신뢰 앵커 전까지 차단 |
| 실데이터 Fake 주입 | 없음. Fake RSS는 기존 합성 모드에서만 사용 |

실사용 로컬 저장 전환을 모든 외부 연동의 포괄 승인으로 해석하지 않았다. 현재 paid/SNS 버튼을 눌러도 외부 실행이 가능한 상태가 아니다. 향후 사용자가 실제 연동 검증을 승인할 때 해당 경계를 별도 검토해야 한다. 저장 키·외부 인증·자동화를 함께 풀지 않았다.

개발 변경은 `tools/bat_distribution/operation.py`, `windows_live.py`, `tests/test_operation.py`다. 실제 설치본에는 `windows_live.py`를 교체하고 기존에 없던 `local_work.py`와 `operation.py`를 추가했다. 프로그램 파일 목록에 그 bytes/SHA를 명시 등록했다. `launch.json`, `app/layout.json`에서 모드와 hash binding을 전환했다. 원래 파일에 대한 쓰기는 in-place flush/fsync로 ACL을 유지했다. React·Python 제작 엔진·native 바이너리·schema/migration·V3·운영 Guard는 수정하지 않았다. 기존 BAT ZIP/EXE 후보를 재생성하거나 교체하지 않았다.

최종 launch SHA-256: `8aac22b0a56d37354280168595b674282182425de60db432bb4ce56c9b52b1fd`

최종 layout SHA-256: `f90b5a0207cb4af92b2b4c37c570d160c53b7bca5dd5231b3b550a218facf011`

## 집중 검증과 실행·종료

- 신규 모드 집중 단위 검사 **15 PASS / 0 FAIL**. 한 건의 기존 Starlette/httpx 사용 중단 예고 경고가 있으며 제품 오류가 아니다.
- 실제 프로필의 정상 one-time claim/React 홈·3제작실·TOP3 탭, 로컬 설정, CSRF/다른 Origin 차단, 설정 저장/원복, 외부 실행403, TOP3 기존 rank1·2·3 및 미디어 링크 확인까지 **18개 검사 통과**.
- 인증 없이 React 요청403. 실제 설정 하나(request_timeout)만 인증·CSRF를 통해 다른 유효값으로 저장한 뒤 같은 API로 원복했다. 기사·대본·프로젝트·게시물 시험 레코드0.
- 첫 검증 주기에는 인증 세션을 정상 발급받기 위해 자동 브라우저 열기만 잠시 보류했다. 검증 후 true와 새 SHA binding으로 복원했다.
- 신규 Stop BAT **0**, Start 프로세스 최종 **0**, 소유 session 해제 확인. 재실행 후 설정 원값과 데이터가 유지됐다.
- 재실행은 Edge 자동 열기 accepted=true. 발급29.1초 내 bootstrap 재사용403과 Edge Studio 제목으로 정상 인증을 확인했다. token/cookie/URL fragment를 저장·출력하지 않았다.
- 실제 Edge에는 연결된 DOM 검사 채널이 없으므로 이번 **전체 Edge DOM 재검사/화면별 신규 캡처는 NOT VERIFIED**. 기존 실제 React GUI·56 PASS·합성 저장44 PASS를 재사용한다. 실제 OS DPI 역시 이전 미검증 상태를 유지한다.

검증 도구의 마지막 cached-media 루프는 이미지 게시물 경로도 포함했는데 영상 전용 정규식으로 가정해 `AssertionError`1회가 발생했다. 설정은 이미 정상 원복됐고 뒤이어 정상 Stop0을 확인했다. **앱의 미디어 오류나 제품 FAIL로 오인하지 않는다.** 미디어20개 전체 보존과 기존5개 HTTP Range/디코딩 증거를 재사용했고, 이 잘못된 가정 때문에 실데이터 설정 변경을 다시 반복하지 않았다. 신규 제품 FAIL/ERROR0, 검증 도구 ERROR1을 별도 기록한다. 과거 증거를 신규 실행 수에 합산하지 않는다.

## 데이터 보존 결과

| 대상 | 결과 |
|---|---|
| 뉴스 | 169건(기존 표시 정책 visible81/hidden88 유지) |
| AI 처리 기록 | 48건. 순수 분석48로 확대하지 않음; 기존 analysis29 |
| 대본/영상 프로젝트/이미지 게시물 | 6 / 7 / 3 |
| DB | schema0018,47개 테이블, integrity=ok |
| 전후 내용 비교 | 46개 테이블 동일. audit_logs에 승인된 설정 저장·원복 기록2건만 추가 |
| 사용자 설정 | 원값 복원, 재실행 후 동일 |
| 미디어20 + opaque 암호문6 | 26파일 hash/size/mtime 동일 |
| 자동화/게시 예약 | 각각0, 자동 실행 없음 |
| 원본169/A/B | 103파일 hash/size/mtime 동일; DB SHA3개 모두 기존값 동일 |

원본 DB·백업A/B SHA-256: `238d0aea41bc1377a29b9a1eb4b30f43e9d38ad39bba22e8a2fe31d7e6726287`.

DPAPI/OAuth 암호문의 존재·보존은 실제 로그인 성공이나 외부 사용 가능성 검증을 뜻하지 않는다. 실제 유료 AI·OAuth·SNS 호출0. 외부 공급사 연결 검사0. V3 Service Running을 확인했고 예외/비활성화/관리자 우회0.

## 기존 운영 프로세스 처리

기존 cmd20388 → Python3684 →15012 →26288 →12700의 경로/parent 계보와 기존 소유 콘솔 세션을 확인했다. 별도0건 DB를 사용한 기존 run.bat에 Ctrl+C를 보내고 CMD의 배치 종료 질문에 응답했다. 기존 launcher는 사용자 종료 메시지를 출력했고, Uvicorn KeyboardInterrupt traceback 및 콘솔 종료코드1이 남았다. 이를 신규 Stop0이나 오류 없는 기존 종료로 바꾸어 보고하지 않는다. 서버 정리 finally 경로와 프로세스4개 소멸,8765 해제를 확인했으며 taskkill/TerminateProcess/강제 잠금 해제는 사용하지 않았다. 신규18768은 계속 유지됐다.

기존 코드·DB·키·미디어·백업은 삭제하지 않았다. 기존 HTML 운영본은 필요 시 수동 재사용할 수 있게 보존했다. 재사용 시 신규 프로필과 임의 합병하거나 두 운영본이 같은 DB에 동시 쓰게 하면 안 된다.

## 정리 후보와 남은 조건

- `C:/Codex/NewsFlowAI/newsflow-ai/run.bat`와 구형 HTML 프로그램 파일은 향후 정리 검토 대상으로만 둔다. 기존 DB/인증자료/미디어/A/B 및 EXE/ZIP 보존 후보는 삭제 목록에 넣지 않았다. **이번 실제 삭제0**. 오래된 NewsFlow 바로가기나 자동 시작 등록은 발견되지 않아 제거하지 않았다.
- 실제 API별 모델/유료 생성/계정 권한·OAuth/SNS는 별도 승인·검증 필요. 현재 로컬 작업 전환이 그 승인을 대신하지 않는다.
- 배포자 인증서/신뢰 앵커, FFmpeg 대응 소스 제공, 샘플12개 사용권, 신규 타 사용자 Windows 설치/DPI 증거는 기존 외부 배포 조건으로 남는다. 무서명 업데이트/외부 배포 차단 유지.
- main·PR35·기존 완료 브랜치 변경/병합0. 새 브랜치 생성·전체 회귀·Guard/V3 분석·디자인·BAT 패키징 반복0.

결과: 신규 BAT 설치본은 현재 PC의 기본 로컬 실행본으로 전환됐고 실제 프로필의 허용된 저장이 동작한다. 원본과 복원 가능한 전환 전 백업을 보존한다. 현재 신규 앱/Edge는 실행 중이며, 종료는 신규 Stop 바로가기를 사용한다.
