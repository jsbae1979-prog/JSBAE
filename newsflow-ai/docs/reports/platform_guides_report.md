# 플랫폼별 계정·게시 가이드 구현

작성: 2026-10-20 KST. 기준 코드 `52f38891c5faa5d6b720ee5f00d7513d88cdb50a`.

## 구현

- 정적 읽기 전용 `/guides/platforms`, `/guides/platforms/{youtube,instagram,tiktok}`.
- 설정 게시 계정의 전체 가이드북 및 YouTube/Instagram별 링크, 추가 플랫폼 화면의 TikTok 링크. 모두 새 탭으로 열어 기존 입력 상태를 보존.
- 계정 생성 → 직접 업로드 → 앱 연동 → 게시 확인 → 문제 해결 → 공식 도움말.
- 직접 업로드에는 API 키/개발자 앱 불필요, 직접 게시한 기록은 앱에 자동 동기화되지 않음을 안내.
- YouTube Desktop OAuth, 채널 확인, 링크 복사, 별도 게시 승인 안내.
- Instagram 프로 계정·Page·Meta 앱·권한·HTTPS 중계의 사용자/운영자 역할 분리.
- TikTok 실계정 연결·실게시 비활성과 심사 적합성 문제를 명시. 준비 목록을 사용 가능한 연결 기능으로 표현하지 않음.
- 운영자 설명은 접을 수 있으며 Ctrl+P 시 펼쳐 인쇄/PDF에 포함, 이후 원래 상태 복구.
- `gui/templates/guides/*.html`을 패키지에 포함. README 첫 부분에 최신 가이드 경로와 과거 Phase 기록의 구분을 추가. 과거 보고서는 보존.

## 최종 검증

Cloud Linux / Python 3.12.14 / Chromium 151, 임시 DB와 기존 Fake fixture.

```sh
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_GUIDE_EVIDENCE=/tmp/newsflow-guide-evidence \
.venv/bin/python -m pytest -q -rs tests/test_platform_guides.py tests/test_youtube_gui.py tests/test_instagram_gui.py
```

**46 passed / 0 failed / 0 skipped / 1 warning (Starlette TestClient httpx 사용 중단 안내).** 전체 회귀 수치가 아닌 변경 범위 결과.

- HTTP GET/알 수 없는 플랫폼 404/POST 미지원, 기존 CSP/캐시 정책 유지.
- 가이드 열람 전후 설정·계정·게시 작업 레코드 동일. 로그인·계정 조회·게시 서비스 호출 없이 렌더링.
- 실제 Cloud 브라우저: Instagram App ID 미저장 입력 → 가이드 새 탭 → 원래 입력 보존. 세 플랫폼의 1366×768, 1920×1080, 390×844 화면 가로 넘침 없음. 목차 이동·키보드 details 열기/닫기·콘솔 오류 없음.
- 브라우저 요청은 로컬 GET만. 외부 탐색/POST 0건. 테스트 중 링크된 외부 사이트는 방문하지 않음.
- 세 플랫폼 PDF 생성. `pdftotext`로 접힌 운영자 내용의 포함 확인. 실제 프린터 출력은 미검증.
- Ruff/JS 문법/git diff --check PASS.
- 설치 환경에 setuptools가 없어 첫 wheel 빌드 실패. Cloud 가상환경에 setuptools/wheel만 설치 후 네트워크 없이 재빌드 성공. wheel 내부 세 가이드·CSS·JS 포함 확인.
- 최초 테스트 2건은 테스트 작성 오류: CSRF/Content-Type 없는 POST의 기대 상태, 접힌 부모 계정 관리 영역을 열지 않은 브라우저 동작. 제품 보안 변경 없이 실제 요청/사용 동선으로 고친 뒤 위 최종 결과 획득.

## 근거와 제한

작성 중 Google 채널 생성·업로드·Desktop OAuth, Instagram 도움말·Facebook Login API, TikTok 계정/게시/정책의 공식 공개 URL을 GET으로 확인(HTTP 200). Meta/TikTok 일부 페이지는 동적 내용이라 링크 접근이 모든 최신 UI·심사 조건의 확인을 뜻하지 않는다. 기존 구현·공식 링크를 바탕으로 안내하며 메뉴/조건 변화 가능성과 실계정 미검증을 표시한다.

실제 공급사 인증/API/토큰 교환/유료 생성/업로드/게시 0건. 공개 도움말 GET은 인증 호출과 구분한다.
사용자 Windows PC, Windows 배율, 실제 플랫폼 계정 생성·연결·게시 및 심사 결과는 NOT VERIFIED.
OAuth/게시 엔진·DB migration·키·운영 설정 변경 없음. Git 원격 push/PR/main 변경 및 운영 앱 재시작 없음.

증거: `/tmp/newsflow-guide-evidence`의 9개 화면, 3개 PDF. 배포용 가이드북은 같은 HTML 본문을 사용하며 `/workspace/outputs`에 별도 제공한다. 다운로드했던 이전 ZIP은 갱신되지 않으므로 앱 안의 가이드를 사용하려면 이번 소스 변경을 별도로 반영해야 한다.
