# Codex 뉴스 조사 및 AI Studio 연동

검증일: 2026-10-16 · Windows 11 / Python 3.14.7. 기준 `d79b8b4926bcf8f08e48a0355a725dabba7831a3`.

## 결과와 사용 방법

- **Codex 연결·ChatGPT 구독 인증 및 RSS 분석·30초 대본 생성 성공. 웹 뉴스 조사는 BLOCKED.** 설치·로그인 성공을 웹 검색 성공으로 표시하지 않는다.
- AI Studio의 **Codex 연결 · RSS 뉴스 분석 → 설치·로그인 확인**으로 공식 CLI 상태를 확인한다. 기존 분석·대본 Provider 선택에서 `Codex` / 모델 `default`를 고르고 기본값을 저장한다. 저장·페이지 로드·선택만으로 추론하지 않는다.
- 기사 선택 → 매 실행 자료 전송·사용량 동의 → 분석 → 30·45·60초 대본 저장 → 사람이 검토 → 기존 Video Studio 순서다. 외부 응답은 미확인 초안이며 출처를 바꿀 수 없다.
- PR #19의 데이터 계약·Fake Research Provider를 선별 재사용했다. 해당 브랜치를 병합하지 않았고 기존 RSS 수집·중복 제거·IntelligenceService·ContentDraft·AIUsage·Video Studio를 재사용했다. migration·의존성 변경 없음.

## 공식 연결·권한·비용

