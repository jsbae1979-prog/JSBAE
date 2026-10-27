# 신규 보안 검사 상태

9개 신규 case는 작성했으나 Guard 차단으로 실행 결과를 확보하지 못했다. 모두 NOT VERIFIED이며 skip/xfail로 처리하지 않았다.

- test_01_synthetic_file_roundtrip_and_external_write_denied — NOT VERIFIED
- test_02_UNC_ADS_device_relative_and_credential_paths — NOT VERIFIED
- test_03_reparse_inspection_and_link_creation_denied — NOT VERIFIED
- test_04_registered_SQLite_transaction_close_reopen — NOT VERIFIED
- test_05_SQLite_ATTACH_extension_factory_and_URI_denied — NOT VERIFIED
- test_06_owned_literal_loopback_exchange — NOT VERIFIED
- test_07_operating_port_external_DNS_proxy_and_unowned_loopback_denied — NOT VERIFIED
- test_08_process_and_background_thread_denied — NOT VERIFIED
- test_09_actual_FileLock_in_app_data_directory — NOT VERIFIED
