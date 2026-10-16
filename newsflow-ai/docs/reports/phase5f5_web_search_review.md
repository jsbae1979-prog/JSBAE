# Phase 5F.5 공식 웹 검색 API 검토

검토일: 2026-10-16. 공식 문서와 기존 소스만 읽었다. API 키·세션 파일을 열거나 계정별 모델 조회, 검색, 추론을 실행하지 않았다.

## 판단

OpenAI Responses와 Claude Messages API의 웹 검색 **제품 지원은 확인**했다. 그러나 NewsFlow에서 사용할 계정·모델 권한, 검색별 비용 승인·한도, 실제 검색 이벤트와 기사 URL은 **NOT VERIFIED**다. 따라서 이번 단계의 실제 API 웹 검색은 **BLOCKED**로 유지한다. 연결 성공이나 모델 목록 조회만으로 검색 성공을 표시하지 않는다.

사용자의 추가 지시에 따라 뉴스 확보의 기본 정책은 **AI 웹 조사 우선**이다. RSS는 사용자가 명시적으로 선택·저장한 보조 수집 경로이며 AI 검색의 자동 대체 수단이 아니다. AI 검색을 선택했으나 사용할 수 없으면 차단 사유와 필요한 승인을 표시하고 멈춘다. RSS 수집이나 체험 자료 사용으로 조용히 전환하지 않는다. AI 웹 조사와 RSS 보완의 결합도 별도 선택이 있어야 하며, 실제 수집 방식을 기사·작업에 구분해 남긴다. 실제 API가 막힌 상태에서는 Fake 검색 계약과 명시적으로 선택한 RSS 통합 경로를 검증할 수 있지만 이를 실제 AI 뉴스 검색 성공으로 보고하지 않는다.

| 경로 | 공식 기능 | 인증·과금 | 이번 단계 |
| --- | --- | --- | --- |
| OpenAI API | Responses의 `web_search` | 프로젝트 API 인증, 모델 토큰 및 검색 과금 | 문서 검토 완료; 실제 계정·검색 미검증, BLOCKED |
| Claude API | Messages의 서버 `web_search` | Claude Console API 인증, 모델 토큰 및 검색 과금 | Claude Code와 별개; 신규 실행 Provider 미도입, BLOCKED |
| Claude Code | 기존 제한된 CLI로 제공된 기사 분석·대본 | 기존 본인 계정 인증·사용량 | 뉴스 검색 미검증; 일반 배포 약관 적합성 NOT VERIFIED |
| Codex | 기존 RSS 자료 분석·대본 | 기존 ChatGPT 계정 인증·사용량 | 웹 검색 BLOCKED 유지; 재조사하지 않음 |

## OpenAI

