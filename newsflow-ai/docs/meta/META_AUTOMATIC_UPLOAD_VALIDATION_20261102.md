# Meta 자동 업로드 구현과 검증 20261102

프로그램이 게시 대상에 맞춰 파일을 직접 전송하거나 본인 저장소로 자동 업로드하도록 개발 구조를 변경했다. 운영 설치·계정·키·사용자 파일은 변경하지 않았다. 실제 Meta/저장소 수락은 미검증이므로 운영 사용 판정은 CONDITIONAL이다.

## 코드와 구현 범위

- 브랜치: `codex/newsflow-character-shorts-automation-20261030`
- 구현 SHA: `f4e2e15ae7689e3e48424491df43c390d8c795f7`
- 작업 전 SHA: `3cfbd2f0cdf9597faaedb6d202c018c11e9c4da7`. 원격 fetch 결과와 일치했다.
- Facebook JPEG/MP4: 고정 Graph 호스트로 multipart 파일 직접 전송. 외부 저장소 설정이 없어도 전송 준비 가능.
- Instagram 영상: `upload_type=resumable` 컨테이너 생성, ID를 먼저 보관한 뒤 고정 `rupload.facebook.com` 경로로 파일 전송. 처리 상태 확인과 최종 게시 승인은 기존 별도 단계 유지.
- Instagram 이미지: S3 호환 저장소를 최초 한 번 등록. 승인 후 24시간 PUT/GET 서명 URL 생성, 자동 PUT, GET 해시 확인, Meta 이미지 URL 전달. 본인 비공개 버킷을 사용할 수 있다.
- 같은 파일의 확인된 업로드 재사용. 자동 주소 만료는 같은 객체의 서명만 갱신하며 PUT을 반복하지 않는다. 실패·불명·중단 기록은 임의 초기화하지 않는다.
- 직접 전송이 거절돼도 다른 경로로 자동 전송하지 않는다. `upload_unknown`의 상태 조회와 최종 게시 `unknown`을 구분하여 불명 게시를 다시 승인 가능 상태로 만들지 않는다.
- 업로드 경로를 화면에 표시하고 파일별 주소 입력은 고급 호환 기능으로 이동했다. 설정 저장 자체에는 외부 전송이 없다.

## 변경 위치

| 영역 | 파일 |
|---|---|
| 직접 파일 전송 | `src/newsflow/meta/direct_upload.py`, `graph.py`, `publishing.py` |
| 사용자별 자동 저장소 | `src/newsflow/meta/automatic_storage.py`, `storage.py`, `media.py` |
| 로컬 API와 실행 경계 | `src/newsflow/meta/routes.py`, `tools/bat_distribution/meta_access.py` |
| 두 POST 경로 목록 | `src/newsflow/studio/actions.json`, `frontend/src/legacy-actions.json` |
| 설정·게시 화면 | `frontend/src/studio/management/MetaAccounts.tsx`, `MetaPublishPanel.tsx` |
| Fake 검사 | `tests/test_meta_automatic_upload.py`, `tests/test_meta_automatic_browser.py` |
| Windows CI | `.github/workflows/newsflow-character-automation.yml` 기존 단계에 새 검사 추가 |

## 검증 결과

기존 Python 환경을 재사용했다. `PYTHONPATH=src;tools;tests`, `PYTHONUTF8=1`로 실행했다. 각 행의 검사는 서로 중복되므로 합산하지 않는다.

| 검사 | 명령 | 결과 |
|---|---|---|
| Windows Python 3.14 Meta 통합 | `python -m pytest -q -rs --tb=short tests/test_meta_accounts.py tests/test_meta_direct.py tests/test_meta_automatic_upload.py tests/test_meta_browser.py tests/test_meta_automatic_browser.py` | 107 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| Windows Python 3.12 Meta 백엔드 | `python -m pytest -q -rs --tb=short tests/test_meta_automatic_upload.py tests/test_meta_accounts.py tests/test_meta_direct.py` | 102 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| studio_v3 | `python -m pytest -q -rs --tb=short tools/studio_v3/tests` | 58 PASS |
| frontend 계약 | `node --test tests/*.test.mjs` | 47 PASS |
| React 빌드 | `tsc --noEmit` 및 `vite build` | PASS, 기존 폰트 경로·번들 크기 경고 유지 |
| 변경 Python 정적 검사 | `ruff check src/newsflow/meta tests/test_meta_automatic_upload.py tools/bat_distribution/meta_access.py` | PASS |
| 전체 Python 회귀 | `python -m pytest -q -rs --tb=short --junitxml=.../auto-full.xml` | 6975 PASS / 113 FAIL / 24 ERROR / 50 SKIP |

