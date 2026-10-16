# STEP 3 — API 뉴스 검색·분석·대본 자동화

상태: 구현·로컬 Fake 통합·Chrome 검증 완료, Windows CI 결과 대기. 실제 OpenAI/Anthropic 호출은 0건이며 실제 연결·검색은 **NOT VERIFIED / BLOCKED**이다. Claude Code·Codex CLI를 실행하거나 인증 상태를 다시 조사하지 않았다.

## 구현 범위

- 기존 단일 작업실과 `IntelligenceService`·Autopilot을 재사용한다. 검색 → 같은 API의 분석 → 30·45·60초 대본 → 사용자 검토 → 기존 음성·영상 단계로 연결한다. 작업실·설정 외의 새 메뉴는 추가하지 않는다.
- OpenAI 검색은 Responses API의 `web_search`를 사용하고 분석·대본은 기존 OpenAI 어댑터를 재사용한다. Claude API는 별도 API Key 기반 Messages 어댑터를 추가했으며 Claude Code 구독 인증을 사용하지 않는다.
- 검색 요청은 도구 1회로 제한한다. OpenAI `max_tool_calls=1`, Anthropic `web_search_20250305`·`max_uses=1`·`allowed_callers=["direct"]`를 사용한다. 코드 실행·추가 도구·자동 계속 호출은 제공하지 않는다.
- 수집 정책은 AI 검색, RSS, 명시적 AI 검색+RSS 보완을 구분한다. 기존에 저장된 RSS 선택은 보존한다. 검색 실패 시 RSS나 다른 Provider로 자동 전환하지 않는다.
- 검색·분석·대본 실행 ID를 기존 작업에 연결한다. 성공 결과 재사용, 결과 불명·시간 초과·취소 시 자동 재전송 차단, 대본·최종 영상 검토 게이트를 유지한다.

## 공식 API 조건

| 항목 | OpenAI API | Claude API |
|---|---|---|
| 구현 모델 계약 | `gpt-4.1-mini` | `claude-sonnet-4-6` |
| 공식 검색 경로 | Responses `web_search` | Messages `web_search_20250305`, 직접 호출 |
| 검색 도구 공시 가격 | $10 / 1,000회 + 토큰 | $10 / 1,000회 + 토큰 |
| 입력·출력 공시 가격 / 1M 토큰 | $0.40 / $1.60 | $3 / $15 |
| 추가 비용 특성 | 해당 모델 검색 입력은 회당 8,000토큰 고정 블록 | 검색 내용·중간 처리에 사용된 입력 토큰도 과금 |
| 계정 조건 | API 키, 모델 접근 권한, 계정별 결제·사용 한도 | 별도 API 키, 모델·조직 검색 권한, 결제·사용 한도 |
| 실제 계정 검증 | 미실행 | 미실행 |

공시 가격은 2026-10-16 확인 기준이며 세금·계정별 계약·변경된 가격을 보장하지 않는다. CLI 구독과 별도의 API 과금이다. 모델과 조직의 실제 권한·한도는 공개 문서만으로 확인할 수 없다. Sonnet 4.6은 현재 제공 중인 legacy 모델로 문서에 표시된다.

