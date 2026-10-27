# 집중 테스트 ID별 결과

코드: `48c93e55cf37baaac03e1541871400f1bc376125`

신규 24개 + 기존 영향 범위 8개 = **32 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
변경 없는 upstream filelock/기존 Guard 직접 통합은 BLOCKED이며 이 목록의 PASS와 구분한다.

| 테스트 ID | 결과 | 구분 |
|---|---|---|
| `test_contract_bridge.IntegrationTests.test_01_guard_first_and_no_preimport` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_02_actual_filelock_source_contract_matches` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_03_existing_Guard_registration_stays_blocked` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_04_registration_before_guard_denied` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_05_unknown_capability_denied` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_06_native_reentrancy_retains_outer_lock` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_07_context_proxy_does_not_double_acquire` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_08_nested_contexts_and_body_exception` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_09_timeout_rolls_back_only_failed_session` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_10_nonblocking_attempt` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_11_unbounded_and_unsupported_options_blocked` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_12_unheld_release_is_noop` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_13_explicit_force_releases_only_owned_lock` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_14_cross_thread_denied` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_15_descriptor_PID_DLL_exports_blocked` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_16_paths_cannot_be_smuggled_as_registration_names` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_17_unlock_failure_retains_lock_and_journal` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_18_post_unlock_close_failure_is_not_held` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_19_uncertain_acquire_is_not_replayed` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_20_context_body_and_release_failure_both_preserved` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_21_journal_failure_blocks_new_execution` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_22_closed_session_and_registry_deny_reuse` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_23_sessions_do_not_change_each_others_state` | PASS | 신규 |
| `test_contract_bridge.IntegrationTests.test_24_restart_record_does_not_authorize_reacquire` | PASS | 신규 |
| `test_capability.CapabilityTests.test_01_guard_first` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_02_real_exclusive_lock_and_release` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_05_raw_and_forged_handles` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_20_external_PID_blocked_before_OS` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_21_raw_DLL_blocked` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_27_parent_junction_is_denied` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_31_handle_path_mismatch_is_denied` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_33_failed_unlock_preserves_state` | PASS | 기존 영향 범위 |
