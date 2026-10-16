# Phase 5F.5 AI 뉴스 분석·대본 통합 자동화

기준 `515f9544dfa2df587a95b2bafeceef43d08a64a7`, 브랜치 `feat/newsflow-ai-news-automation`. PR #24의 화면과 기존 엔진을 재사용했다. 후속 단일 페이지 개편은 이 브랜치에 포함하지 않는다.

## 수집 정책과 구현 범위

추가 지시에 따라 **신규 기본값은 AI 웹 뉴스 조사**다. 기존에 명시적으로 저장한 RSS·체험 선택은 변경하지 않는다. `ai_web`, `rss`, `hybrid`를 구분하고, 웹 검색 차단·실패 시 RSS나 다른 Provider로 대체하지 않는다. 현재 웹 검색 경로는 모두 실행 차단 상태이며, 사용자가 RSS를 직접 선택한 경우 통합 제작이 가능하다.

| AI | 기사 분석·대본 | 웹 검색 | 인증·비용 |
|---|---|---|---|
| Claude Code | 기존 어댑터를 Autopilot에 연결 | NOT VERIFIED · 실행 차단 | 공식 구독 인증·본인 사용량, 요청별 전송 동의 |
| Codex | 기존 RSS 어댑터를 Autopilot에 연결 | BLOCKED 유지 | 기존 ChatGPT 인증·사용 가능량/격리 검사 |
| OpenAI API | 기존 분석·대본 재사용 | Responses 제품 지원 확인, 앱 실행 BLOCKED | 기존 API 키·승인·월 한도 유지; 검색은 별도 승인 필요 |
| Offline | 기존 로컬 분석·대본 | 미지원 | 외부 호출 없음 |
| Claude API | 신규 실행 Provider 미도입 | 공식 제품 지원, 앱 실행 BLOCKED | Code CLI와 별도 API 인증·비용 조건 필요 |

`NEWS_SEARCH`, `NEWS_ANALYSIS`, `SCRIPT_GENERATION` 계약은 설치·인증·실제 요청 성공과 구분한다. 공식 API 기능·가격·계정 제한은 [웹 검색 검토](phase5f5_web_search_review.md)에 기록했다. 실제 계정 권한·검색 비용 승인·검색 이벤트와 기사 URL 검증을 수행하지 않아 STEP 5는 BLOCKED다. 실제 AI 검색→분석→대본 완전 자동화는 완료로 표시하지 않는다.

## 기존 구조와 통합

- `AutopilotCoordinator`의 작업·시도·산출물·검토·복구 모델과 `PipelineBackend`, `IntelligenceService`를 재사용했다. DB migration은 추가/수정하지 않았다.
- 명시적 RSS 정책: 기존 `NewsService` 수집/중복 제거 → 최대 10건 비교·추천 → 같은 AI·모델로 선택 기사 대본 → 대본 검토 → 기존 음성/FFmpeg → 최종 검토.
- 뉴스 종류·30/45/60초·음성·모델·수집 정책·분야·기간·동의 시각·분석/대본 ID를 작업에 보존한다. 신규 통합 흐름의 기사 선택 중간 페이지를 생략하고 필수 대본·영상 검토는 유지한다.
- AI의 추천 ID는 실제 전달된 기사 중 하나여야 한다. 추천이 없는 기존/Fake 응답은 RSS 휴리스틱 선택으로 명시하며 AI 순위로 표시하지 않는다.
- 분석 전체 출처·비교·불확실성을 보존하고 대본에는 선택된 기사 근거만 전달한다. 이전 AI Studio 상세 편집 경로도 유지한다.

## 출처·기간·안전성

- 기존 공개 RSS URL/robots/DNS/TLS 정책과 canonical URL 중복 제거를 유지한다. Google RSS 차단을 우회하지 않으며 특정 RSS의 성공을 전체 출처 성공으로 일반화하지 않는다.
- 발행일 미상·미래·기간 밖 기사는 지정 기간의 제작 후보로 확정하지 않는다. 오늘은 한국 시간 자정 기준이며 원본의 미상 날짜를 생성하지 않는다.
- RSS 제목/요약 기반 분석과 원문 전체 확인·사실 검증·실측 인기도를 구분한다. 검색 후보를 실제 뉴스로 자동 저장하는 우회 경로는 추가하지 않았다.
- 외부 AI는 기사 최대 10건의 제목·요약(기사당 최대 800자)·URL·발행 시각 전달 및 분석 1회+대본 1회 사용량에 대한 요청별 동의를 받는다. 설정 저장/GET은 추론을 시작하지 않는다.
- OpenAI 기존 API 승인·예산을 검색 비용 승인으로 확대하지 않는다. 자동 제작 OpenAI 어댑터는 재시도하지 않는다. CLI는 작업 전용 인스턴스로 취소하며 다른 Studio 작업을 취소하지 않는다.
- 시작 요청 ID 중복 방지, 호출 전 ID 저장, 성공 결과 재사용, 실패/취소/결과 불명 요청 재전송 차단을 확인했다. 재시작 시 성공·실패·진행 중 결과를 구분한다.
- CSRF/Origin/CSP·DPAPI·출처/권리 검토·SNS 차단을 유지한다. 실제 유료 API·구독 추론·OAuth·SNS 호출은 0건이다.

## 검증

- 로컬 변경 영역: 기능/선택·출처 계약 48 passed, 새·기존 Autopilot 91 passed, GUI 관련 60 passed. 후속 요청 ID/동적 안내 수정은 해당 항목만 추가 확인했다. 숫자는 실행 묶음별이며 중복을 합산한 전체 테스트 수가 아니다.
- Windows Chrome 분리 서버: AI 웹 기본 BLOCKED → 자동 RSS 미실행 → RSS 직접 선택 → 두 요청 동의 → Fake 분석·대본 자동 생성 → 대본 검토 → 실제 Supertonic F1/FFmpeg 45초 영상 → 최종 검토 대기.
- Fake 서버는 실제 Claude/Codex/OpenAI 추론 메서드를 명시적으로 차단했다. 진단에서 Fake 연결·격리 데이터·실제 추론 차단을 확인했다. 화면의 Claude 경로 검증은 실제 계정 추론 성공을 의미하지 않는다.
- 샘플: `validation-output/phase5f5/ui-test-data/outputs/videos/video-5f5372108fe245b0b79d01970f79bd49.mp4`.
- 실제 재생·최종 Windows CI·데이터 보존 결과는 완료 시 추가한다.

## 변경 파일과 남은 범위

Autopilot `backend/contracts/service`, Intelligence `capabilities/provider/schema/service`, GUI `autopilot_routes/production_context/production_routes/production_status/task_views`, 홈·설정·작업·동의 템플릿과 `home_production.js`, 해당 테스트, 전용 Windows workflow, 보고서 2개.

실제 Claude/Codex 추론·계정 한도, OpenAI/Claude API 검색, Claude Code 일반 배포 약관, 사람의 발음·영상 품질은 NOT VERIFIED다. 새 음성 엔진·SNS·Phase 5G 개발은 수행하지 않았다. 단일 페이지 통합 UX는 별도 기준 브랜치에서 후속 작업한다.

## GitHub

최종 SHA·신규 Draft PR·Windows Actions 결과 기록 대기.
