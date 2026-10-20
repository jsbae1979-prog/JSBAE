# 유사 기사 종합 대본 — 구현 및 검증

- 작성: 2026-10-20 KST
- 기준: `ff4f1f8` / 구현·검증 코드: `985e2ef9924c9eefcde729a3e661cfc4874841e7`
- 브랜치: `codex/newsflow-ux-video-app`, 로컬 보존. PR #35/원격 브랜치/main 변경 없음.

## 구현

새 통합 자동 제작의 외부 AI 작업에 `similar_articles_v1` 정책을 저장한다. 기존 RSS/API 웹 검색 및 기사 분석 요청을 재사용하고, 선택한 기준 기사와 유사한 **최대 5개 기사 자료를 한 번의 대본 생성 요청에 함께 전달**한다. 기존 OpenAI·Claude API와 통합 CLI Provider 경로를 사용하며, Provider를 바꾸거나 별도 엔진을 추가하지 않았다.

관련 기사 선택은 기존 분석에 저장된 제목 유사도 그룹을 사용한다. 기준 기사와 직접 제목 유사도 0.65 이상인지 다시 확인하고, 분류가 서로 다르거나 확인된 발행 시각이 48시간 이상 떨어진 자료는 제외한다. 후보는 기존 수집/검색 범위 안에서만 고르며 새 검색·추가 분석 호출을 하지 않는다. 날짜 미상은 미상으로 유지한다. 이는 보수적인 내부 휴리스틱이며 같은 사건·독립 보도·사실 확인의 증명이 아니다.

관련 자료가 하나뿐이면 같은 Provider로 단일 기사 대본을 작성하고 화면에 그 사실을 표시한다. 여러 기사를 얻기 위해 자동 재검색하거나 다른 Provider로 전환하지 않는다. 기존 수집 중복 제거로 하나의 기사에 합쳐진 여러 출처는 기존 provenance로 유지된다.

대본 요청에는 선택한 모든 기사의 제목·요약·출처와 분석 결과를 전달한다. 공급사 지시에는 한 편으로 종합하되 출처별 수치·날짜·주장의 차이를 보존하고, 평균/다수결로 충돌을 해결하거나 반복 보도를 독립 검증으로 취급하지 말도록 명시했다. `facts_verified`는 false다. 실제 AI가 이를 얼마나 잘 따르는지는 실호출 없이 검증 완료로 주장하지 않는다.

## 기존 정책과 복구

- 분석·대본·TTS·영상·게시 엔진, 사용 동의, 사용량 기록, 비용 검사, 실패/결과 불명 재호출 차단을 재사용한다. 추가 API 요청을 자동으로 실행하지 않는다. 여러 자료로 입력 토큰은 늘어날 수 있으므로 기존 사용량/비용 검사 대상이다.
- 기존 작업에는 새 종합 정책을 소급하지 않는다. 이전 작업 번호로 재진입해도 기존 단일 기사 기록과 호출 이력을 보존한다.
- 선택한 기사 ID 목록을 작업 단계 결과에 고정하고, 대본 재사용 시 분석 스냅샷·기사 집합·작업/Provider 바인딩을 확인한다. 완료 대본은 다시 생성하지 않는다.
- 묶음의 모든 기사를 기존 `AutopilotArtifact`에 `synthesis_article`로 기록한다. 기존 `BEGIN IMMEDIATE` 트랜잭션 안에서 대표 기사 claim, 묶음 claim, 단계 결과를 함께 저장한다. 다른 작업의 대표 또는 보조 기사로 재사용되는 것을 차단한다. 취소/실패 때에도 기존 중복 방지 정책처럼 기록을 보존한다.
- DB 스키마 및 기존 migration 변경 없음. 운영 DB·키·설정·MP4 변경/앱 재시작 없음.
- 각 기사 근거는 `ContentDraft.sources` → 영상 스냅샷 → 게시 초안까지 보존된다. 게시 설명의 자동 출처 링크 공개 선택도 유지한다. 사실/권리 검토와 최종 게시 승인은 별개다.
- 유료 무인 예약 정책을 확대하지 않았다. 기존 오프라인·예약 제작을 새 유료 종합 작업으로 전환하지 않는다.

