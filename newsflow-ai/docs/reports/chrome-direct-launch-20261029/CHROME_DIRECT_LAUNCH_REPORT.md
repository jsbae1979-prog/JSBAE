# Chrome 직접 열기 준비 및 승인된 수동 인증 재시작 결과

최종 판정: **CONDITIONAL — Chrome 직접 열기 개발·집중 검사 완료. 운영 적용·Chrome 인증·세 제작실 GUI는 미완료.**

## 승인된 Stop·Start 1회

- 기준 개발 브랜치: `codex/newsflow-bat-distribution-prep`, 시작 HEAD `13bfe8cea7cbb8693dfd47cc31625adcdfe19478`.
- `C:/NewsFlowAI/Stop_NewsFlowAI.bat`로 기존 소유 PID3588 정상 종료. Stop exit0. 강제 종료0.
- 정지 상태 프로필은 별도 사용자 전용 경로에 기존 snapshot으로 백업하고 SQLite 백업의47개 테이블 내용hash를 원본과 대조했다. 기존 복원 검증 증거 재사용; 원본/A/B는 복원 대상으로 사용하지 않았다.
- `Start_NewsFlowAI.bat` 1회 실행. 현재 **PID31492 / 127.0.0.1:18768 / READY / STILL_ACTIVE**, 실제 포트 수신 확인. Start는 실행 중이므로 exit0이라고 기록하지 않는다.
- Edge의 인증 선사용을 막기 위해 launch/layout의 자동 열기와 결합hash만 일시 변경했다. 시작 후 두 파일의 원래 bytes·SHA·ACL을 복원했다. 현재 openBrowser=true.
- 브라우저 자동화0, 추가 재시작0, agent 인증 재전송0. 사용자에게 기존 로컬 인증 파일의 URL을 Chrome 주소창에 직접 입력하도록 안내했다. 해당 파일의 인증값이나 쿠키를 agent가 읽거나 출력하지 않았다.

## 사용자 수동 인증 결과

사용자 보고: `Local session unavailable. Open NewsFlow AI again from your own Windows account.`

이는 정상 CONNECT HTML의 script가 수행된 뒤 claim 단계에서 실패할 때 표시되는 문구다. 이전의 첫 CONNECT 페이지 경계 거절과 구분한다. 정확한 실패 HTTP 상태 및 최초 사용자 시도 시각은 관찰하지 않았다. 파일의 내용이 아닌 mtime만 검사했을 때 시작 후245.3초가 경과해 현재120초 lifetime 밖이었다. **최초 시도 때도 만료됐다고 단정하지 않는다.** claim의 Origin/본문/유효기간 등 어떤 조건이 실패했는지는 확정하지 않았다. 토큰·쿠키·전체 요청 헤더를 수집하지 않았고 만료값을 다시 보내지 않았다.

뉴스 쇼츠·이미지·캐릭터 제작실 GUI는 **NOT VERIFIED**. 사용자가 인증 실패를 보고했으므로 GUI 성공으로 집계하지 않는다. 새 bootstrap은 현재 코드에서 LaunchSession 생성 시에만 발급되며, 연장·재발급·쿠키 이전 같은 우회 경로를 추가하지 않았다.

## 사용자의 Chrome 자동 열기 요청에 대한 최소 수정

개발 브랜치의 `tools/bat_distribution/windows_live.py`에서 기본 브라우저에 맡기던 `webbrowser.open`을 `open_chrome_session`으로 교체했다.

- 설치된 Chrome의 표준 경로만 확인하고 기존 ordinary_absolute 경로 검증을 재사용한다. 현재 PC의 `C:/Program Files/Google/Chrome/Application/chrome.exe` 존재 확인.
- 앱 READY 후 새 세션의 기존 launch URL을 정상 Chrome 실행에 직접 전달한다. 확장 프로그램의 goto나 주소창 자동 입력을 사용하지 않는다.
- shell=False, 인자 배열, 표준입력/출력/오류 비노출. URL·native 예외를 로그에 출력하지 않는다.
- loopback·고정 허용 포트·정식connect경로·43자 fragment·query없음 검증. Edge/다른 브라우저로의 자동 fallback 없음.
- Chrome 실행 요청 수락은 인증 완료 증명이 아니다. browser-open-result에는 요청/수락여부와 browser=chrome만 기록한다.
- LocalAccess,120초 유효기간,one-time claim,HttpOnly/SameSite 쿠키,CSRF/Origin,DPAPI,ACL 정책은 변경하지 않았다.
- **현재 C:/NewsFlowAI의 코드·layout에는 이 개발 변경을 적용하지 않았다.** 실행 중 프로세스에는 이전 코드가 적재돼 있고 기존 인증값은 이미 만료돼 있다. 적용할 때 해당 controller파일과 기존layout의 해당파일hash/bytes만 일치시켜야 한다. 새로운 인증 확인에는 별도 승인된 Stop·Start1회가 필요하다. 이번 승인 횟수는 이미 사용했으므로 실행하지 않았다.

## 신규 검사와 보호

`tools/bat_distribution/tests/test_chrome_launch.py`: **13 PASS /0 FAIL /0 ERROR**, 실제 브라우저 프로세스 대신 합성URL·fake Popen 사용. Chrome 직접 argv·shell금지·출력비노출·잘못된URL거부·Chrome없음/실행실패·다른브라우저 fallback없음을 검사했다. 실제 자동열기/인증은 NOT VERIFIED. 기존 전체 회귀·패키징·보안 감사는 반복하지 않았다.

- 기존 뉴스169건 및 AI처리48/대본6/영상프로젝트7/이미지게시물3건은 기존47개 테이블의 내용hash·건수 불변으로 보존 확인.
- 암호문6개·미디어20개 총26파일의hash/size/mtime 불변.
- 기존169원본 DB 및 백업A/B의 기존SHA-256 일치 유지.
- decryptCredentials/automaticJobsEnabled/externalExecutionEnabled=false 유지. 무서명 업데이트 차단 유지.
- 키복호화·유료API·OAuth·SNS·자동화 활성화0. main/PR35/기존프로그램/백업 변경·삭제0.
- 기존 `validation/` 미추적 로컬 자료는 그대로 보존하며 커밋하지 않는다. 비공개 프로필 백업·설정bytes·인증파일·DB·키·미디어는 Git에 넣지 않는다.

추가 운영 적용과 재시작 승인 전까지 PID31492 운영 앱을 유지한다. Chrome 자동 열기 개발 완료를 실제 로그인 성공이나 세 제작실 인수로 표시하지 않는다.