새 통합에는 Responses `web_search`가 권장된다. 완료된 `web_search_call`과 검색 동작, 인용 URL 및 `web_search_call.action.sources`를 확인해야 한다. 검색을 선택 사항으로 두는 `tool_choice:auto`는 검색 0건일 수 있다. 결과의 출처 링크를 사용자가 볼 수 있게 표시해야 하며, 검색 인용만으로 기사 본문 전체·발행일·사실 확인 완료를 주장할 수 없다. 모델별 지원과 제한이 있으므로 저장된 모델 이름만으로 기능을 추정하지 않는다. [공식 웹 검색 문서](https://developers.openai.com/api/docs/guides/tools-web-search)

인증은 API 키 또는 공식 단기 워크로드 토큰을 사용하는 별도 API 경로다. 기존 Codex 로그인 파일을 추출해 사용하지 않는다. 프로젝트 인증·권한은 이번에 조회하지 않았다. [API 인증](https://developers.openai.com/api/reference/overview)

공식 표의 `web_search` 가격은 1,000회당 **USD 10**이며 검색 내용 토큰과 모델 입출력 비용이 추가된다. `gpt-4o-mini`·`gpt-4.1-mini`의 비프리뷰 검색 내용은 호출당 8,000 입력 토큰 묶음으로 청구된다. 무료·무제한으로 표시할 수 없다. [공식 가격표](https://developers.openai.com/api/docs/pricing)

## Claude API

기본 검색 `web_search_20250305`와 동적 필터링이 있는 후속 버전이 문서화되어 있다. 모델·도구 버전 호환성을 확인해야 한다. 최소 권한의 향후 구현에서는 기본 검색 또는 직접 호출만 검토하며 코드 실행 도구를 자동 추가하지 않는다. `max_uses`로 검색 수를 제한할 수 있다. HTTP 200이어도 `web_search_tool_result_error`가 있거나 결과가 빈 배열이면 성공이 아니다. 실제 `server_tool_use`·결과·인용을 함께 검사해야 한다. 가격은 검색 1,000회당 **USD 10**에 모델 토큰 비용이 추가된다. [공식 웹 검색 도구](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)

Claude Console API 키 인증은 기존 Claude Code 구독 로그인과 구분한다. 공식 인증 문서는 Bearer API 키를 안내하며 기존 `x-api-key`도 지원한다. API 도입 시 별도 DPAPI 저장소·동의·예산이 필요하다. [공식 API 인증](https://platform.claude.com/docs/en/manage-claude/authentication)

현재 공식 청구 문서는 일부 Max·Team 플랜의 연결된 Console 조직에 월별 API 크레딧이 있을 수 있다고 설명한다. 계정별 적용·잔여액을 확인하지 않았으므로 무료라고 단정하지 않는다. 타임아웃이나 연결 해제 뒤 서버에서 완료된 요청은 청구될 수 있다. 결과 불명 요청을 자동 재전송하지 않아야 한다. [공식 API 청구 안내](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)

## 기존 코드와 적용 경계

- `intelligence/provider.py`: 기존 OpenAI 경로는 `/chat/completions`의 분석·대본 JSON 요청이다. 검색 도구를 요청하지 않는다. `check_connection()`의 모델 조회는 검색·청구 한도 검증이 아니다.
- `intelligence/settings.py`: 기본 OpenAI 모델은 `gpt-4o-mini`이며 기존 동의·월별 토큰 한도가 있다. 이 승인을 추가 검색 도구 비용의 승인으로 확대하지 않는다.
- `intelligence/claude_code.py`: `--restricted`, 비어 있는 도구 목록·MCP 설정, 세션 미저장을 유지한다. 웹 검색을 위해 이 격리를 해제하지 않는다.
- `research.py`: 출처·시간·관련 기사 계약 및 검색 이벤트 검증을 재사용할 수 있다. 후보 URL의 존재·안전성·출처와 실제 검색 증거가 확인되기 전에는 실제 뉴스로 자동 저장하지 않는다.

향후 실제 검색을 열려면 특정 계정·모델·도구, 전달 자료, 최대 검색 횟수·입출력량·요청 비용과 월 한도를 먼저 보여 주고 별도 승인을 받아야 한다. 검색·분석·대본 사용량을 구분하고, 결과 불명 예약을 보존하며 자동 재시도·다른 Provider 전환을 차단한다. 로컬 추정 사용량을 공급사 청구량으로 표시하지 않는다. API 약관·기사 권리의 계정별 적용 및 Claude Code의 일반 상업 배포 적합성은 이번 문서 검토로 확인된 것으로 취급하지 않는다.

## 검색 계약의 최소 재사용 범위

아래 내용은 기존 코드의 읽기 전용 검토와 구현 권고다. 이 문서 작성 과정에서 계약·수집 코드나 실행 경로를 수정하지 않았다.

| 기존 구성 | 재사용 및 한계 |
| --- | --- |
| `research.ResearchRequest` | 분야·기간·5/10/20건의 엄격한 입력 계약을 재사용한다. 기간 선택 자체가 기사 발행일 검증은 아니다. |
| `research.Source` / `SearchArticle` | 출처·URL·근거·요약·주장·미확인 사항, nullable 시간대 포함 발행일을 재사용한다. `verification=needs_review`를 유지한다. |
| `research.NewsSearchResult` | 1~20건, 정규화된 URL 중복 차단을 재사용한다. `example` 계열 합성 URL은 실제 검색 후보로 받지 않는다. |
| `research.validate_search_evidence()` | 실제 어댑터가 관찰한 완료 이벤트에서 검색 1건 이상과 후보별 열람 URL을 대조하는 원칙을 재사용한다. 현재 입력은 App Server의 `webSearch/search/openPage` 전용이며 OpenAI·Claude 이벤트를 그대로 받을 수 없다. 모델 JSON의 자기 주장으로 이벤트를 만들면 안 된다. |
| `research.FakeResearchProvider` / `FakeResearchResult` | `synthetic=True`, 합성 출처·URL과 30/45/60초 fixture를 유지한다. 실제 검색 증거·실제 기사로 승격하거나 뉴스 DB에 넣지 않는다. |
| `research.find_existing_articles()` | 이미 RSS로 저장된 기사와 정규화 URL을 읽기 전용으로 연결한다. 새로운 검색 후보를 저장하지 않는 안전한 경계다. |
| `news.rss_adapter.validate_url()` / `news.dedup.canonical_url()` | URL 문법·사설 주소·인증정보 차단 및 추적 인자 제거를 재사용한다. 문법 검증만으로 DNS 안전성·기사 존재·내용을 확인했다고 표시하지 않는다. |
| `news.service.NewsService.collect()` | 기존 RSS 수집 및 `NewsArticle`·`ArticleMention` 중복·출처 저장을 그대로 유지한다. AI가 만든 후보를 가짜 RSS로 주입하지 않는다. |

Fake 검색 증거 검증을 확장한다면 어댑터 관찰값과 모델 작성값을 별도로 전달하는 작은 계약이 적절하다. 관찰값에는 실제/합성 구분, Provider·요청 ID, 완료 여부·검색 횟수·오류, 도구 결과의 출처 URL·확인 범위·인용 근거·조사 시각을 둔다. 모델 값에는 기존 `SearchArticle`의 요약·주장·미확인 사항을 둔다. 현재 `facts`는 AI가 추출한 주장일 뿐 검증된 사실이 아니므로 UI에서 원문 근거와 AI 해석을 구분한다.

URL이 도구의 실제 결과·열람 근거와 연결되지 않거나 결과가 비었으면 실패한다. 검색 결과·인용 일부만 얻었으면 전체 본문 확인으로 격상하지 않는다. 발행일이 없으면 `None`을 보존하고 기간 일치 여부도 미확인으로 남긴다. 관찰한 날짜 근거 없이 AI가 만든 날짜로 기간을 통과시키지 않는다. Fake의 성공은 계약 검증만 뜻하며 실제 Provider 검증 상태는 계속 미검증이다. 기존 검색 후보에서 뉴스 DB로의 자동 삽입 경로는 열지 않는다.
