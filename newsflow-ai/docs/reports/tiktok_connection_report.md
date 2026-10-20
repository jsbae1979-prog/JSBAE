# TikTok 앱 연동 개발 보고서

작성일: 2026-10-20 KST. 기준 커밋 `8a0447f4a2e7c4a0352812dc6e486edc85880071`.
검증 코드: `feaff78915236fd04a404d3b76b740e6fb94a324`.
브랜치: `codex/newsflow-ux-video-app`. 로컬 커밋만 보존하며 원격 push·PR #35 변경·main 병합은 하지 않았습니다.

## 결과

**개발·합성 검증 범위 완료. 실제 TikTok 로그인·업로드 가능 판정은 NOT VERIFIED입니다.**

- Desktop 앱 정보 등록, Windows 보호 저장소 분리, 연결 상태 및 동의 UI 추가.
- TikTok 전용 Desktop PKCE/state/loopback callback → 코드 교환 → open_id 검증 → 계정 연결 처리 구현.
- 갱신·해제·취소·만료, 계정 격리, revision CAS, 암호문 쓰기/검증/참조 전환, 결과 불명 복구 구현.
- 기존 TikTokPublisher/ExtendedPublishingService/UnifiedPublishingService에 합성 OAuth 바인딩을 주입해 검토·승인·전송·결과·재시작 중복 방지 검증. 게시 엔진은 재작성하지 않았습니다.
- 실제 로그인·브라우저 실행·서비스 토큰 취급은 코드 수준 기본 차단. 설정 저장·환경변수·GUI 동의만으로 활성화되지 않습니다. 운영 게시 서비스는 기존 BlockedTransport 유지.
- DB 모델과 현재 마이그레이션 재사용. 새 migration 없음. 운영 DB/키/영상 사용 없음.

## 공식 문서 및 운영 제한

공개 공식 문서에서 Desktop Login Kit 지원과 wildcard loopback 포트, TikTok의 SHA256 **hex** PKCE, code exchange/refresh/revoke, 계정 조회 scope를 확인했습니다.
근거 URL과 계약은 [TikTok 연동 문서](../TIKTOK_CONNECTION.md)에 정리했습니다.

TikTok Content Sharing Guidelines는 개인·팀이 관리하는 계정만을 위한 업로드 유틸리티를 부적합 사용례로 명시합니다. NewsFlow AI의 실제 앱 용도·이용 대상과 심사 적합성은 별도 확인해야 합니다.
공용 Client secret을 공유 배포본에 포함하지 않습니다. 현재 사용자 자신의 앱 정보를 Windows에 암호화하는 구조이며, 공용 앱을 다중 사용자에게 배포하는 비밀값 관리 구조는 별도 검토가 필요합니다.

## 수정한 검증 중 결함

1. FastAPI 기본 입력 검증 오류에 제출한 Client secret이 포함될 수 있었습니다. TikTok 라우트 전용 검증 오류 처리로 입력값을 응답에서 제거했고, 길이 초과·잘못된 필드·CSRF/Origin을 검증했습니다.
2. 같은 화면으로 돌아오는 POST가 연결 상태를 갱신하도록 기존 form JS에 TikTok 전용 상태 갱신 처리를 추가했습니다. 실제 Chromium POST와 재진입으로 확인했습니다.
3. 만료된 계정을 계속 준비 완료로 표시하지 않고 인증 만료/재연결 안내를 표시합니다. 사용자 명시적 인증 갱신 경로는 별도로 유지합니다.

## 테스트

환경: Cloud Linux 개발 컨테이너, Python 3.12.14, Chromium 151.0.7922.173. Windows를 모의한 테스트를 Windows 실행이라고 기록하지 않습니다.

```sh
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_TIKTOK_EVIDENCE=/tmp/newsflow-tiktok-evidence \
.venv/bin/python -m pytest -q -rs \
  tests/test_tiktok_connection.py tests/test_tiktok_gui.py \
  tests/test_tiktok_publishing_connection.py \
  tests/test_production_dpapi.py tests/test_production_vault.py tests/test_oauth_callback.py \
  tests/test_youtube_connection.py tests/test_youtube_link.py tests/test_youtube_gui.py \
  tests/test_instagram_connection.py tests/test_instagram_gui.py \
  tests/test_social_platforms.py tests/test_social_transport.py tests/test_social_ui.py \
  tests/test_social_calendar_analytics.py tests/test_unified_publishing.py \
  tests/test_unified_publishing_gui.py tests/test_platform_guides.py
```

최종 결과는 아래 표 및 함께 제공한 `pytest.txt`에 기록합니다.

| 검증 | 결과 |
|---|---|
| 변경 범위 및 관련 회귀 | PASS: **463 passed / 5 skipped / 1 warning / 0 failed**, 77.67초 |
| Ruff `ruff check src tests` | PASS |
| `python -m pip check` | PASS, broken requirements 없음 |
| 실제 Cloud 브라우저 | PASS, 1366×768 / 1920×1080 / 390×844 |
| Windows Python3.12/3.14, native DPAPI/포트 | NOT VERIFIED, Windows 실행 수단 없음 |
| 실제 TikTok 인증·앱 심사·권한·게시 | NOT VERIFIED |
| 현재 전체 제품 회귀 | 재실행하지 않음. 범위 테스트를 전체 PASS로 확대하지 않음 |

