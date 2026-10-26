# Windows 합성 통합 검증 절차

사용자가 승인한 기존 GitHub Actions Windows 임시 Runner만 사용합니다. 로컬 Guard 차단 경로를 재실행하거나 사전 import로 우회하지 않습니다.

- Windows/Python 3.14.7 및 GITHUB_ACTIONS 환경 확인
- Runner 임시 위치의 새 합성 DB·AppData, 실제 인증 환경변수 제거
- 실제 네트워크·공급사 transport·subprocess는 테스트 fixture에서 실패하도록 대체
- 예약 start만 모의 처리하고 테스트 종료 시 기존 lifespan 정리 사용
- 원래 create_app, CSRF/Origin middleware, 원래 URL-encoded/multipart 폼과 서비스 실행
- 이미지 Adapter는 단일 Fake 결과만 반환하며 유료 호출 0회
- 실제 키·운영 DB·미디어·백업 접근 없음
- 이 결과는 Windows Runner 통합 증거이며 PC의 Guard 아래 전체 앱 기동 PASS를 의미하지 않습니다.
