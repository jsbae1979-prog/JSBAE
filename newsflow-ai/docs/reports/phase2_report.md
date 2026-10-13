# NewsFlow AI — Phase 2 AI News Intelligence

## 판정 및 범위

Phase 1/1A 승인 기준 bd9df6d에서 별도 `feat/newsflow-phase2` 브랜치로 개발했습니다. Windows 11 전용 운영 구조, 기본 127.0.0.1:8765, 기존 Phase 1 PR #1과 main을 보존합니다. Phase 3·영상 제작·SNS 게시·main 병합은 수행하지 않습니다.

| 항목 | 결과 | 근거/제약 |
|---|---|---|
| Cloud 전체 pytest | PASS | `python -m pytest -q -rs`: 107 passed / 1 skipped / 1 warning / 0 failed |
| 기존 Phase 1 회귀 | PASS | 기존 73개 테스트 유지, DB revision 기대값만 0002로 갱신 |
| 뉴스 분석·그룹화·출처 비교 | PASS | RSS 근거/점수 snapshot, 0.65 제목 유사도 후보, Offline/Fake 검증 |
| Provider와 API 오류·타임아웃 | PASS | Offline/Fake, OpenAI 고정 HTTPS 요청을 mock 검증 |
| 30/45/60초 대본 | PASS | 구조·필드 길이·장면 길이 합계 검사, 출처 보존 |
| 초안 저장·수정 | PASS | 불변 출처, revision 조건부 UPDATE, 검토 필요 상태 |
| 실제 AI API | NOT VERIFIED | 실제 키 사용·유료 API 호출 없음 |
| 실제 RSS | NOT VERIFIED | 기존 미검증 상태 유지; live opt-in 테스트 1개 skip |
| Windows 11 사용자 PC 운영 | NOT VERIFIED | 수동 PC 설치·네트워크·권한·보안 제품·Ctrl+C 미검증 |
| Phase 2 Windows Actions | NOT VERIFIED | 업로드 후 실행 결과를 아래에 갱신 |
| 실제 Cloud Chromium | PASS | 실제 서버에서 등록·수집·AI 분석·45초 대본·필드 편집 POST, 모바일·재실행 후 초안 유지 |

## 구현 및 아키텍처

GUI와 서비스·DB·Provider를 분리했습니다. AI Studio에서 기사 1~10개 선택, 분석 Provider 선택, 분석 근거/출처/미확인 사항 확인, 30/45/60초 대본 생성, 필드별 수정·저장·목록 조회와 실행 이력/오류 확인을 제공합니다. 기존 Dashboard/News Explorer/Settings 기능은 유지합니다.

Offline은 실제 AI 결과가 아닌 RSS 근거 설명과 편집용 기본 대본입니다. OpenAI는 분석·대본 생성 모두 명시적 Provider 선택 및 해당 실행의 외부 전송/비용 동의가 있어야 호출합니다. 모델/temperature/timeout/max_tokens는 설정 가능하며 옵션과 Provider를 실행 이력에 저장합니다. 실제 조회수·검색량을 측정하지 않고 기존 내부 추천 점수 및 미평가 항목을 그대로 보존합니다.

기사별 제목/RSS 요약(최대 800자)/발행시각 또는 NULL/카테고리/대표 및 중복 출처 링크/점수 근거를 snapshot으로 저장합니다. 분석 비교는 선택 기사 ID를 빠짐없이 참조해야 하며 새로운 출처 ID는 거부합니다. 복수 출처 보도를 독립 검증이나 신뢰도로 해석하지 않습니다. 신뢰도는 미평가, 사실 확인은 unverified입니다.

DB migration 0002는 intelligence_runs와 content_drafts만 추가합니다. 0001과 기존 데이터를 수정하지 않습니다. 기존 데이터 이전 도구가 0001/0002를 허용하도록 보완했습니다. 원문 출처는 편집 불가이며 초안 수정은 revision으로 동시 편집 충돌을 감지합니다. 중단된 생성은 재기동 시 interrupted로 기록하고 자동 외부 재호출하지 않습니다.

## 보안·저작권

- PASS: 기존 CSRF/Origin(null 거부)/Host/SSRF/robots/TLS/HTML escape/CSP/no-referrer 정책 유지. GUI POST는 기존 same-origin fetch 방식을 사용합니다.
- PASS: API 키는 NEWSFLOW_AI_API_KEY 환경변수만 사용. 키 입력/출력 폼, DB 저장, Git 저장, 로그 출력 없음. 외부 오류 본문과 예외 텍스트는 저장/표시하지 않습니다.
- PASS: 고정 https://api.openai.com/v1/chat/completions, TLS 기본 검증, 리디렉션 거부, 유한 timeout, 입력 64KB/응답 128KB 제한. CI는 API 키 제거·합성 RSS·Offline만 사용.
- PASS: strict Pydantic schema, 장면 시간/길이/선택 출처 ID/키 재출력/일부 선정·확정 문구/100자 이상 연속 요약 복제 검사를 수행합니다. 검사는 사실·저작권 판정을 자동 보장하지 않습니다.
- PASS: 원문 본문 스크래핑/자동 SNS 게시/자동 승인 없음. 모든 초안은 사람 검토 필요 상태이며 화면에 미확인 보도와 저작권 주의사항을 표시합니다.
- NOT VERIFIED: 실제 외부 모델의 사실성·환각 방지 성능·출력 품질·실제 API 인증/과금·Windows 사용자 PC Secret/ACL 정책.

