# 기존 전체 회귀 57 FAIL 해결 보고

작성 시각: 2026-10-19T19:03:13+09:00 (KST)

## 판정과 범위

기존 57개 실패를 최신 작업 시작 코드에서 모두 재현한 후 제품 분기 결함과 오래된 테스트 계약을 구분해 수정했다. 과거 보고서의 57 FAIL 기록은 그대로 보존한다. 이 보고서의 결과는 아래 SHA의 새 검증이다.

- 시작 SHA: `4b4e9c232f8b66ead8966e72556f283f39cb1fa0` (작업 트리 clean).
- 최종 검증 코드 SHA: `cc7b3190c9acd8a3bacbfbfbb0ce4bac004de1a9`.
- 브랜치: `codex/newsflow-ux-video-app`. 로컬 커밋만 생성; push·PR #35 갱신·main 병합 없음.
- 기존 실패 재현: **57 FAIL, 230 deselected, 0 missing**. 전체 테스트 중 기존 57개 ID만 선별한 결과이며 deselected를 skip으로 세지 않는다.
- 해결 비교: **57/57 해결**, ID별 누락 0. 사용량 관련 2개 테스트를 각각 OpenAI/Claude API로 확장하여 최종 대응 테스트는 **59개 PASS**.
- 최종 Cloud 전체: **3827 PASS / 0 FAIL / 10 SKIP / 1 WARNING** (961.86초). 경고는 기존 Starlette TestClient의 httpx 사용 중단 안내다. 정확한 시간·경고와 원문은 [전체 로그](evidence/regression-57-resolution/full.log), [JUnit](evidence/regression-57-resolution/full.xml).
- Ruff: PASS. `pip check`: PASS.
- Windows 11·Windows Python 3.12/3.14·실제 DPAPI/음질·실제 공급사: **NOT VERIFIED**. 원격 코드를 변경해 Actions를 실행하지 않았다.

## 제품 결함과 수정

새 RSS 제작에서 Claude Code/Codex를 선택하고 실행 동의를 해도, `news_usage`가 있으면 기존 로컬 주제 대본 분기로 들어갔다. 분석·대본 요청, 취소 전달, 실패·결과 불명 검사가 실제 선택 경로에 도달하지 못했다.

새로 동의한 CLI 작업에만 `cli_grounded_v1`을 저장하고 기존 분석/대본 엔진으로 연결했다. API 엔진·검색 엔진을 새로 만들지 않았다. 기록에 이 표시가 없는 과거 로컬 작업은 과거 방식으로 재개되며 추가 외부 호출을 얻지 않는다. 동의 화면도 RSS 확보 후 같은 AI 분석 1회·대본 1회라는 실제 동작에 맞췄다.

저장된 결과 재사용 시 Provider·모델·작업 ID·동의 시각의 일치를 검사한다. 결과 불명이나 실패한 외부 요청은 재전송하지 않는다. 지원되지 않는 VERIFIED 작업은 AI 호출 전에 중단한다. 이 경계를 검증하는 신규 테스트 10개를 추가했다.

## 테스트 기준을 갱신한 이유

- UI: 현재 7개 주요 메뉴와 실제 href, 통합 설정 화면, 홈 제작 진입, 설명 간소화에 맞춘다. 삭제된 개발 단계 이름·헤더·중복 설정 설명을 복원하지 않는다.
- 데이터: 단계 기록의 `request` 설정, `STANDARD` 전달, 분석 schema의 선택적 추천 필드를 검사한다. 이미 생성된 분석의 Provider/model이 새 기본값으로 바뀌지 않는 것도 검사한다.
- 비용/재시도: 옛 자동 재시도 허용 기대를 **외부 요청 재전송 금지**로 바꿨다. Fake API의 분석 200 + 대본 200 = 400토큰 반환 기록을 확인하며 실패 대본의 사용량도 남긴다. 추측 비용 예약이나 요청별 금액 한도를 다시 추가하지 않았다.
- Mock: 오래된 OpenAI 준비 gate 대신 현재 worker의 준비 gate를 사용한다. Windows platform mock은 자격정보 모듈에만 적용해 Linux 표준 라이브러리까지 오염시키지 않는다. FakeCipher 결과를 실제 Windows DPAPI 성공으로 보고하지 않는다.
- 기존 테스트 함수는 삭제하지 않았다. 일부 함수 이름에 옛 `six`, `estimate`, `retried` 표현이 남아 있는 것은 과거 실패 ID 추적을 위한 것이며 assertion과 docstring은 현재 정책을 명시한다. 새 skip/xfail을 추가하지 않았다.