공식 근거: [OpenAI 웹 검색](https://developers.openai.com/api/docs/guides/tools-web-search), [OpenAI 가격](https://developers.openai.com/api/docs/pricing), [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [OpenAI 한도](https://developers.openai.com/api/docs/guides/rate-limits), [Anthropic 웹 검색](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), [Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview), [Anthropic 한도](https://platform.claude.com/docs/en/api/rate-limits).

[OpenAI 서비스 계약](https://openai.com/policies/services-agreement/)과 [Anthropic 상업 약관](https://www.anthropic.com/legal/commercial-terms)은 조건에 따른 앱 통합을 허용한다. 출력에 대한 권리가 원문 기사·이미지의 제3자 권리까지 제공하는 것은 아니다. 원문 출처 링크와 사실·저작권 검토는 유지한다.

## 검색 근거와 미검증 정보

- 실제 도구 완료 식별자와 도구가 반환한 출처 URL을 모델 JSON과 대조한다. 검색 이벤트 0건, 빈 출처, 임의 생성 URL, 사설·인증정보 포함 URL, 잘못된 JSON은 성공 처리하지 않는다. 공급사 출처 제목이 없으면 모델이 만든 제목으로 보충하지 않고 차단한다. OpenAI 인용 메타데이터 제목은 실제 도구 출처 목록에 이미 있는 URL에만 연결한다.
- 도구 출처와 모델의 주장(`claimed_title`, `claimed_publisher`, `claimed_published_at`)을 분리한다. 검색 결과만으로 원문 본문·사실·언론사 신원을 검증했다고 표시하지 않는다. 실제 인기 순위도 제공하지 않는다.
- Anthropic `page_age`는 페이지 갱신 정보이며 기사 발행일로 쓰지 않는다. 공식 응답에서 확정할 수 없는 발행일은 `None`으로 보존한다. 날짜 확인이 필요한 기사만 남으면 분석을 시작하지 않는다. 사용자가 선택한 RSS 보완 경로는 같은 원문 URL에 대한 RSS 메타데이터를 재사용할 수 있다.
- Fake 결과는 `test_fixture`로 표시하며 실제 웹 검색 수행 증거로 사용하지 않는다. 사용자에게 보여주는 검색 요약에는 기존 출처 링크를 유지한다.

## 키·비용·데이터 보호

- OpenAI의 기존 키 저장을 재사용하고 Claude API 키는 별도 DPAPI 저장소에 등록·교체·삭제한다. 키를 일반 SQLite 값·HTML·로그에 저장하지 않는다. 설정 저장과 화면 조회는 API 요청을 발생시키지 않는다.
- 설정 완료, 실제 연결 미확인, 사용 승인 필요, 예산 제한, 실제 성공 여부를 구분한다. 기존 분석 승인을 검색 비용 승인으로 확대하지 않는다.
- 요청별·월별 USD 한도와 계정 잔여 예산 확인, 별도 검색 동의 및 인증·검색 검증 상태를 호출 전에 확인한다. 실제 계정 검증 기록이 없으므로 현 단계의 실호출은 차단된다.
- 추가 migration `0013_api_requests`는 동시 요청의 비용 예약과 불명확한 결과를 보존한다. 과금 가능 요청의 예약을 결과 불명·취소·오류만으로 해제하지 않는다. 로컬 사용량과 보수적 비용 예약은 공급사 청구액이 아니다.
- 외부 HTTPS 목적지는 공식 API 호스트로 고정하고 TLS 검증·응답 크기 제한·리디렉션 차단을 유지한다. 원격 오류 원문과 키를 사용자 오류에 포함하지 않는다. 취소는 이미 발생한 공급사 사용량을 되돌리지 않는다.
- 기존 migration·사용자 DB·뉴스·대본·영상·Provider 선택·CSRF·Origin·CSP·DPAPI와 대본/최종 검토를 보존한다. 실제 보존 대조 결과는 최종 검증란에 기록한다.

## 검증 및 제출

| 항목 | 결과 |
|---|---|
| API 어댑터·검색 계약 핵심 테스트 | 로컬 Python 3.14: 39 PASS, 해당 파일 Ruff PASS |
| API 설정·비용 보호 | 22 PASS |
| Fake API 검색·분석·대본 파이프라인 | 18 PASS |
| 기존 분석·자동 제작 계약 | 94 PASS |
| 설정·작업실 GUI 계약 | 18 PASS (11 + 7); 추가 연결 계약 2건 최종 확인 예정 |
| migration·데이터 계약 | 15 PASS |
| 실제 Windows Chrome 작업실 동선 | PASS: 별도 DB·Fake API 3단계 → 대본 검토 → Supertonic F1 → 30.02초 MP4 → 인라인 재생·다운로드 |
| Windows Python 3.12 / 3.14 CI | 변경 범위 workflow 준비, 최종 결과·URL 기록 예정 |
| 기존 사용자 DB·영상 보존 대조 | PASS: SQLite integrity=ok, 모든 테이블 행 수·설정 해시·기존 MP4 3개 SHA-256 동일 |
| 실제 OpenAI/Anthropic 요청 | 0건, NOT VERIFIED |
| 실제 Claude Code/Codex CLI·인증 시험 | 0건, 사용자 지시에 따라 중단 유지 |
| 실제 API 검색 → 실제 한국어 음성·MP4 | NOT VERIFIED; 이번 단계의 승인 범위 밖 |

새 workflow는 코드 push 때 Python 3.12·3.14를 각각 검증하며 문서만 변경한 push는 제외한다. 고정 의존성·`pip check`·변경 영역 Ruff와 Fake 계약 테스트만 실행한다. 실제 계정 인증·CLI·API·SNS 호출을 포함하지 않는다.

주요 변경 영역: `intelligence/api_search.py`, `api_providers.py`, `api_settings.py`, `service.py`, `credentials.py`, `capabilities.py`, 기존 설정·뉴스 서비스, Autopilot, 통합 설정·작업실 라우트/템플릿, 추가 migration, 변경 영역 테스트 및 `.github/workflows/api-news-search-windows.yml`. 최종 변경 파일 목록은 Draft PR diff를 기준으로 한다.

- 브랜치: `feat/newsflow-api-news-search`
- 기준 SHA: `34c22e9a89afcde12ea89ef859e1157a6a8dc813`
- 최종 SHA: 최종 기록 예정
- Draft PR: 최종 기록 예정 (base: `feat/newsflow-unified-ai-workspace`)
- Windows Actions: 최종 기록 예정

남은 미검증: 실제 API 키·계정 권한·웹 검색 성공, 공급사 청구액, 원문 발행일/사실 검증, 실제 AI 결과의 한국어 대본·청취 품질. 새 Provider를 설정하는 것만으로 이를 PASS로 표시하지 않는다.

## 로컬 영상·재시작 검증

- 사용자 앱(8765)은 그대로 두고 `validation-output/step3-api-news-search/ui-test-data`의 별도 DB와 8780 루프백 테스트 서버를 사용했다. API·CLI 실호출을 차단한 테스트 전용 Fake 주입이며 실제 검색·인증 성공 증거가 아니다.
- Fake 검색·분석·대본 각 1회, 실행 ID 1/2/3. 대본 검토 후에는 로컬 영상 단계만 수행했다. 최종 영상은 사용자 검토 대기로 보존했다.
- 실제 로컬 Supertonic F1·FFmpeg 9.0.2: H.264/AAC, 1080×1920, 30.02168초. 측정 문장 5개의 타임스탬프와 자막이 일치하며 마지막 발화 종료 26.810초로 잘림 없음. 음성 속도 강제 증가·대본 단축 없음. 사람의 발음·내용 품질은 NOT VERIFIED.
- Chrome 재생 시 readyState=4, 오류 없음, 재생 시각 28.54초 확인. MP4 저장본과 원본 SHA-256 일치. 격리 앱 재시작 후 요청 ID와 영상 유지, 추가 Fake 호출 0건.
- 샘플(로컬 전용): `validation-output/step3-api-news-search/ui-test-data/outputs/videos/video-b9823ec5901d44e0b37b11bd424d7aa1.mp4`. 다운로드 사본은 사용자 Downloads의 같은 이름. 실제 보도가 아닌 합성 테스트 자료이다.
- 화면 증거(로컬 전용): `validation-output/step3-api-news-search/chrome-result.png`, `chrome-api-settings.png`. 모델·음성·영상·DB·인증 파일은 Git에 포함하지 않는다.
- 신규 migration 0013만 추가한다. 사용자 원본 DB에는 앱 업데이트·migration을 실행하지 않았다. 기존 0001–0012와 의존성 고정 파일, CLI 구현 파일은 그대로다.