전체 회귀는 최종 업로드 중단 구분·만료 갱신 보완 전 시작한 작업본 검사다. 해당 보완은 최종 107/102개 집중 검사로 확인했다. 전체 회귀를 최종 SHA의 전 항목 통과로 확대 해석하지 않는다. 처음 실행에서 개발 소스/도구 경로 누락과 새 CSRF fixture 오류가 발생했으며, 기존 실행 경로와 쿠키 계약으로 바로잡은 뒤 위 최종 결과를 얻었다.

새 검사는 직접 전송의 대상·본문·고정 호스트, 전송 동의 이전 무호출, 타 사용자 접근 차단, 파일 변조, 요청 거절/타임아웃 무재시도, 컨테이너 보존, 불명 최종 게시 재실행 차단, 자동 저장소 암호화 계약, PUT/GET 파일 일치, 주소 갱신 무재업로드, AWS 공식 SigV4 예제 일치, CSRF와 두 경로 목록을 포함한다. 독립 headless Chrome에서는 최초 한 번 설정·키 입력란 비우기·직접 전송 버튼·확인 취소 시 미전송을 확인했다. 사용자의 운영 Chrome을 제어하지 않았다.

## 전체 회귀에서 남은 항목

- `tests.test_ai_video_service::test_a_batch_that_fills_the_month_exactly_is_still_sent` (failure)
- `tests.test_ai_video_service::test_a_status_failure_after_the_deadline_keeps_polling_then_closes_refetchably` (failure)
- `tests.test_ai_video_service::test_existing_explicit_reservation_survives_month_boundary` (failure)
- `tests.test_all_scene_browser::test_workspace_all_ai_voice_approval_to_original_task_preview[openai]` (failure)
- `tests.test_all_scene_browser::test_workspace_all_ai_voice_approval_to_original_task_preview[claude_api]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-False-supertonic:F1-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-False-supertonic:F1-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-False-elevenlabs-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-False-elevenlabs-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-True-supertonic:F1-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-True-supertonic:F1-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-True-elevenlabs-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[openai-True-elevenlabs-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-False-supertonic:F1-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-False-supertonic:F1-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-False-elevenlabs-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-False-elevenlabs-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-True-supertonic:F1-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-True-supertonic:F1-False]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-True-elevenlabs-True]` (failure)
- `tests.test_all_scene_production::test_eight_choice_matrix_real_ffmpeg[claude_api-True-elevenlabs-False]` (failure)
- `tests.test_all_scene_safety::test_deleted_or_unreviewed_generated_clip_prevents_synthesis[openai]` (failure)
- `tests.test_all_scene_safety::test_deleted_or_unreviewed_generated_clip_prevents_synthesis[claude_api]` (failure)
- `tests.test_all_scene_safety::test_failed_voice_with_completed_ai_clips_is_not_recharged_on_compose_retry[openai]` (failure)
- `tests.test_all_scene_safety::test_failed_voice_with_completed_ai_clips_is_not_recharged_on_compose_retry[claude_api]` (failure)
- `tests.test_blue_studio_browser::test_portrait_library_edit_playback_and_publish_keep_original_boundaries` (failure)
- `tests.test_character_direct_browser::test_character_studio_exposes_only_original_story_flow` (failure)
- `tests.test_character_direct_continuity::test_30_seconds_has_setup_and_continuing_ending_without_a_writer[kling-video/o3/image-reference]` (failure)
- `tests.test_character_direct_continuity::test_30_seconds_has_setup_and_continuing_ending_without_a_writer[kling-video/v3.0/std/image-to-video]` (failure)
- `tests.test_character_direct_continuity::test_second_segment_receives_true_final_frame_and_frozen_context` (failure)
- `tests.test_character_direct_continuity::test_changed_context_never_submits_the_continuation[context]` (failure)
- `tests.test_character_direct_continuity::test_changed_context_never_submits_the_continuation[parent_prompt]` (failure)
- `tests.test_character_direct_continuity::test_failed_or_unknown_parent_does_not_start_or_retry_next_segment[failed]` (failure)
- `tests.test_character_direct_continuity::test_failed_or_unknown_parent_does_not_start_or_retry_next_segment[unknown]` (failure)
- `tests.test_character_direct_continuity::test_continuation_price_increase_stops_before_second_submit` (failure)
- `tests.test_character_direct_video::test_image_topic_to_fake_video_and_final_mp4_has_zero_story_calls[15]` (failure)
- `tests.test_character_direct_video::test_image_topic_to_fake_video_and_final_mp4_has_zero_story_calls[30]` (failure)
- `tests.test_character_direct_video::test_direct_and_story_modes_cannot_share_an_idempotency_key` (failure)
- `tests.test_character_direct_video::test_unknown_direct_submit_is_not_replayed` (failure)
- `tests.test_character_episode_automation::test_fake_pipeline_to_real_mp4[15-\ubcc4-rabbit-claude-sonnet-4-6]` (failure)
- `tests.test_character_episode_automation::test_fake_pipeline_to_real_mp4[35-\ub2ec-penguin-gpt-4.1-mini]` (failure)
- `tests.test_character_episode_automation::test_fake_pipeline_to_real_mp4[60-\ubcc4-rabbit-claude-sonnet-4-6]` (failure)
- `tests.test_character_episode_automation::test_approval_edit_revision_and_unknown_never_replayed` (failure)
- `tests.test_character_episode_automation::test_duration_change_requires_new_script_and_preserves_snapshot` (failure)
- `tests.test_character_episode_automation::test_selected_model_is_frozen_after_script` (failure)
- `tests.test_character_episode_automation::test_sound_off_is_local_edit_without_more_authoring_or_paid_execution` (failure)
- `tests.test_character_episode_editing::test_real_ffmpeg_variable_episode_is_exact_portrait_mp4[15]` (error)
- `tests.test_character_episode_editing::test_real_ffmpeg_variable_episode_is_exact_portrait_mp4[35]` (error)
- `tests.test_character_episode_editing::test_real_ffmpeg_variable_episode_is_exact_portrait_mp4[60]` (error)
- `tests.test_character_episode_editing::test_real_audio_crossfade_contains_both_sources_without_time_shift` (failure)
- `tests.test_character_episode_end_to_end::test_registered_characters_and_generated_topics_reach_final_mp4[15-0-claude_api-claude-sonnet-4-6]` (failure)
- `tests.test_character_episode_end_to_end::test_registered_characters_and_generated_topics_reach_final_mp4[35-1-openai-gpt-4.1-mini]` (failure)
- `tests.test_character_episode_end_to_end::test_registered_characters_and_generated_topics_reach_final_mp4[60-0-claude_api-claude-sonnet-4-6]` (failure)
- `tests.test_character_episode_recovery::test_known_failed_scene_requires_new_approval_and_counts_prior_exposure` (failure)
- `tests.test_character_episode_recovery::test_explicit_failed_retry_keeps_first_receipt_and_dependency_waiting` (failure)
- `tests.test_character_episode_recovery::test_timeout_submission_cannot_enter_failed_retry_path` (failure)
- `tests.test_character_episode_recovery::test_transient_status_failure_can_recover_without_resubmission` (failure)
- `tests.test_character_episode_recovery::test_failed_download_recovers_accepted_request_without_post_retry` (failure)
- `tests.test_character_episode_recovery::test_dependency_quote_increase_never_spends_above_approved_amount` (failure)
- `tests.test_character_episode_recovery::test_tampered_dependency_payload_is_not_uploaded_or_submitted` (failure)
- `tests.test_character_episode_recovery::test_valid_script_and_cost_survive_local_prompt_failure` (failure)
- `tests.test_character_episode_recovery::test_owned_partial_download_is_preserved_then_same_request_downloaded` (failure)
- `tests.test_character_episode_recovery::test_foreign_file_cannot_be_adopted_as_failed_download` (failure)
- `tests.test_character_episode_recovery::test_local_budget_refusal_restores_requestable_state_without_automatic_call` (failure)
- `tests.test_character_episode_regeneration::test_quote_does_not_generate_or_change_old_clips_and_can_be_canceled` (failure)
- `tests.test_character_episode_regeneration::test_only_approved_scene_and_continued_descendant_get_new_attempts` (failure)
- `tests.test_character_episode_regeneration::test_continuation_selected_alone_uses_unchanged_parent_frame` (failure)
- `tests.test_character_episode_regeneration::test_regeneration_exposure_cap_blocks_before_any_new_generation` (failure)
- `tests.test_character_episode_regeneration::test_expired_regeneration_quote_does_not_submit` (failure)
- `tests.test_character_episode_regeneration::test_foreign_clip_path_is_blocked_before_quote_upload` (failure)
- `tests.test_character_episode_regeneration::test_completed_final_and_composition_are_preserved_as_revision` (failure)
- `tests.test_character_kling_media::test_selected_ratio_output_and_audio_survive_real_local_composition[on-9:16]` (failure)
- `tests.test_character_kling_media::test_selected_ratio_output_and_audio_survive_real_local_composition[off-9:16]` (failure)
- `tests.test_character_kling_media::test_voice_request_is_not_silently_replaced_with_silence` (failure)
- `tests.test_character_library_preview_browser::test_character_cards_use_owned_reference_without_inventing_final_media` (failure)
- `tests.test_character_media::test_three_synthetic_episodes_are_1080x1920_30s_without_speech[\uc6d4\uc694\uc77c \uc544\uce68 9\uc2dc 1\ubd84 \uc9c0\uac01]` (error)
- `tests.test_character_media::test_three_synthetic_episodes_are_1080x1920_30s_without_speech[\uc18c\ub780\uc2a4\ub7ec\uc6b4 \ud300 \ud68c\uc758]` (error)
- `tests.test_character_media::test_three_synthetic_episodes_are_1080x1920_30s_without_speech[\uc11c\ubc84 \uc7a5\uc560\uc640 \ub290\uae0b\ud55c \ub300\ub9ac]` (error)
- `tests.test_character_media::test_unused_noncommercial_sfx_is_never_added_to_plain_composition` (error)
- `tests.test_character_media::test_failed_ffmpeg_attempt_can_finish_with_existing_paid_shaped_clips` (error)
- `tests.test_character_media::test_long_root` (error)
- `tests.test_character_natural_timing::test_fake_single_request_no_paid_retry_or_scene_seconds_change` (failure)
- `tests.test_character_natural_timing::test_saved_response_free_recovery_retains_evidence_and_cost` (failure)
- `tests.test_character_natural_timing::test_real_local_ffmpeg_keeps_27_9_seconds_instead_of_padding_to_30` (error)
- `tests.test_character_natural_timing::test_saved_20_17_story_recovers_without_ai_or_rewriting` (failure)
- `tests.test_character_natural_timing::test_real_ffmpeg_preserves_20_17_without_trimming` (error)
- `tests.test_character_plain_compose::test_real_legacy_mixed_audio_stays_in_its_original_scene` (failure)
- `tests.test_character_quote_expiry_review::test_exact_lifetime_without_key_or_network[0-ready]` (error)
- `tests.test_character_quote_expiry_review::test_exact_lifetime_without_key_or_network[900-ready]` (error)
- `tests.test_character_quote_expiry_review::test_exact_lifetime_without_key_or_network[901-expired]` (error)
- `tests.test_character_quote_expiry_review::test_exact_lifetime_without_key_or_network[-1-changed]` (error)
- `tests.test_character_quote_expiry_review::test_invalid_quote_metadata_closed[not-a-date]` (error)
- `tests.test_character_quote_expiry_review::test_invalid_quote_metadata_closed[2026-10-31T00:00:00]` (error)
- `tests.test_character_quote_expiry_review::test_invalid_quote_metadata_closed[None]` (error)
- `tests.test_character_quote_expiry_review::test_expired_submit_specific_reason_no_key_decryption_or_submit` (error)
- `tests.test_character_quote_expiry_review::test_explicit_quote_refresh_keeps_history_and_needs_new_approval` (error)
- `tests.test_character_quote_expiry_review::test_unknown_outcome_remains_blocked_and_cannot_refresh` (error)
- `tests.test_character_story_format::test_new_job_freezes_format_and_reaches_loop_mp4` (failure)
- `tests.test_character_validation_feedback::test_schema_failure_is_stored_safely_and_sent_only_on_next_explicit_request` (failure)
- `tests.test_character_validation_feedback::test_duration_failure_reaches_next_explicit_retry_without_raw_response` (failure)
- `tests.test_character_validation_feedback::test_ambiguous_response_has_no_schema_feedback_and_cannot_be_retried` (failure)
- `tests.test_cloud_workspace_flow::test_api_to_render_review_and_existing_publish_services[openai]` (failure)
- `tests.test_cloud_workspace_flow::test_api_to_render_review_and_existing_publish_services[claude_api]` (failure)
- `tests.test_dashboard_cohesion::test_archive_filters_visual_system_and_auxiliary_routes` (failure)
- `tests.test_feed_connections_browser::test_distinct_background_changes_immediately_without_save_and_keeps_rank` (failure)
- `tests.test_feed_cost_review_browser::test_cost_status_and_expired_additional_quote` (failure)
- `tests.test_feed_growth_browser::test_free_copy_and_manual_performance_browser` (failure)
- `tests.test_final_media::test_four_combinations_local_mp4[False-local-30]` (failure)
- `tests.test_final_media::test_four_combinations_local_mp4[False-elevenlabs-45]` (failure)
- `tests.test_final_media::test_four_combinations_local_mp4[True-local-60]` (failure)
- `tests.test_final_media::test_four_combinations_local_mp4[True-elevenlabs-30]` (failure)
- `tests.test_first_search_budget::test_stale_proof_and_active_auth_check_block[authentication_verified_at-stale-API \uc5f0\uacb0 \ubbf8\ud655\uc778]` (failure)
- `tests.test_news_image_linking::test_real_mp4_every_auto_scene_has_expected_pixels` (failure)
- `tests.test_phase5d1_safety::test_restart_queries_existing_request_and_preserves_ready_clip` (failure)
- `tests.test_production_options_browser::test_skip_review_elevenlabs_fake_to_real_mp4_final_review[openai]` (failure)
- `tests.test_production_options_browser::test_skip_review_elevenlabs_fake_to_real_mp4_final_review[claude_api]` (failure)
- `tests.test_program_review_fixes::test_timing_review_explains_without_changing_story` (failure)
- `tests.test_program_review_fixes::test_timing_review_invalid_numbers_are_not_repaired` (failure)
- `tests.test_quote_rss_settings_browser::test_expired_quote_offers_one_explicit_refresh_not_paid_submit` (error)
- `tests.test_quote_rss_settings_browser::test_fresh_quote_uses_one_bound_cost_approval_at_both_sizes` (error)
- `tests.test_quote_rss_settings_browser::test_open_quote_dialog_expires_without_submitting_or_replaying` (error)
- `tests.test_social_calendar_analytics::test_recommendations_require_comparable_complete_windows_and_one_account` (failure)
- `tests.test_step13j_user_flow::test_synthetic_rss_to_manual_image_video_and_unapproved_local_publish_draft` (failure)
- `tests.test_studio_functional_controls::test_actual_ffmpeg_fade_mp4_and_decoded_frames` (failure)
- `tests.test_usability_browser::test_local_workflow_and_all_screen_design` (failure)
- `tests.test_ux_workflow_settings::test_local_check_is_explicit_cached_and_not_generation` (failure)
- `tests.test_windows_timezone_contract::test_iana_pacific_dst_transition_and_fold[2026-03-08T09:59:00+00:00-1-59--8-0]` (failure)
- `tests.test_windows_timezone_contract::test_iana_pacific_dst_transition_and_fold[2026-03-08T10:00:00+00:00-3-0--7-0]` (failure)
- `tests.test_windows_timezone_contract::test_iana_pacific_dst_transition_and_fold[2026-11-01T08:30:00+00:00-1-30--7-0]` (failure)
- `tests.test_windows_timezone_contract::test_iana_pacific_dst_transition_and_fold[2026-11-01T09:30:00+00:00-1-30--8-1]` (failure)
- `tests.test_windows_timezone_contract::test_iana_seoul_agrees_with_existing_kst_and_calendar_stores_utc[2026-03-08T10:00:00+00:00]` (failure)
- `tests.test_windows_timezone_contract::test_iana_seoul_agrees_with_existing_kst_and_calendar_stores_utc[2026-11-01T09:30:00+00:00]` (failure)
- `tests.test_windows_transition_plan::test_restore_point_update_failure_and_restart` (failure)
- `tests.test_windows_transition_plan::test_additive_upgrade_preserves_every_old_table_and_restore_revision[0016]` (failure)
- `tests.test_windows_transition_plan::test_additive_upgrade_preserves_every_old_table_and_restore_revision[0017]` (failure)
- `tests.test_windows_transition_plan::test_tamper_and_overwrite_refused` (failure)
- `tests.test_windows_transition_plan::test_legacy_migrate_data_is_not_current_backup_tool` (failure)