57개 ID의 변경 이유·최종 대응 ID·결과는 [비교 JSON](evidence/regression-57-resolution/comparison.json)에 있다. 단순 건수 비교가 아니다. 제목과 retryable parameter가 바뀐 4개 ID와 사용량 2개 테스트의 확장도 명시적으로 연결했다.

## 검증 방법과 재현

동일한 Cloud Python 3.12.14 가상환경과 의존성을 사용했다. 분석 중 의존성 설치·업데이트 없음. [의존성 목록](evidence/regression-57-resolution/dependencies.txt).

```bash
cd /workspace/JSBAE/newsflow-ai
NEWSFLOW_LIVE_TEST=0 NEWSFLOW_AI_LIVE_TEST=0 \
PYTHONPATH=docs/reports/evidence/ux-video-app/final-validation \
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
.venv/bin/python -m pytest -p cloud_validation_browser -q -rs --tb=short
.venv/bin/ruff check src tests
PIP_CACHE_DIR=/tmp/newsflow-pip-cache .venv/bin/python -m pip check
```

`cloud_validation_browser`는 이전 검증에서도 사용한 Cloud Chromium 실행 경로 선택용 plugin이다. Windows/Chrome으로 위장하거나 제품·보안 assertion을 변경하지 않는다. 전체 실행의 정확한 명령은 [명령 JSON](evidence/regression-57-resolution/full-command.json)에 있다. 테스트 프로세스에는 실제 API 키·토큰·live opt-in 환경을 상속하지 않았다.

수정 중 선택 AI·신규 API·기존 로컬 작업 보존 관련 101개 테스트가 PASS했다. 이후 최종 전체 테스트에 해당 검증을 포함했다. 실제 브라우저를 사용하는 `*browser*` 모듈의 결과도 전체 JUnit에 포함된다(19 cases). 새 화면 설계나 대량의 중복 스크린샷을 만들지 않았다.

Skip은 플랫폼 전용·기존 opt-in 등 실제 이유를 [skip 목록](evidence/regression-57-resolution/skips.json)에 그대로 기록한다. Windows 모의 테스트는 실제 Windows 실행으로 계산하지 않는다.

## 전체 검증에서 추가로 발견한 기존 실패 10개

기존 57개 목록 밖에서 10개가 더 발견됐다. 기준 SHA `4b4e9c2`의 소스·테스트를 Git archive로 임시 폴더에 비교용으로 추출하여 같은 Python/의존성에서 해당 **전체 테스트** 10개를 실행했다. 비교는 부분 probe나 건수 추정이 아니다. 기준 코드도 같은 10개가 같은 assertion에서 실패했다. [기준 로그 7건](evidence/regression-57-resolution/additional-all-baseline.log)과 [추가 기준 로그 3건](evidence/regression-57-resolution/additional-last-baseline.log)에 실패 근거를 보존했다. 첫 로그는 실제 import된 기준 소스 경로도 기록한다. 브랜치를 전환하거나 기존 작업을 덮어쓰지 않았다.