## 변경 파일

- src/newsflow/intelligence/{provider,schema,service,__init__}.py: Provider protocol, Offline/Fake/OpenAI, 엄격한 결과와 근거/초안 서비스.
- src/newsflow/db/models.py, db/migrations/versions/0002_intelligence.py: 분석·초안 테이블과 추가 migration.
- src/newsflow/gui/intelligence_routes.py, gui/templates/{ai,base}.html, static/css/app.css, main.py: AI Studio 메뉴/폼/결과/편집/오류와 앱 연결·중단 복구.
- src/newsflow/migrate_data.py, tests/test_database.py: 새 DB 버전 지원/기대값. 기존 회귀를 제거하거나 skip하지 않음.
- tests/test_intelligence.py: 신규 34개 테스트.
- tools/ci_validation.py: 실제 Chromium AI 분석·대본·수정 POST, 모바일 및 재실행 후 초안 유지 검사. 기존 Windows 검증 유지.
- .github/workflows/newsflow-phase2-windows.yml: Phase 2 브랜치 전용 Windows Python 3.12/전체 pytest/실제 BAT/Chromium 검증. Phase 1 workflow 수정 없음.
- AGENTS.md, pyproject.toml, .env.example, README.md, docs/architecture.md, 본 보고서와 evidence: 승인 범위/직접 Pydantic 의존성/Windows 운영·AI 사용 문서.

## 테스트 및 실행 구분

Cloud 명령: `.venv/bin/python -m pytest -q -rs`. 최종 결과 107 passed / 1 skipped / 1 warning / 0 failed. warning은 기존 FastAPI TestClient의 Starlette/httpx deprecation이며 숨기거나 실패 테스트를 skip하지 않았습니다. live RSS는 기존 opt-in이므로 별도 skip입니다. 새 34개 테스트는 Provider Fake/타임아웃/오류/외부 동의/키 미설정/키 비노출/JSON 검증/30·45·60초/미확인/출처 보존/복제 차단/초안 수정 충돌/GUI CSRF·escape/DB 업그레이드/중단 복구를 검증합니다.

개발 중 첫 회귀에서 데이터 이전의 0001 전용 검사 실패를 수정했습니다. pytest와 Chromium을 동시에 실행했던 중간 회귀에서는 기존 subprocess timeout 테스트 2개가 실패했습니다. 검사를 완화하지 않고 실행을 분리한 최종 전체 회귀가 통과했습니다. 모든 실패를 최종 PASS로 덮지 않고 원인과 재검증을 기록합니다.

## 미구현·제약 및 Phase 3 선행 조건

실제 AI/RSS/사용자 PC 운영 미검증. Offline 대본은 사람이 작성할 기본 템플릿이며 자동 맞춤 AI 분석을 대신하지 않습니다. 제목 유사도 후보는 날짜/수치가 다른 기사도 포함할 수 있으므로 동일 사건으로 확정하지 않습니다. 의미 기반 검색·자동 외부 팩트체크·출처 독립성 판정·실제 화제성 측정·작업 큐·자동 재시도·TTS/실제 영상 길이 측정·영상 렌더링·SNS/OAuth·게시 승인 기능은 미구현입니다. 계획된 장면 초 수는 실제 음성 길이 검증이 아닙니다. 유효한 JSON이나 금칙어 검사는 환각/저작권 위반을 모두 판별하지 못합니다.

Phase 3 진입 전 사용자 Phase 2 승인, 실제 Windows 11 운영 점검, 허가된 실제 RSS 및 AI API opt-in 검증, 모델/비용/출력 품질 평가, 사람의 사실·출처·소재 권한 검토 절차 확정이 필요합니다. Phase 3는 시작하지 않습니다.

## Git / PR 및 최종 증거

기준 bd9df6d. 별도 feat/newsflow-phase2. 새 Draft PR은 feat/newsflow-phase1을 base로 하는 의존 PR로 생성하여 Phase 2 변경만 검토할 수 있게 합니다. 기존 PR #1은 수정·병합하지 않습니다. main 변경 없음. 커밋/PR/Windows 결과는 실행 후 갱신합니다.

Cloud 실제 실행 명령: `.venv/bin/python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/phase2-final-cloud`. 서버 기동/종료, HTTP POST, SQLite 저장·재실행·조회, 중복/포트 충돌, Chromium 실제 same-origin POST, AI Studio 분석·대본·필드별 수정·초안 재기동 보존, 390px 모바일 overflow 없음 PASS. 이는 Linux Cloud의 실제 실행이며 Windows BAT 실행 또는 실제 AI/RSS 통신 검증이 아닙니다. [Cloud 결과](phase2_evidence/cloud_result.json), [pytest](phase2_evidence/cloud_pytest.txt), [AI Studio 화면](phase2_evidence/ai_studio.png), [모바일 화면](phase2_evidence/mobile.png).