Windows 전용 skip은 TikTok native DPAPI, 기존 production DPAPI, production vault, SO_EXCLUSIVEADDRUSE, YouTube native DPAPI입니다. 테스트 삭제·근거 없는 skip 추가 없음.
Starlette TestClient의 httpx deprecation 경고 1건을 별도 유지합니다. 과거 전체 회귀 57 FAIL 기록도 수정하지 않았습니다.

신규 TikTok 테스트는 앱 설정 암호화/비노출, 실제 loopback HTTP, PKCE/state/Host/Origin/replay/포트 충돌, 거절/취소/만료, token 응답 및 scope/identity 불일치, 갱신 회전·해제, 두 서비스의 동시 인증 선점, CAS, 장애/재시작/미완료 암호문 보존, 승인 누락, Fake 게시·중복 방지를 포함합니다.

## 화면 검증과 자료

- 기본 차단 상태와 합성 앱 등록 후에도 로그인 버튼 비활성 유지 확인.
- 합성 환경: 저장 → 다른 화면 이동 → 재진입 → 별도 동의 → Fake 연결 → 상태 확인.
- Client secret 재표시 없음, 포커스 이동, 모바일 가로 넘침 없음.
- 합성 계정은 화면에 “합성 인증 검증 환경 · 실제 계정 아님” 및 “합성 연결됨”을 표시.
- `tiktok-default-blocked.png`, `tiktok-default-blocked-mobile.png`: 기본 차단, 후자는 합성 앱 설정만 저장한 상태.
- `tiktok-connected-1366.png`, `tiktok-connected-1920.png`, `tiktok-connected-390.png`: 합성 계정 상태.
- `tiktok-app-settings.png`: 접힌 설정을 열고 키 입력 포커스 확인. 기존 비밀값은 빈 입력란.
- 화면은 위 검증 코드에서 임시 앱/DB로 촬영. 사용자 PC·Windows 화면 배율 검증은 아님.

## 외부 호출과 보존

실제 공급사 로그인·계정 조회·token exchange/refresh/revoke·영상 전송·SNS 게시·유료 API **0건**.
테스트는 Fake HTTPS 연결, `nf-synthetic-` 앱/코드/토큰, 합성 publisher만 사용합니다. GUI 테스트는 외부 요청 차단과 외부 요청 목록0건을 확인합니다.
공식 문서 공개 GET은 인증/API 실행과 구분합니다. OAuth 브라우저는 Fake 주입, 실제 브라우저 검증은 로컬 NewsFlow UI만 사용했습니다.

원격·PR·main 및 운영 앱을 변경하거나 재시작하지 않았습니다. 개발 파일만 수정했습니다. 사용자 PC의 로컬 보완4개, DB/LocalCache/DPAPI/영상에는 접근하지 않았습니다.

## 남은 항목

- 실제 Windows 현재 사용자 DPAPI·시스템 브라우저·콜백·포트 점유: NOT VERIFIED. 재현 명령은 연동 문서 참고.
- 실제 TikTok의 Desktop PKCE 수용, 앱 심사, scope 부여, 실제 토큰·계정·영상 게시: NOT VERIFIED.
- 현재 운영 인증/게시가 차단된 것은 의도된 경계입니다. 실제 계정 테스트와 운영 활성화는 후속 승인 범위입니다.
- 오래된/실패한 암호문은 자동 삭제하지 않으며 안전한 정리 도구는 이번 범위에서 구현하지 않았습니다.
- 실제 사용자 Windows PC의 기존 데이터 결합·설치·실행·청취 품질은 검증하지 않았습니다.
- 사용자용 가이드와 기술 문서를 갱신했고 기존 역사 보고서는 보존했습니다.

## 변경 파일

- 인증: `oauth/tiktok.py`, `tiktok_protocol.py`, `tiktok_callback.py`, `tiktok_credentials.py` 신규.
- 공통 보안 재사용: `oauth/production_dpapi.py` 계정 namespace 검증기 주입 추가(기존 기본값 유지).
- GUI: `gui/tiktok_routes.py`, `templates/tiktok_connection.html` 신규, `social_routes.py`, `platform_connections.html`, `static/js/app.js`, `static/css/studio-workstations.css` 연결.
- 초기화/종료: `main.py` TikTok 서비스 등록·복구·종료.
- 가이드: `templates/guides/tiktok.html`, `docs/platform_account_guides.md`, `docs/TIKTOK_CONNECTION.md`.
- 신규 검증: `tests/test_tiktok_connection.py`, `test_tiktok_gui.py`, `test_tiktok_publishing_connection.py`.
- 보고서 이후 변경은 문서뿐이며 검증 코드의 src/tests는 동일하게 보존합니다.
