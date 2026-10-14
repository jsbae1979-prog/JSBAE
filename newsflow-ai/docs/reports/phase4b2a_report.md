# NewsFlow AI — Phase 4B-2A 보고서

이 문서는 Draft PR 검증 중 갱신됩니다. Windows 결과와 Git SHA는 실제 실행 완료 후 기록합니다. 실제 Google/Instagram 로그인, OAuth 토큰 발급·저장, SNS 업로드·게시 및 Phase 4B-2B는 실행하지 않습니다.

## 1. 기준 및 구현 범위

- 저장소: `jsbae1979-prog/JSBAE`, 프로젝트: `newsflow-ai/`.
- 승인 기준: Phase 4B-1 `4bce0c70af7f17af4904120866c4b46eae8c4ca2`, PR #5.
- 작업 브랜치: `feat/newsflow-phase4b2a`, base: `feat/newsflow-phase4b1`.
- 운영 환경: Windows 11, Python 3.12, `127.0.0.1:8765`, `%LOCALAPPDATA%\NewsFlowAI`.

YouTube Desktop client 설정 검증, dormant 시스템 브라우저와 공식 HTTPS transport, Authorization Code + PKCE S256, state·callback·만료·재사용 검증, token response·scope 검증, 명시적인 refresh/revoke, 결과 불명 차단과 계정별 grant 결합을 구현했습니다. 실제 transport·브라우저·credential 실행은 production activation에서 차단합니다. Instagram의 미확인 로그인 방식은 BLOCKED로 유지합니다.

## 2. OAuth 아키텍처

`YouTubeOAuthAdapter.configured_protocol()` → `GoogleOAuthProtocol` → `GoogleHTTPSOAuthTransport`/`GoogleSystemBrowser`는 비활성 운영 경로입니다. 모든 실행 진입점이 `require_production_activation()`에서 거부되며 환경변수·GUI 플래그를 입력받지 않습니다. 테스트는 별도의 `SyntheticLoopbackTransport`와 실제 loopback Fake HTTP 서버에서만 수행합니다. 합성 코드·token/client secret 식별자를 강제하고 official endpoint, 임의 transport, 자동 redirect 또는 시스템 브라우저 사용을 허용하지 않습니다.

`youtube.upload`만으로 계정 identity를 확인하지 않습니다. 발급 grant 전체의 access·refresh·expiry·scope 결합을 확인하여 다른 계정의 refresh token을 섞거나 승인 범위를 바꾼 요청을 전송 전에 거부합니다. callback 및 교환 요청은 일회성이고 refresh 결과 불명 상태는 재시도·identity 사용을 차단합니다. 실제 identity 조회 adapter 및 callback HTTP dispatch는 후속 활성화 전 조건입니다.

## 3. 공식 OAuth 문서 및 Provider별 범위

공식 URL·확인 날짜·본문 근거는 [조사 자료](phase4b2a_evidence/oauth_official_sources.json), [Cloud 공개 문서 조회](phase4b2a_evidence/cloud_official_docs.json), [OAuth 운영 설계](../oauth_production.md)에 보존합니다. Cloud 공개 문서 GET은 프록시 제한으로 NOT VERIFIED입니다. 공식 유지보수 GitHub 소스에서 Google endpoint/S256 및 YouTube scope 정의를 확인했으며 실행하지 않았습니다. Windows의 현재 primary document 결과는 검증 후 추가합니다.

Instagram Login과 Facebook Login의 계정 유형, 최소 scope, redirect, 앱 검수, exchange/refresh/revoke 및 identity는 공식 근거가 확보되기 전 NOT VERIFIED입니다. Instagram은 Google 구현을 상속해 사용하지 않고 실제 endpoint·scope 미설정을 유지합니다.

## 4. Windows CredentialVault 보안 검토

기존 synthetic-only DPAPI는 변경하지 않았습니다. 별도 `ProductionCredentialBoundary`는 실제 backend 생성 전 저장·조회·교체·삭제·복구를 차단합니다. production backend는 계약과 활성화 선행 조건만 제공하며 실제 토큰 저장 구현·실행을 완료로 주장하지 않습니다.

`SyntheticCredentialBoundaryKernel`에서 account key·합성 identity digest·opaque reference 격리, 작업 예약, revision CAS, 암호문 재조회, 일회성 완료, 이전 reference 정리 및 fail-closed 복구를 검증합니다. migration 0006의 journal에는 비밀 원문이 없습니다. 재시작 복구는 원자적 DB metadata 격리만 수행하고 provider·vault를 호출하지 않습니다. 복구가 이미 완료된 작업이나 현재 credential을 삭제하지 않도록 단계 및 CAS를 구분합니다.

