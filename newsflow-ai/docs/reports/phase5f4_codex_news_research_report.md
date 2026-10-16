# Phase 5F.4 Codex 뉴스 조사 — BLOCKED

2026-10-16 · Windows 11 / Python 3.14.7 · 기준 `e2904c6335954c7fb71becf02dc4c94c059bcd43`

## 판정 및 실제 실험

공식 연동 경로는 존재하지만 이 PC에서 실제 뉴스 검색 성공을 확인하지 못했다. 사용자 지정 선행 조건에 따라 GUI·DB 연동을 시작하지 않았다. 실서비스 기능 완료가 아니다.

- 공식 설치된 Codex CLI `0.163.0-alpha.10.2`의 App Server stdio JSON-RPC 사용.
- `account/read`에서 ChatGPT 인증, `account/rateLimits/read`에서 일반 사용 가능 상태 확인. 인증 파일·쿠키·토큰 추출/복사 없음.
- ChatGPT 구독 추론 2회: 최초 실험 후 클라이언트의 대기 중 알림 누락을 수정하여 1회 재확인. API 키 기반 호출은 하지 않았다. 정확한 사용량 및 청구액은 확인하지 못했다.
- 일회성 스레드, 읽기 전용, 명령 실행·앱·플러그인·MCP·hooks 비활성화, 승인 요청 거절, 제한 시간 120초. 설치 버전의 read-only 정책은 읽기 경로를 세밀하게 제한하는 보장을 제공하지 않는다.
- 재확인 결과: turn completed, 실제 `webSearch` 이벤트 **0건**, 구조화 응답 `{"articles":[]}`. 명령 실행/파일 변경/MCP 실행 이벤트 없음.
- 원인 미확정: 모델·계정·런타임·도구 제공 조건을 추가 확인해야 한다. 공식 웹 검색 전체가 미지원이라고 단정하지 않는다. 추가 추론 반복 중단.
- 실제 뉴스 결과, 원문 확인, GUI 동선, DB 저장, AI Studio 전달: **NOT VERIFIED / NOT IMPLEMENTED**.

실험 스크립트와 비밀정보를 제외한 진단은 로컬 ignored `validation-output/phase5f4/`에만 남겼다. 인증정보나 사용자 데이터는 커밋하지 않았다.

## 공식 경로 및 비용

| 항목 | 확인 결과 |
|---|---|
| SDK | 공식 TypeScript SDK로 로컬 스레드 제어 가능. Python 애플리케이션은 App Server JSON-RPC 연결 설계가 적합하다. |
| App Server | 인증 상태·한도 조회, 스레드, 진행 이벤트, outputSchema 및 취소 지원. JSON 형식 성공만으로 검색 성공을 판정하면 안 된다. |
| ChatGPT 인증 | 공식 Codex 로그인 경로로 구독 사용 가능. 별도 API 키는 이번 실험에 필요하지 않았다. 일반 배포 앱의 Sign in with ChatGPT는 별도 등록·동의·지원 조건 검토 필요. |
| 웹 검색 | 공식 도구가 존재하지만 해당 계정/모델/런타임 제공 조건 확인 필요. 이번 실험에서는 실행을 입증하지 못했다. |
| 한도/과금 | 구독 포함 사용량도 제한되며 다른 Codex 사용과 공유될 수 있다. 무료·무제한이라고 표시하지 않는다. 추가 크레딧 구매나 API 키 경로로 자동 전환하지 않는다. |

