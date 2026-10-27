# 실행한 테스트 ID

최종 Windows CI: 28 PASS. 신규 26개, 기존 재사용 경로 2개. skip/xfail 없음.

1. `test_real_filelock.RealFileLockTests.test_01_real_guard_first_package_import` — PASS
2. `test_real_filelock.RealFileLockTests.test_02_actual_acquire_zero_release` — PASS
3. `test_real_filelock.RealFileLockTests.test_03_real_contention_timeout` — PASS
4. `test_real_filelock.RealFileLockTests.test_04_positive_timeout_and_recovery` — PASS
5. `test_real_filelock.RealFileLockTests.test_05_actual_context_proxy_and_nested_reentrancy` — PASS
6. `test_real_filelock.RealFileLockTests.test_06_default_cleanup_attempt_and_file_reuse` — PASS
7. `test_real_filelock.RealFileLockTests.test_07_preserve_file_option_does_not_unlink` — PASS
8. `test_real_filelock.RealFileLockTests.test_08_CRT_owner_not_native_CloseHandle_owner` — PASS
9. `test_real_filelock.RealFileLockTests.test_09_upstream_external_descriptor_is_rejected` — PASS
10. `test_real_filelock.RealFileLockTests.test_10_external_synthetic_path_denied_before_Rtl` — PASS
11. `test_real_filelock.RealFileLockTests.test_11_UNC_ADS_device_and_relative_denied_without_OS_probe` — PASS
12. `test_real_filelock.RealFileLockTests.test_12_real_Rtl_allocate_and_free_once` — PASS
13. `test_real_filelock.RealFileLockTests.test_13_Python_and_arbitrary_pointer_cannot_be_freed` — PASS
14. `test_real_filelock.RealFileLockTests.test_14_in_use_buffer_cannot_be_freed_during_real_NT_call` — PASS
15. `test_real_filelock.RealFileLockTests.test_15_changed_user_pointer_denied_before_free` — PASS
16. `test_real_filelock.RealFileLockTests.test_16_unknown_buffer_owner_is_not_freed` — PASS
17. `test_real_filelock.RealFileLockTests.test_17_Rtl_output_is_validated_and_rejected_allocation_is_freed` — PASS
18. `test_real_filelock.RealFileLockTests.test_18_post_free_notification_does_not_double_free` — PASS
19. `test_real_filelock.RealFileLockTests.test_19_native_lock_unknown_outcome_not_replayed` — PASS
20. `test_real_filelock.RealFileLockTests.test_20_unlock_unknown_preserves_logical_lock_no_native_replay` — PASS
21. `test_real_filelock.RealFileLockTests.test_21_close_failure_before_and_after_commit` — PASS
22. `test_real_filelock.RealFileLockTests.test_22_process_and_unknown_DLL_symbol_blocked` — PASS
23. `test_real_filelock.RealFileLockTests.test_23_callbacks_and_unbounded_wait_not_enabled` — PASS
24. `test_real_filelock.RealFileLockTests.test_24_Guard_network_process_and_operating_port_unchanged` — PASS
25. `test_real_filelock.RealFileLockTests.test_25_final_handle_metadata_is_rechecked` — PASS
26. `test_real_filelock.RealFileLockTests.test_26_actual_default_unlink_success_under_owned_generation` — PASS
27. `test_capability.CapabilityTests.test_27_parent_junction_is_denied` — PASS
28. `test_capability.CapabilityTests.test_31_handle_path_mismatch_is_denied` — PASS

기존 39/32/29 전체 묶음은 재실행하지 않았다. 현재 결과와 합산하지 않는다.
