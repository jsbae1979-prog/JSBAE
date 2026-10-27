# 신규 보안 테스트 ID별 결과

검증 코드: `4774553264b19cd4fc7b63f272a00b521f4acdb9`

Windows Python 3.14.7 / Windows Server 2025. 전체 앱 테스트가 아니다.

| 테스트 ID | 결과 |
|---|---|
| `test_01_guard_first` | PASS |
| `test_02_real_exclusive_lock_and_release` | PASS |
| `test_03_contention_timeout` | PASS |
| `test_04_closed_and_recycled_capability` | PASS |
| `test_05_raw_and_forged_handles` | PASS |
| `test_06_foreign_scope_capability` | PASS |
| `test_07_foreign_registration` | PASS |
| `test_08_unheld_unlock` | PASS |
| `test_09_wrong_thread_unlock` | PASS |
| `test_10_invalid_timeout` | PASS |
| `test_11_external_synthetic_path` | PASS |
| `test_12_UNC_and_device` | PASS |
| `test_13_ADS` | PASS |
| `test_14_relative_parent_and_drive_relative` | PASS |
| `test_15_ambiguous_names` | PASS |
| `test_16_preexisting_file_not_truncated` | PASS |
| `test_17_double_registration` | PASS |
| `test_18_closed_scope` | PASS |
| `test_19_native_symbol_not_exposed` | PASS |
| `test_20_external_PID_blocked_before_OS` | PASS |
| `test_21_raw_DLL_blocked` | PASS |
| `test_22_arbitrary_symbol_blocked` | PASS |
| `test_23_network_and_DNS_blocked` | PASS |
| `test_24_child_process_blocked` | PASS |
| `test_25_no_implicit_reentrancy` | PASS |
| `test_26_active_scope_cannot_be_renamed` | PASS |
| `test_27_parent_junction_is_denied` | PASS |
| `test_28_nested_junction_is_denied` | PASS |
| `test_29_leaf_reparse_is_denied` | PASS |
| `test_30_existing_hardlink_is_denied` | PASS |
| `test_31_handle_path_mismatch_is_denied` | PASS |
| `test_32_file_identity_mismatch_is_denied` | PASS |
| `test_33_failed_unlock_preserves_state` | PASS |
| `test_34_failed_close_preserves_ownership` | PASS |
| `test_35_grant_cannot_be_forged_or_reused` | PASS |
| `test_36_binding_window_cannot_be_reopened` | PASS |
| `test_37_grant_path_tampering` | PASS |
| `test_38_raw_function_address_is_denied` | PASS |
| `test_39_private_backend_rejects_foreign_handle_before_OS` | PASS |

39 PASS / 0 FAIL / 0 ERROR / 0 SKIP. Native 핸들 및 합성 자료 정리까지 성공.
