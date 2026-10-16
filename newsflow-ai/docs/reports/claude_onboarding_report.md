# Claude 연결 초기 설정 및 배포 준비

보고 기준: 2026-10-16 KST. 대상 Windows 11 / Python 3.12·3.14.

## 구현·사용 순서

- 기존 공식 CLI 탐색, 최소 권한 추론, JSON 검증, 취소·시간 제한·자동 재시도 금지를 재사용했다. Provider 선택 UI를 중복 구현하지 않았다.
- 홈의 **API·계정 설정 → Claude 연결** 또는 **대본 만들기**에서 연결 준비에 접근한다. 이전 미커밋 홈 접근성 개선 4개 파일은 별도 커밋 `d669e950f220b649012ddb2ac7c44e5edbe56626`으로 보존했다.
- **설치·로그인 확인**은 `--version`, `auth status`만 실행한다. 페이지 로드·Provider 선택·기본값 저장은 CLI나 추론을 실행하지 않는다. 자동 조회는 없다.
- 미설치는 공식 설치 문서로 안내한다. 미로그인일 때만 사용자가 동의 후 **공식 CLI 로그인 창 열기**를 누르면 수정되지 않은 CLI의 `auth login` 대화형 창을 연다. 로그인 출력·URL·코드·토큰을 수집하지 않는다. 이미 준비 완료이면 재로그인하지 않는다.
- 창 종료만으로 성공 처리하지 않는다. 사용자가 연결을 다시 확인해야 한다. 앱 프로세스 안의 중복 로그인은 차단한다. 앱 밖에서 사용자가 연 창이나 앱 재시작 전의 로그인 창은 추적하지 않으므로 기존 창을 먼저 완료·닫도록 안내한다.
- 기존 Provider 선택에서 Claude와 모델을 고르고 **AI Studio 기본값 저장**을 누른다. 기존 AppSetting에 저장하며 migration을 추가·수정하지 않는다. 분석·대본의 매 실행 동의와 Autopilot·예약 설정은 별개다.
- **앱에서 Claude 기본 사용 해제**는 AI Studio를 Offline으로 바꿀 뿐 CLI 로그아웃·자격증명 삭제를 하지 않는다.

## 인증·비용·배포 조건

공식 문서 확인: [설치](https://code.claude.com/docs/en/setup), [CLI reference](https://code.claude.com/docs/en/cli-reference), [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance).

- 공식 문서는 제품 내 CLI 실행 조건과 제3자 앱의 Claude.ai 로그인·자격증명 중개 제한을 함께 명시한다. 사용자가 설치한 수정되지 않은 CLI와 본인 계정을 사용하며 인증정보를 앱이 중개·추출하지 않는다. 사용자 확인 체크박스를 배포 약관 승인 증거로 취급하지 않는다.
- 상태 검사는 CLI의 현재 환경을 관찰한다. API 키·다른 인증 방식은 **인증 확인됨 / 앱에서 해당 과금 방식 승인 필요**로 구분한다. API 경로를 활성화하지 않는다.
- 기존 추론 경로의 구독 전용 가드와 API 자격증명 환경변수 제거를 유지했다. `CLAUDE_CONFIG_DIR`은 공식 사용자 구성 위치를 동일하게 사용하도록 보존한다. CLI 바이너리·내장 로그인 방식을 변조하지 않는다.
- 앱의 구독 전용 실행 제한과 환경변수 필터링이 일반 제품 배포 조건 전체를 충족하는지는 **NOT VERIFIED**다. 개인 PC 성공을 재배포·상업 서비스 허용으로 확대하지 않는다. 별도 약관 검토가 필요하다.
- 자료 전송·본인 계정 사용량·공급사 제한, 로컬 사용 기록과 실제 청구량의 차이를 안내한다. 무료·무제한이나 잔여 한도를 보장하지 않는다. 웹 검색은 켜지지 않는다. 다른 유료 Provider로 자동 전환하지 않는다.

## 검증

- Windows 11 / Python 3.14.7: `pytest -q tests/test_claude_onboarding.py tests/test_claude_audio_fit.py` **32 passed**. 변경 Python 파일 Ruff PASS.
- Fake: 미설치·구버전·미로그인·정상·다른 인증·오류·시간 초과, 동의·중복 창·취소·종료 후 재확인, 설정 재시작 보존·Provider 전환, CSRF/Origin·비밀정보 비노출·추론 미실행을 확인했다.
- 첫 테스트에서 테스트 대역의 바인딩 오류를 수정했다. 샌드박스의 asyncio 로컬 소켓 대기 때문에 일반 사용자 실행으로 전환했으며 앱 보안 정책은 변경하지 않았다.
- 실제 기존 `run.bat` 재시작, 내장 브라우저의 AI Studio 화면과 버튼 동작을 확인했다. 공식 CLI **2.1.301**, 상태 **로컬 실행 준비 완료**(20:23 KST). 실제 공식 로그인 창 재실행은 기존 로그인 보존을 위해 하지 않았다. 로그인 창 동작 자체는 Fake 검증이다.
- 실제 화면에서 **Claude Code / sonnet** 기본값을 저장하고 다시 열었을 때 복원됨을 확인했다. 실행 동의는 미체크. 기존 초안 #2와 Video Studio 링크가 표시된다. Chrome 별도 검증·새 추론·음성 생성·사람 청취는 수행하지 않았다.
- 기존 LocalCache 데이터 경로를 유지했다. 읽기 전용 SQLite 백업은 무시된 `validation-output`에만 저장했다. 기사 8·초안 2·영상 프로젝트 2·렌더 작업 2·AI 실행 4건 유지, 기존 MP4 2개 SHA-256 동일, SQLite quick_check `ok`. AI Studio 외 설정은 백업과 동일하다.
- Python 3.12·3.14 변경 영역 Windows CI를 한 번 실행하도록 전용 workflow를 추가했다. 결과와 최종 Git 식별자는 아래 게시 기록에 기재한다. 전체 회귀는 실행하지 않는다.

## 변경 파일·게시 기록

- 홈 접근성: `base.html`, `easy_home.html`, `simple_settings.html`, `easy.css`.
- 연결·설정: `intelligence/claude_code.py`, `intelligence/settings.py`, `intelligence/service.py`, `gui/intelligence_routes.py`, `gui/templates/ai.html`, `gui/templates/claude_connection.html`, `static/js/app.js`, `static/js/claude_connection.js`.
- 검증·문서: `tests/test_claude_onboarding.py`, `.github/workflows/newsflow-claude-onboarding-windows.yml`, 본 보고서.
- Base: `feat/newsflow-phase5f3-voices` / `b570a29a37138080b787170e23a967be009c2596`.
- 작업 브랜치: `feat/newsflow-claude-onboarding`. 기존 PR #18·#20, 연구 브랜치, main 변경 없음.
- 인증·세션 파일, 사용자 DB, WAV/MP4, 모델 가중치·로컬 검증 캡처는 커밋하지 않는다.
- PR·코드 SHA·Actions 결과: 게시 후 기록 예정.