공식 근거: [App Server](https://developers.openai.com/codex/app-server), [인증](https://developers.openai.com/codex/auth), [웹 검색](https://developers.openai.com/codex/web-search), [설정](https://developers.openai.com/codex/config-reference).

- 사용자가 설치한 공식 CLI의 `app-server --listen stdio://`와 공식 RPC를 사용한다. `account/read`의 ChatGPT 인증 및 `account/rateLimits/read`의 사용 가능 상태를 확인한다. 인증 파일·쿠키·세션 토큰을 읽거나 복사하지 않는다.
- 검증 CLI는 **0.163.0-alpha.10.2**다. 실험적 App Server의 도구 의미가 달라질 수 있어 다른 버전은 격리 재검증 전 차단한다. CLI 자체의 기존 공식 인증 위치는 유지하고 API 키·토큰 환경변수는 자식 환경에서 제외한다. API 키 방식·사용량 확인 실패는 차단하며 다른 유료 Provider로 전환하지 않는다.
- 임시 작업 폴더, ephemeral thread, read-only, approval never, RSS 경로 web search disabled. shell·MCP·hooks·plugins·skills·agents·browser·computer-use·code-mode 등을 비활성화하고 유효 설정과 thread 응답을 검증한다. 알 수 없는 도구 이벤트·승인 요청은 거절하고 중단한다. 뉴스에 포함된 지시문은 자료로만 전달한다.
- 본인 구독 사용량·호출 제한이 적용된다. 별도 API 키 호출은 0건이며 무료·무제한을 보장하지 않는다. 로컬 토큰 기록은 계정 잔여량·청구량이 아니다. App Server에는 이 화면의 OpenAI 출력 토큰 상한이 적용되지 않음을 안내한다.
- 요청당 시간 제한, 한 작업 동시 실행, 취소·interrupt, 고정 오류 문구, 응답 크기·JSON 스키마 검증을 적용한다. 실패 요청 자동 재전송·공급사 자동 전환은 없다. 이미 발생한 사용량은 취소해도 되돌아가지 않는다.
- 이는 NewsFlow 요청 재전송 제한이다. `unbounded_connection_retries=false`를 실제 유효 설정에서 확인했다. 공식 CLI는 예약된 `model_providers.openai` 재정의를 거부하여 내부 request/stream 재시도 횟수를 0으로 강제하지 못했다. 임의 Provider나 endpoint로 바꾸지 않았으며 **제한된 내부 통신 재시도 및 이미 발생한 구독 사용량은 별개**임을 화면에 안내한다. 오류 주입으로 실제 공급사 재시도·청구 결과를 재현하지 않았다.

## 실제 실행 증거

- **웹 검색 1회:** 모델 `gpt-6.1-sol`, 완료된 webSearch 이벤트 **0건**, 유효 기사 결과 없음, `ai_bad_response`로 차단. 로컬 보고 토큰 8,100. 반복 호출하지 않았다. 정확한 공급사 측 검색 미실행 원인은 확인되지 않았으며 권한 미지원이라고 단정하지 않는다. 웹 조사 GUI·DB 자동 반영은 활성화하지 않았다.
- **RSS:** 기본 Google RSS는 기존 robots 정책에 따라 차단했다. 기존 공개 피드 검토 대상 BBC 코리아 RSS를 같은 PublicRSSAdapter로 확인하고 1건만 기존 NewsService로 저장했다. 원문 본문 수집·정책 우회 없음.
- 기사 #9: BBC 코리아, [‘중국 여행 자제하세요’…한국 정착 탈북민들이 ‘주의 문자’ 받는 이유는?](https://www.bbc.com/korean/articles/cxly4m2v3934o?at_medium=RSS&at_campaign=rss). RSS 제목·요약·출처만 근거로 사용했으며 독립적인 사실 검증 완료로 취급하지 않는다. 추가한 피드는 자동 수집 비활성 상태다.
- **실제 Codex 분석 #5 SUCCESS → 30초 초안 #3 SUCCESS.** 장면 합계 30초, 원문 출처·review_required 보존. RSS 분석과 대본 생성 각각 1회, 웹 검색 이벤트 0건으로 RSS 분석임을 명시했다. 로컬 보고 토큰 6,127 + 6,648. NewsFlow가 제출한 추론 요청은 총 3회(실패한 웹 1회 포함)이며 이후 추가 추론하지 않았다.
- 원시 모델 출력·계정정보를 보고서/Git에 싣지 않았다. 로컬 검증 JSON·SQLite 백업은 Git 무시 경로 `validation-output/codex-integration`에만 있다.

## 핵심 검증 및 보존

- 로컬 초기 핵심 검증: 어댑터 52, 연구 계약·검색 증거 37, Studio·Claude 연결 29, 추가 RSS→대본→Video Studio 통합 1개 통과. 전체 pytest는 반복하지 않았다.
- 무제한 내부 연결 재시도 차단을 추가한 뒤 설정 관련 11개만 재검증했고 통과했다. 변경 후 공식 CLI metadata-only 격리 검증 성공, 추론 0회.
- Fake 검증: 인증·구독 한도 실패, 미검증 CLI/설정 차단, 응답 JSON, 취소·timeout·중복 작업, CSRF/Origin, 설정 재시작 보존·추론 미실행, RSS 중복 제거, 30·45·60초 초안과 출처·검토 상태, 기존 Claude 미호출·설정 보존.
- 기존 `run.bat`과 LocalCache 데이터 경로로 실제 실행, 기본값 `Codex / default` 저장, 정상 종료·재시작 후 복원을 확인했다. 내장 브라우저에서 공식 연결 준비 완료(20:53 KST), 분석 #5·초안 #3·기존 Video Studio로 전달된 3개 장면을 확인했다. 저장·재시작·상태 조회 후 Codex AIUsage는 기존 2건으로 증가하지 않았다. 별도 Chrome 검증은 수행하지 않았다.
- SQLite `quick_check=ok`. 기존 기사 8·초안 2·영상 프로젝트 2·렌더 작업 2·AI 실행 4건의 원래 행이 백업과 동일하며 기존 MP4 2개 SHA-256도 동일하다. 새 RSS 기사 1·초안 1·AI 실행 2건만 추가했다. 앱 설정 변경은 AI Studio Provider/Codex 모델뿐이며 Claude 모델 및 다른 설정은 보존했다.
- 재시작 중 열려 있던 브라우저 탭이 연결 거부 오류 화면에 남아 새 탭으로 결과를 확인했다. 서버는 127.0.0.1에만 바인딩되며 시스템 정책·LAN 설정 변경 없음.

## 변경 파일과 게시 기록

- 연결: `intelligence/codex.py`, `intelligence/service.py`, `intelligence/settings.py`, `research.py`.
- 화면: `gui/intelligence_routes.py`, `gui/templates/{ai,claude_connection,codex_connection}.html`, `static/js/{app,codex_connection}.js`.
- 테스트: `tests/test_codex_{adapter,research,search_evidence,studio}.py`, 전용 Windows workflow 및 본 보고서.
- 브랜치: `feat/newsflow-codex-research-integration`. PR base: `feat/newsflow-claude-onboarding`. 기존 PR #1–#21과 main 변경 없음.
- 최종 검증 코드 SHA·Draft PR·Actions 결과: 게시 후 기록.

## 미검증

- 실제 웹 검색 성공·기사 교차 검증·웹 결과 자동 저장은 미검증/차단 상태다.
- 45·60초 실제 Codex 추론은 추가 사용량을 피하기 위해 실행하지 않았고 Fake 계약으로 검증했다.
- 새로운 TTS·MP4 제작, 사람의 영상·대본 품질 평가, 실제 계정 만료·사용 한도 소진·네트워크 중단 상황은 실계정으로 재현하지 않았다.
- 개인 PC의 공식 인증 성공을 모든 계정·CLI 버전·상업 배포의 지원 보장으로 확대하지 않는다.