SQLite와 파일시스템 전체를 하나의 원자적 트랜잭션으로 주장하지 않습니다. 파일 작성 후 reference 이력 저장 전 강제 종료는 orphan ciphertext를 남길 수 있습니다. Python immutable 문자열의 확정적 메모리 삭제, 같은 사용자 악성 프로세스의 격리 및 실제 production vault 운영은 NOT VERIFIED입니다.

## 5. Cloud 전체 회귀 및 GUI

명령: `.venv/bin/python -m pytest -q -rs --junitxml=/tmp/newsflow-phase4b2a-cloud-pytest.xml`.

최종 결과는 실행 완료 후 기록합니다. 초기 전체 검증의 fixture 등록 및 migration 이전 도구 실패를 수정했습니다. 실패는 PASS로 처리하지 않았습니다.

실제 FastAPI 서버와 Chromium에서 RSS 등록/활성화/수집 POST, 검색, AI·Video·Publishing POST, disabled OAuth 버튼, 위조 시작 423, 새 readiness 상태, SQLite 저장·재시작 유지, 중복 실행·포트 충돌 및 모바일 overflow를 확인했습니다. [Cloud 브라우저 evidence](phase4b2a_evidence/cloud_result.json), [화면](phase4b2a_evidence/oauth_studio.png).

## 6. Windows Actions 전체 회귀

NOT VERIFIED — 실행 대기. 새 workflow는 `windows-latest`, Python 3.12, 새 feature 브랜치만 대상으로 하고 실제 API 키나 OAuth 계정 정보를 등록하지 않습니다. native DPAPI와 새 boundary의 합성 회전·계정 격리, 전체 pytest, 실제 BAT/server/health/LOCALAPPDATA/SQLite/브라우저 POST를 실행합니다.

## 7. 실제 OAuth·SNS 호출 0건 증거

실제 인증·token exchange·refresh·revoke·identity API·service credential 저장 및 SNS 업로드·게시: 0건. 근거는 unconditional production gate, official transport/browser 직접 호출 차단 테스트, backend factory 미호출, Fake HTTP 서버에서의 합성 request assertions, GUI forged start 423, 외부 브라우저 request origin 빈 목록, DB account `not_connected`/`api_ready=false`/credential 미생성 및 PublishJob/Attempt 0건입니다. structural safety 응답은 전체 기기의 독립 네트워크 계측기로 주장하지 않습니다. 공개 공식 문서 GET과 Fake loopback HTTP는 실제 OAuth 호출로 집계하지 않습니다.

## 8. 미검증·보안상 남은 위험 및 실계정 선행 조건

실제 Google/Instagram 로그인·token 발급·저장, 실제 앱 등록/계정 권한/앱 검수, 실제 SNS 게시, 사용자 Windows 11 PC 운영, 기존 실제 RSS·AI API, 한국어 TTS 및 완성 영상의 사람 품질 검토는 모두 NOT VERIFIED입니다. 샘플 MP4와 자동 DPAPI 검증은 위 항목의 대체 검증이 아닙니다.

실계정 활성화에는 사용자 후속 승인과 검토 가능한 production activation 코드 변경, Google Desktop 앱/동의 화면/최소 scope 및 채널 identity 검증, 정확한 callback dispatch, Instagram 공식 로그인 정책 확정, 별도 current-user production backend·orphan 관리·실패/회수 복구 검증이 필요합니다. OAuth 연결 승인은 SNS 게시 승인으로 해석하지 않습니다. CSRF/SSRF/TLS/CSP와 Publisher 차단을 완화하지 않았습니다.

## 9. 변경 파일 및 Git

변경은 `newsflow-ai/`와 해당 단계의 새 Windows workflow에 한정합니다. 주요 파일: `oauth/activation.py`, `oauth/production.py`, `oauth/production_vault.py`, provider integration, DB model/migration 0006, startup recovery, data migration allowlist, Publishing readiness/API/template, 테스트 fixture·protocol/binding/vault/GUI/activation, 공식 문서 collector, CI harness, README/AGENTS/architecture/공식 연구 자료 및 이 보고서입니다. 기존 migration 0001~0005 및 synthetic-only vault는 변경하지 않았습니다.

Git SHA 및 실제 Draft PR 번호는 생성 후 기록합니다. 기존 PR #1~#5와 main을 병합하거나 수정하지 않습니다.

## 10. Phase 4B-2B 진입 여부 및 중단

Phase 4B-2B 실제 운영 승인: NOT VERIFIED/미승인. 이번 단계는 비활성 OAuth 코드와 합성 검증의 검토 대상입니다. 실계정 선행 조건을 해소하고 사용자가 다음 단계를 명시적으로 승인하기 전 연결·token 발급·저장·업로드·게시를 실행할 수 없습니다. 완료 보고서 및 Draft PR 제출 후 개발을 중단합니다.