- API 최초 검증 UI 2개: 간소화 전 문구와 9,000토큰 기술 설명을 기대했다. 현재 1회 유료 검증·비용 미확정·재전송 금지 안내와 승인/인증 차단을 검사한다.
- Claude 연결 UI 1개: 연결 확인을 접으면 실패하던 기대를 수정했다. 비용 dialog/form과 분리된 하나의 닫힌 연결 영역과 필수 동의는 그대로 검사한다.
- Codex Studio 1개: `presentation` 스타일 메타데이터가 추가된 저장 구조를 검사한다. 30/45/60초 대본, 원문 출처, 선택 Provider와 사용량을 끝까지 검사했다.
- 홈 UI 2개: 승인된 대시보드 제목과 빈 영상 상태를 검사한다. Fake 영상이 실제 플레이어/파일로 노출되지 않는 검사도 유지했다.
- 뉴스 활용 UI 1개: 반복 API 안내 대신 실제 선택 AI 표시와 설정 링크를 검사한다. QUICK/STANDARD·VERIFIED 숨김·저장값 불변 검사는 유지했다.

마지막 3개는 주제 대본의 현재 안내, 승인된 7개 메뉴와 제작 선택값, 옆 패널에 노출한 영상 편집 설정을 반영했다. 중첩된 details를 정규식으로 잘못 읽던 테스트 helper는 HTML 구조를 검사하도록 고쳤다. 자막·소재·효과와 명시적 검토/유료 음성 동의는 그대로 검사한다.

추가 10개도 삭제/skip 없이 수정하여 관련 84개 테스트가 통과했다. [추가 비교표](evidence/regression-57-resolution/additional-existing-comparison.json). 첫 전체 실행의 FAIL 기록도 [보존](evidence/regression-57-resolution/full-first.log)하고, 테스트 수정 후 최종 SHA에서 전체 검증을 다시 수행했다. 전체를 반복한 이유는 새로 확인한 실패의 수정과 최종 코드·테스트 일치 확인이며, 중간 FAIL을 전체 PASS로 바꾸어 표기하지 않았다.

## 안전성과 미검증

실제 유료 API·CLI 로그인·OAuth·SNS 게시 실행은 0건이다. 실서비스 호출/청구를 검증한 것이 아니며 live opt-in은 비활성화했다. 합성 RSS/AI 공급자, 임시 SQLite/폴더로 검증했다. 환경의 실사용 비밀값을 테스트에 전달하지 않았다. 이는 실서비스 품질·로그인·청구 성공의 증명이 아니다.

기존 승인·결과 불명 차단·중복 방지·대본 및 최종 영상 검토·별도 게시 승인을 유지했다. 운영 DB/키/설정/MP4와 migration을 변경하지 않았다. 운영 앱을 재시작하지 않았다. 원격 PR #35 Draft와 main 상태는 이 작업에서 변경하지 않았다.

추가 실검증은 Windows PC 또는 별도 승인된 Windows CI에서 동일 코드로 수행해야 한다. 실제 음성 품질·외부 API·OAuth·SNS 게시 검증은 별도 사용자 승인 범위다. 본 작업 후 추가 기능 개발을 중단한다.

## 변경 파일

- `newsflow-ai/src/newsflow/autopilot/backend.py`
- `newsflow-ai/src/newsflow/autopilot/service.py`
- `newsflow-ai/src/newsflow/gui/autopilot_routes.py`
- `newsflow-ai/src/newsflow/gui/templates/autopilot_start_guide.html`
- `newsflow-ai/tests/test_ai_estimate.py`
- `newsflow-ai/tests/test_ai_news_automation_backend.py`
- `newsflow-ai/tests/test_ai_news_automation_gui.py`
- `newsflow-ai/tests/test_ai_video_gui.py`
- `newsflow-ai/tests/test_api_first_check_gui.py`
- `newsflow-ai/tests/test_autopilot_state.py`
- `newsflow-ai/tests/test_claude_connection_gui.py`
- `newsflow-ai/tests/test_codex_adapter.py`
- `newsflow-ai/tests/test_codex_studio.py`
- `newsflow-ai/tests/test_easy_setup.py`
- `newsflow-ai/tests/test_easy_ui.py`
- `newsflow-ai/tests/test_gui.py`
- `newsflow-ai/tests/test_news_usage_gui.py`
- `newsflow-ai/tests/test_oauth_operations_gui.py`
- `newsflow-ai/tests/test_oauth_production_gui.py`
- `newsflow-ai/tests/test_realcontent.py`
- `newsflow-ai/tests/test_topic_editor_gui.py`
- `newsflow-ai/tests/test_ux_navigation.py`
- `newsflow-ai/tests/test_ux_video.py`
- `newsflow-ai/tests/test_ux_workflow.py`
- `newsflow-ai/tests/test_ux_workflow_context.py`

