# C단계 — 제작·검토·YouTube/Instagram 게시 통합

## 구현 결과

- B 승인 기준 `765fe0fe3b1526098a0115f3d54fb68fc14e5f73`에서 동일 `codex/newsflow-core-production` / Draft PR #34를 이어갔습니다.
- Instagram의 주입되지 않은 authorization backend를 **실제 HTTPS 인증 중계 클라이언트 + 별도 ASGI 인증 서버**로 연결했습니다. Facebook Login for Business authorization-code 경로만 사용합니다. Windows 배포본에는 공유 App Secret이 없습니다.
- state·code·결과 전달 1회 처리, 앱 인스턴스의 메모리 verifier 결합, 짧은 만료, 취소, 앱 ID·권한·프로 계정 확인과 기존 DPAPI 저장을 연결했습니다. Page가 하나여도 사용자가 직접 선택합니다. 기존 계정 재연결도 제공합니다.
- 중계는 로그인에만 사용합니다. MP4는 기존 공식 플랫폼 어댑터가 직접 전송하며 인증 서버는 보관하거나 전송하지 않습니다.
- 작업실에서 같은 완성 영상에 **YouTube / Instagram / YouTube + Instagram**을 선택하고, 공통 내용·출처·권리·AI 표시 검토 후 명시적으로 게시합니다. YouTube는 기본 비공개, Instagram은 별도 공개 게시 동의가 필수입니다.
- 기존 플랫폼 서비스를 조정하는 작은 공통 서비스가 플랫폼별 작업·성공·실패·결과 불명을 별도로 보존합니다. 한쪽 성공 후 다른 쪽을 이어가도 성공한 플랫폼의 인증·전송·게시는 반복하지 않습니다. 처리 대기는 다음 사용자 실행에서 상태를 확인하며, 실패·결과 불명은 자동 재시도하지 않습니다.
- 기존 SQLite `PublishEvidence`를 재사용합니다. migration 추가·수정 없음. 계정 연결은 제작·MP4 저장의 선행 조건이 아닙니다. 기존 상세 URL과 A/B 서비스는 유지했습니다.

## 검증

- C 변경 영역: 인증 중계 서버, Windows 클라이언트, 공통 게시 서비스, 작업실 GUI만 Fake 검증합니다. 기존 A/B 전체 회귀는 반복하지 않습니다.
- 실제 클라이언트 → 실제 중계 ASGI 라우트 → Fake Meta → 계정 선택 → 기존 계정 검증/보호 저장 계약 테스트 포함. 취소·만료·재사용·불명 결과·동시 요청·플랫폼별 중복 차단을 확인했습니다.
- 로컬 Python 3.14에서 작성 중 범위 테스트 및 Ruff/pip check PASS. GUI 15개는 처음 13 PASS/2 FAIL(테스트의 잘못된 기존 URL·버튼 문구), 그 두 항목 수정 후 2 PASS입니다. 제품 실패를 숨기거나 테스트를 skip하지 않았습니다.
- 격리 서버 `127.0.0.1:8796`의 합성 계정·DB·파일로 앱 내 브라우저에서 두 플랫폼 선택 → 검토 저장 → 하나의 게시 버튼 → YouTube 완료/Instagram 처리 대기 → Instagram만 후속 실행 대상으로 표시됨을 확인했습니다. 외부 통신을 차단한 Fake 어댑터이며 실제 로그인·업로드 증거가 아닙니다. 임시 서버와 탭은 종료했습니다.
- 로컬 화면 증거: `validation-output/unified-publishing-ui-20261017/partial-result.png` (Git 미포함). 이 단계에서 영상 품질·실제 재생을 다시 검증하지 않았습니다.
- Windows Python 3.12/3.14 CI: 최종 결과는 아래에 기록합니다.

## 보존과 미검증

- 운영 8765 프로세스 재시작 없음. 운영 DB·OAuth 토큰·API Key·설정·기존 MP4에는 접근·수정하지 않았습니다. 검증은 별도 임시 데이터만 사용했습니다. 새 운영 데이터 해시나 무결성 검사를 수행한 것으로 주장하지 않습니다.
- 검색·분석·TTS·FFmpeg·비용 처리 코드는 변경하지 않았습니다. 요청별 금액 한도와 추측 기반 예약을 다시 추가하지 않았습니다.
- 실제 Meta/Google 로그인, 토큰 교환, 업로드·공개 게시, 유료 AI 및 Claude Code/Codex CLI 테스트 **0건**. 실계정 게시와 전체 실사용 결과는 **NOT VERIFIED**입니다.
- **구현상 authorization backend 부재는 해소**했습니다. 운영 연결은 HTTPS 인증 서비스 배포, Meta 앱/최소 권한 구성, 정확한 callback, 서버 비밀 관리, 해당 Page/Instagram 권한이 준비되어야 가능합니다. 배포 대상에 따라 App Review·Advanced Access·Business Verification도 필요합니다.
- 배포 절차와 공식 근거는 [인증 중계 준비 문서](../INSTAGRAM_AUTH_RELAY.md)에 있습니다. 단일 worker·최대 10분 인증 세션을 사용하며 서버 재시작은 미완료 로그인을 무효화합니다. 첫 응답의 최대 100개 Page를 지원합니다. 앱/프록시/업스트림 로그에서 callback query·Authorization·토큰·App Secret을 수집하지 않는 구성이 필수입니다.
- 다음 필수 작업은 운영자 인프라·Meta/Google 앱 조건 준비 후, 별도 사용자 승인 범위에서 실제 계정 연결과 동일 MP4의 두 플랫폼 게시를 확인하는 것입니다. C 이후 새 기능 개발은 하지 않습니다.

## 변경 범위 및 Git

- 인증: `oauth/instagram.py`, `oauth/instagram_relay.py`, `oauth/relay_server.py`
- 통합: `publishing/unified.py`, `main.py`, `gui/unified_publishing_routes.py`, `gui/instagram_routes.py`
- 화면: 기존 작업실/설정 템플릿·라우트, `unified_publish.html`, `publish_workspace.js`, 기존 `app.js`
- 검증/문서: C 전용 테스트 4개, Windows C 워크플로, 인증 중계 배포 안내와 이 보고서. B CI는 수동 실행으로 보존하여 C push가 B 전체 테스트를 반복하지 않게 했습니다.
- 기존 PR #1~#33·main 변경/병합 없음. 신규 PR 없음. [Draft PR #34](https://github.com/jsbae1979-prog/JSBAE/pull/34)를 유지합니다.