전체 실패는 별도 목록으로 보존하며 이 작업의 자동 업로드 집중 검사를 통과했다는 이유로 해결됐다고 주장하지 않는다. 이번 작업과 무관한 제품 영역의 변경은 하지 않았다.

전체 실행에서도 Meta 이름의 검사 실패는 없었다. 남은 항목에는 기존 영상 렌더 단계의 상태 불일치, 브라우저의 비활성 검토 체크박스 대기 시간 초과, 캐릭터 제작·Windows 환경 검사가 포함된다. `test_character_media` 등의 fixture는 FFmpeg 경로 미설정, `test_windows_timezone_contract`는 `America/Los_Angeles` 시간대 자료 누락을 보고했다. 이전 보고서에도 전체 회귀 실패가 기록돼 있지만 이번 137개 실패/오류가 모두 동일한 기존 문제라고 단정하지 않는다. 관련 없는 구현이나 검증 조건을 바꿔 전체 통과로 만들지 않았다.

## 외부 검증과 운영 조건

- 실제 저장소 계정/버킷·본인 전용 키 등록, 실제 Meta 계정/권한 수락, 두 실제 계정 간 게시 확인: NOT VERIFIED.
- Instagram 직접 업로드의 Facebook Login for Business/API v26.0 실제 지원 수락: NOT VERIFIED. Meta 문서 직접 조회는 429 제한이 있었고 공식 SDK의 upload_type/파일 API와 문서 계약을 바탕으로 Fake 검증했다.
- 저장소는 S3 SigV4 path-style을 지원해야 한다. STS session token은 지원하지 않는다. 객체 보존/삭제는 버킷 수명주기 설정으로 관리하며 서명 주소 만료가 파일 삭제를 뜻하지 않는다.
- 기존 100MiB 파일 제한과 PNG 원본 보존 JPEG 사본 처리를 유지한다. 실제 미디어 코덱/길이/계정별 수락은 게시 승인 후 검증한다.
- 운영 `C:\NewsFlowAI`, `D:\NewsFlowAI_Data`, 18768 프로세스, 키·백업·원본은 읽거나 변경하지 않았다. 실제 OAuth/게시·유료 생성·업로드·서비스 가입/구매를 하지 않았다.
- main/기존 PR 병합과 운영 배포는 하지 않았다. 기존 미커밋 3개 파일 및 기존 untracked 자료는 유지했다.
- CI: [Windows 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/41435535213), 구현 SHA 기준 성공. Python 3.12와 3.14 각각 Meta 107 PASS, 기존 Fake 제작·FFmpeg·route 151 PASS이며 frontend 계약·React 빌드도 통과했다. 이 집중 CI는 전체 로컬 회귀 결과와 범위가 다르다.

관련 사용법과 외부 조건은 [자동 업로드 사용 안내](META_MULTI_ACCOUNT.md#프로그램-자동-업로드)에 정리했다. 비민감 집계 및 로컬 증거 파일 해시는 [검증 집계](automatic-upload-validation-summary.json)에 보존했다.