공식 문서: [SDK](https://learn.chatgpt.com/docs/codex-sdk), [App Server](https://learn.chatgpt.com/docs/app-server), [인증](https://learn.chatgpt.com/docs/auth), [웹 검색](https://learn.chatgpt.com/docs/web-search), [가격](https://learn.chatgpt.com/docs/pricing), [구독 로그인](https://learn.chatgpt.com/docs/sign-in-with-chatgpt), [OSS 앱 인증](https://developers.openai.com/siwc/token-sharing-open-source), [Preview 제한](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## 구현 및 재사용

- `src/newsflow/research.py`: 엄격한 요청/출처/조사 결과/30·45·60초 대본 계약. 기존 Script/Scene과 RSS URL 정책 검사 재사용. 알 수 없는 발행일은 null 유지.
- Fake Provider는 `[합성]`, example.com fixture, `synthetic=true`로 명시. DB·GUI·네트워크·인증·명령 실행 연결 없음. 실서비스 Provider는 항상 BLOCKED 예외로 종료.
- URL 검사는 형식/안전 정책 검사만 한다. 기사 존재·언론사 소유·교차 확인·순위를 증명하지 않는다. 합성 결과를 실제 뉴스로 가져오는 기능 없음.
- `tests/test_codex_research.py`: 계약 왕복, 개수/필드/시각/대본 길이, 위험 URL, 중복 fixture, 합성 표시 및 차단/취소 검증.
- `.github/workflows/newsflow-phase5f4-windows.yml`: Python 3.12/3.14 고정 의존성 설치, pip check, 변경 영역 Ruff·테스트만 실행. 실제 Codex·뉴스·유료 API 호출 없음.
- 기존 RSS/AI/Video Studio/SAPI/FFmpeg/SQLite/DPAPI/보안·migration은 변경하지 않았다. Phase 5F.3은 별도 브랜치와 PR #18에 보존되어 있으며 본 브랜치에 혼합하지 않았다.

## 후속 설계 — 미구현

실제 검색과 출처 확인이 성공한 뒤만 GUI·DB 구현을 재개한다. 분야 6개, 기간 3개, 개수 5/10/20을 기존 GUI에 추가하고 사용자 검토 후 기존 AI Studio/Video Studio로 전달한다. 자동 게시하지 않는다.

조사 전 구독 한도와 과금 불확실성을 안내하고 명시적 실행 동의를 받는다. 한도 조회 실패·인증 실패·추가 비용 가능 시 차단한다. 동시 작업 1개, 일일 횟수 상한, 요청 지문 중복 방지, 120초 제한과 명시적 취소를 적용한다. 타임아웃·결과 불명은 자동 재시도하지 않고 사용량 상태를 보수적으로 보존한다. 취소가 비용 환불을 뜻하지 않는다. 로컬 카운터를 공급사 청구량으로 표시하지 않는다.

외부 명령 요청은 거절하고 조사 텍스트는 실행하지 않는다. 원문 URL은 기존 DNS/public-address/redirect 정책으로 별도 확인하고 출처·발행 시각을 대조한다. 확인 불가 내용은 검토 대기 후보로 둔다. 인기 측정 자료가 없으면 순위 없음. 기존 NewsService canonical/similar-title 중복 제거를 공유하도록 공통 저장 경계를 정리하되 기존 migration은 수정하지 않는다. 본 단계에서는 이 저장 경계를 구현하지 않았다.

## 검증 및 미검증

- 로컬 Python 3.14: **19 passed**, Ruff PASS, pip check PASS. 기존 Starlette/httpx deprecation 경고 1건, 의존성 변경 없음.
- Windows Actions 최초 실행에서 Python 3.12 러너의 사전 설치 pipx/filelock 충돌로 pip check 실패. 기존 Windows workflow의 전용 venv 격리를 적용하여 해당 CI 영역만 재검증한다. 고정 의존성 변경 없음. 결과는 최종 기록에서 갱신.
- 전체 회귀·GUI·MP4·DB 쓰기 테스트는 실행하지 않음. 실서비스 인증 실패/한도/타임아웃/취소는 구현·검증되지 않았으며 Fake 취소 테스트로 대체했다고 주장하지 않는다.
- 사용자 데이터/기존 MP4/설정 파일 변경, 실제 유료 API, OAuth/SNS 게시, 관리자 권한 상승, 실행 정책 변경, main 병합 없음.
- Windows 재검증: Python 3.12/3.14 각각 핵심 19 tests, Ruff, pip check **SUCCESS**. [Actions 38881022468](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38881022468). 최초 실패 후 원인 수정 1회, 성공 후 반복 없음.
- 검증 코드 SHA: `10a7c7a89d08fa197a5051b758d613af5e22f04d`. 이후 보고서만 갱신하며 최종 HEAD는 완료 메시지에 기재한다.
- 브랜치 `feat/newsflow-phase5f4` · [Draft PR #19](https://github.com/jsbae1979-prog/JSBAE/pull/19), base `feat/newsflow-phase5f2`. 기존 PR/main 변경 없음.