## 화면

기존 작업실 대본 영역에서 관련 기사 수와 접을 수 있는 기사별 제목·요약·발행 시각·원문 링크를 보여 준다. 한 개일 때는 “관련 자료가 부족해 기사 1개로 작성했습니다. 자동 재검색은 하지 않았습니다.”라고 표시한다.

Cloud Chromium 1366×768 및 390×844에서 자료 열기·기사별 링크 확인·화면 재진입·가로 넘침을 확인했다. 화면은 합성 데이터이며 실제 공급사 품질/사용자 Windows 화면 검증이 아니다.

## 검증

Cloud Python 3.12.14. Fake OpenAI/Claude API, Fake RSS, 합성 계정·임시 DB 사용.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_SYNTHESIS_EVIDENCE=/tmp/newsflow-synthesis-evidence \
.venv/bin/python -m pytest -q -rs \
  tests/test_multi_article_synthesis.py tests/test_synthesis_gui.py \
  tests/test_api_news_pipeline.py tests/test_ai_news_automation_backend.py \
  tests/test_autopilot_backend.py tests/test_autopilot_boundaries.py \
  tests/test_autopilot_state.py tests/test_intelligence.py \
  tests/test_scheduler.py tests/test_scheduler_gui.py \
  tests/test_autopilot_metadata.py tests/test_publish_metadata.py \
  tests/test_publish_source_choice.py tests/test_unified_publishing.py
.venv/bin/ruff check src tests
git diff --check
```

- **PASS: 302 passed / 0 failed / 0 skipped / 1 warning**, 65.03초. 기존 Starlette/httpx 사용 중단 경고.
- **PASS:** Ruff, diff check.
- **PASS:** RSS/API 검색 각각에서 Fake OpenAI·Claude로 여러 근거를 한 번의 요청에 전달, 30/45/60초 대본 저장 및 재사용.
- **PASS:** 서로 다른 수치가 있는 원문 요약 보존·미확인 상태, unrelated 기사 제외, 최대 5개/분류/발행시각 경계, 근거 집합 위조 차단.
- **PASS:** 묶음 전체 중복 방지, 동시 경쟁 작업 하나만 claim 성공 및 실패 작업의 부분 기록 롤백.
- **PASS:** 이전 작업 단일 기사 유지, timeout/결과 불명 재호출 차단, 기존 API/CLI/예약/검토/게시 회귀.
- **PASS:** Fake 영상 스냅샷과 게시 대기 초안에 여러 기사 출처 유지. 실제 MP4 렌더링 품질 증거는 아니다.
- **PASS:** 실제 Cloud 브라우저의 복수/단일 기사 구분과 근거 보기.
- 초기 회귀에서 발견한 legacy 로컬 작업의 새 정책 적용 오류 2건을 코드로 수정했다. 테스트 삭제/skip/보안 완화 없이 재검증했다. 테스트 fixture의 필수 필드·파라미터 설정 오류도 수정했다.
- 로그: `/tmp/newsflow-synthesis-final-tests.txt`. 스크린샷: `/tmp/newsflow-synthesis-evidence/synthesis-{openai,claude_api}-{1366,390}.png`.

## 미검증 및 중단

실제 유료 API·CLI 실행·OAuth·SNS 호출 **0건**. 실제 공급사의 종합 대본 품질, 의미상 같은 사건 판단, 사실관계·권리 확인, 한국어 음성/영상 품질, Windows 사용자 PC·Windows Actions의 이번 코드 실행은 **NOT VERIFIED**다.

전체 회귀를 반복하지 않았다. 기존 **57 FAIL** 기록은 유지하며 이번 변경 범위의 결과를 전체 PASS로 보고하지 않는다. 자료 정리 후 추가 개발을 중단한다.
