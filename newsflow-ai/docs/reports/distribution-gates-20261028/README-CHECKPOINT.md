# 이번 배포 차단 보완의 재개 지점

현재 코드의 실제 공개 배포 가능 여부는 `DISTRIBUTION_GATES_REPORT.md`를 따른다.
`secured-build-summary.json`은 로컬 EXE, `ci-*.json`은 Windows CI를 식별한다.

제품 구현은53207f8, 검증기 최종 기준은1ab226a다. 이후 보고서/README만 추가하는
문서 커밋은 동일 구현의 성공 CI를 재사용한다. 문서 전용 커밋의 `[skip ci]`는
중복 실행을 생략하기 위한 것이며 실행한 검사나 실패를 숨기는 용도가 아니다.
실패한 CI1도 보존하며 pytest skip/xfail 추가나 실패 결과 삭제는 하지 않는다.

다음 작업에서 같은 GUI/Guard/전체 회귀를 다시 시작하지 않는다. 필요한 것은
샘플 권리 증빙, 정확한 GPL source/build bundle, 실제 publisher 인증서 및
별도 Windows 사용자/새 PC/DPI 환경이다. 그 자료 없이 플래그만 바꾸거나
가짜 서명·가짜 연결·가짜 한국어 음성 성공으로 완료 처리하지 않는다.