## 기존 57개 결과 연결

| 과거 테스트 ID | 구분 | 최종 대응 결과 |
|---|---|---|
| `tests.test_ai_estimate::test_gui_prices_form_and_estimate_text` | test_contract | PASS |
| `tests.test_ai_estimate::test_retried_failed_script_tokens_stay_in_the_job_total` | no_replay_policy | PASS, PASS |
| `tests.test_ai_estimate::test_start_and_job_pages_show_estimate_then_actual_usage` | test_contract | PASS, PASS |
| `tests.test_ai_news_automation_backend::test_cancel_is_delivered_to_only_operation_owned_provider` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_category_and_unknown_old_future_dates_are_not_current_news` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_failed_and_unknown_external_requests_never_replay[error0-analysis]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_failed_and_unknown_external_requests_never_replay[error0-script]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_failed_and_unknown_external_requests_never_replay[error1-analysis]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_failed_and_unknown_external_requests_never_replay[error1-script]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_failed_and_unknown_external_requests_never_replay[error2-analysis]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_failed_and_unknown_external_requests_never_replay[error2-script]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_idempotency_refuses_changed_policy_or_model` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_offline_keeps_local_flow_and_explicit_policy` | test_contract | PASS |
| `tests.test_ai_news_automation_backend::test_restart_distinguishes_success_failure_and_unknown_without_replay[failed-ai_request_stopped-False]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_restart_distinguishes_success_failure_and_unknown_without_replay[running-outcome_unknown-False]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_restart_distinguishes_success_failure_and_unknown_without_replay[success-interrupted-True]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_resume_after_script_review_carries_voice_without_new_ai` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_same_provider_pipeline_preserves_selection_context_usage_and_review[30-claude_code]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_same_provider_pipeline_preserves_selection_context_usage_and_review[30-codex]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_same_provider_pipeline_preserves_selection_context_usage_and_review[45-claude_code]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_same_provider_pipeline_preserves_selection_context_usage_and_review[45-codex]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_same_provider_pipeline_preserves_selection_context_usage_and_review[60-claude_code]` | product_routing | PASS |
| `tests.test_ai_news_automation_backend::test_same_provider_pipeline_preserves_selection_context_usage_and_review[60-codex]` | product_routing | PASS |
| `tests.test_ai_news_automation_gui::test_home_policy_change_has_matching_readiness_and_notice_without_execution` | test_contract | PASS |
| `tests.test_ai_news_automation_gui::test_one_home_request_preserves_choices_and_requires_explicit_consent[30-claude_code-sonnet]` | product_consent_and_test_contract | PASS |
| `tests.test_ai_news_automation_gui::test_one_home_request_preserves_choices_and_requires_explicit_consent[30-codex-default]` | product_consent_and_test_contract | PASS |
| `tests.test_ai_news_automation_gui::test_one_home_request_preserves_choices_and_requires_explicit_consent[45-claude_code-sonnet]` | product_consent_and_test_contract | PASS |
| `tests.test_ai_news_automation_gui::test_one_home_request_preserves_choices_and_requires_explicit_consent[45-codex-default]` | product_consent_and_test_contract | PASS |
| `tests.test_ai_news_automation_gui::test_one_home_request_preserves_choices_and_requires_explicit_consent[60-claude_code-sonnet]` | product_consent_and_test_contract | PASS |
| `tests.test_ai_news_automation_gui::test_one_home_request_preserves_choices_and_requires_explicit_consent[60-codex-default]` | product_consent_and_test_contract | PASS |
| `tests.test_ai_video_gui::test_key_form_stores_through_dpapi_store_and_never_renders_the_key` | fixture_isolation | PASS |
| `tests.test_ai_video_gui::test_pages_render_default_off_and_keep_six_main_menus` | test_contract | PASS |
| `tests.test_autopilot_state::test_easy_synthetic_stages_are_durable_and_ordered` | test_contract | PASS |
| `tests.test_codex_adapter::test_structured_rss_request_preserves_input_and_has_no_implicit_tools[analyze]` | test_contract | PASS |
| `tests.test_easy_setup::test_wizard_is_optional_and_all_core_menus_remain` | test_contract | PASS |
| `tests.test_gui::test_render[/dashboard-\ub274\uc2a4 \ud750\ub984\uc744 \ud55c\ub208\uc5d0]` | test_contract | PASS |
| `tests.test_gui::test_render[/news-\ub274\uc2a4 \ud0d0\uc0c9]` | test_contract | PASS |
| `tests.test_gui::test_render[/settings-\uc6cc\ud06c\uc2a4\ud398\uc774\uc2a4 \uc124\uc815]` | test_contract | PASS |
| `tests.test_oauth_operations_gui::test_operations_panel_keeps_real_connect_button_disabled` | test_contract | PASS |
| `tests.test_oauth_production_gui::test_readiness_panel_distinguishes_preparation_from_real_verification` | test_contract | PASS |
| `tests.test_realcontent::test_external_ai_failures_map_to_actionable_codes[error0-ai_rate_limited-True]` | no_replay_policy | PASS |
| `tests.test_realcontent::test_external_ai_failures_map_to_actionable_codes[error1-ai_timeout-True]` | no_replay_policy | PASS |
| `tests.test_realcontent::test_external_ai_failures_map_to_actionable_codes[error2-ai_bad_response-True]` | no_replay_policy | PASS |
| `tests.test_realcontent::test_gui_start_page_shows_readiness_and_disables_unready_external_ai` | test_contract | PASS |
| `tests.test_realcontent::test_simple_settings_rejects_external_ai_with_sample_news` | test_contract | PASS |
| `tests.test_unified_ai_workspace::test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai[30-claude_code]` | product_routing_and_consent | PASS |
| `tests.test_unified_ai_workspace::test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai[30-codex]` | product_routing_and_consent | PASS |
| `tests.test_unified_ai_workspace::test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai[45-claude_code]` | product_routing_and_consent | PASS |
| `tests.test_unified_ai_workspace::test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai[45-codex]` | product_routing_and_consent | PASS |
| `tests.test_unified_ai_workspace::test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai[60-claude_code]` | product_routing_and_consent | PASS |
| `tests.test_unified_ai_workspace::test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai[60-codex]` | product_routing_and_consent | PASS |
| `tests.test_unified_ai_workspace::test_unknown_script_result_remains_stopped_after_refresh_reconfirm_and_recovery` | product_routing_and_consent | PASS |
| `tests.test_ux_workflow::test_available_local_voice_is_forwarded_without_new_provider_settings` | test_contract | PASS |
| `tests.test_ux_workflow::test_saved_account_provider_requires_consent_without_job_or_replacement[claude_code-sonnet]` | product_routing_and_consent | PASS |
| `tests.test_ux_workflow::test_saved_account_provider_requires_consent_without_job_or_replacement[codex-default]` | product_routing_and_consent | PASS |
| `tests.test_ux_workflow::test_stored_paid_approval_still_requires_per_job_transfer_consent` | fixture_gate | PASS |
| `tests.test_ux_workflow_context::test_different_openai_model_requires_consent_without_replacement` | fixture_gate | PASS |
