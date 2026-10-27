# Guard 사본·CRT 접점 보안 테스트

검증 코드: `b9fa0426cb676c20c1223359e92e2548b63b0e02`

27개 신규 + 2개 기존 영향 범위 = **29 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
filelock 전체 import 거부 검사의 PASS는 실제 filelock 실행 성공을 의미하지 않는다.

| ID | 결과 | 구분 |
|---|---|---|
| `test_copy_boundary.CopyBoundaryTests.test_01_real_Guard_copy_first` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_02_guard_AST_delta_is_only_registration` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_03_registration_is_once_only` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_04_CRT_transfer_removes_native_close_ownership` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_05_real_lock_contention_and_release` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_06_reentrancy_keeps_outer_OS_lock` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_07_CRT_close_never_calls_native_CloseHandle` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_08_foreign_closed_and_integer_descriptors_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_09_raw_CRT_transfer_is_not_a_capability` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_10_external_path_and_handle_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_11_UNC_ADS_device_relative_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_12_buffer_lifetime_and_double_free` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_13_in_use_buffer_cannot_be_freed` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_14_native_Rtl_conversion_and_free_remain_blocked` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_15_pre_transfer_failure_has_native_owner_cleanup` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_16_post_transfer_notification_retains_descriptor_and_blocks_replay` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_17_pre_close_failure_preserves_owned_descriptor` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_18_post_close_notification_is_not_a_live_descriptor` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_19_unlock_failure_does_not_drop_ownership` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_20_raw_DLL_and_unregistered_symbol_still_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_21_external_PID_and_descriptor_export_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_22_network_process_and_DB_boundaries_preserved` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_23_write_to_configured_project_remains_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_24_invalid_timeout_and_foreign_buffer_denied` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_25_native_lock_success_then_error_is_not_replayed` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_26_private_CRT_dispatch_requires_pending_owned_transfer` | PASS | 신규 |
| `test_copy_boundary.CopyBoundaryTests.test_99_unmodified_filelock_import_still_fails_closed` | PASS | 신규 |
| `test_capability.CapabilityTests.test_27_parent_junction_is_denied` | PASS | 기존 영향 범위 |
| `test_capability.CapabilityTests.test_31_handle_path_mismatch_is_denied` | PASS | 기존 영향 범위 |
