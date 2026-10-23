# YouTube 인증 링크 복사·다시 열기

## 범위

기준 Cloud 커밋: `d13af9f03a0c973e71b93445c761feea9b3df07e`.
기존 Google Desktop OAuth 연결 절차를 유지하면서 사용자 요청에 따라 다음 기능을 추가했다.

- 설정 → 게시 계정 → YouTube 연결 대기 중 `인증 링크 복사`, `인증 화면 다시 열기` 제공.
- 시스템 브라우저 실행 실패를 URL 검증·인증 정책 실패와 구분하여, OS 실행 실패만 수동 링크 사용으로 이어진다.
- 클립보드 사용이 차단되면 읽기 전용 입력란을 선택해 Ctrl+C로 복사할 수 있다.
- 복사한 링크는 NewsFlow AI를 실행한 동일 PC에서 사용한다. 연결 시작 후 최대 5분이며 복사/다시 열기로 연장되지 않는다.

## 보안·기존 동작 보존

- 링크는 진행 중인 시도의 state/PKCE/redirect URI를 그대로 사용한다. 새 시도·토큰 교환·업로드를 실행하거나 재전송하지 않는다.
- 링크는 프로세스 메모리의 SecretStr로만 관리한다. DB, 로그, 일반 상태 응답, 최초 HTML에 삽입하지 않는다.
- 사용자가 누른 CSRF/Origin 보호 POST만 링크를 반환하며 `no-store`, `no-referrer`를 유지한다. 클라이언트 비밀값·토큰·PKCE verifier는 반환하지 않는다.
- 취소·만료·교환 시작·완료·revision 변경·재시작 복구 후 거부한다. 화면의 수동 링크는 이동·새 요청·만료 시 제거한다. 이미 복사한 OS 클립보드까지 자동으로 삭제하지 않으며 사용자에게 정리를 안내한다.
- 이전 취소 작업의 늦은 정리가 같은 계정의 새 연결 링크/리스너를 제거하지 않도록 시도별 리스너를 확인한다.
- OAuth scope, 일회성 콜백, 게시 승인, DPAPI, 데이터 마이그레이션은 변경하지 않는다.

## 검증

Cloud Linux, Python 3.12.14, `/usr/bin/chromium`, 합성 서비스·임시 DB만 사용.

```sh
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs \
  tests/test_youtube_link.py tests/test_youtube_connection.py tests/test_youtube_gui.py \
  tests/test_youtube_upload.py tests/test_oauth_callback.py tests/test_oauth_protocol.py \
  tests/test_oauth_protocol_binding.py tests/test_oauth_production_gui.py
```

**PASS(관련 범위): 287 passed / 2 skipped / 0 failed / 1 warning.**

- skip: 실제 Windows current-user DPAPI, SO_EXCLUSIVEADDRUSE. Linux 모의 테스트를 Windows 검증으로 계산하지 않았다.
- warning: 기존 Starlette TestClient의 httpx 사용 중단 안내.
- Cloud 브라우저: 실제 앱 화면에서 1366×768, 1920×1080, 390×844 확인. 복사 성공/거부(권한 결과는 주입), 직접 복사 입력 포커스, 동일 인증 다시 열기, 취소 후 만료 안내, 화면 재진입 시 버튼 제거, 가로 넘침 없음.
- 실제 OS 클립보드 권한/Windows 브라우저 실행은 NOT VERIFIED. 테스트의 브라우저 열기는 Fake 또는 명시적 OS 실패 주입이며 Google 창을 열지 않았다.
- 변경 Python 파일 Ruff PASS, `node --check src/newsflow/static/js/youtube.js` PASS, `git diff --check` PASS.
- 전체 회귀 재실행 없음. 위 수치는 관련 범위이며 기존 전체 회귀 기록을 대체하지 않는다.
- 실제 Google/Meta/유료 API/OAuth/업로드/게시 호출 0건. Fake 토큰 교환은 기존 회귀에서만 합성 데이터로 수행.

## 변경 파일

- `src/newsflow/oauth/production.py`: OS 브라우저 실행 실패의 별도 오류 유형.
- `src/newsflow/oauth/youtube.py`: 메모리 링크, 유효성/재열기, 만료/취소/완료 정리.
- `src/newsflow/gui/youtube_routes.py`: 보호된 링크·재열기 POST.
- `src/newsflow/gui/templates/youtube_connection.html`: 대기 중 동작 및 간단한 사용 안내.
- `src/newsflow/static/js/youtube.js`: 클립보드/수동 복사/재열기/오류 안내.
- `tests/test_youtube_link.py`: 새 동작·보안·시도 격리·실제 Cloud 브라우저 검사.

## 전달 상태와 남은 검증

로컬 구현·커밋만 보존. 원격 push, PR #35 변경, main 변경, 사용자 PC 적용, 운영 앱 재시작 없음.
사용자 Windows 저장소에 보존 중인 4개 OAuth 보완 파일은 이 Cloud 작업에 존재하지 않는다.
추후 인수 시 특히 `oauth/youtube.py`의 로컬 진단 변경을 함께 보존하고 결합 검증해야 한다.
실제 Windows 브라우저/클립보드, 실제 Google 로그인·채널 연결, 사용자 운영 데이터는 NOT VERIFIED.
