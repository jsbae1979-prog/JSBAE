# 실제 설치 시작 설정 후보 (미적용)

별도 합성 검증에서 BAT와 기본 브라우저 자동 열기를 확인했다. 실제 설치본 적용은 자동 심사에서 별도 승인 대상으로 거절돼 아직 실행하지 않았다.

- 대상1: `<CURRENT_USER_HOME>/AppData/Local/NewsFlowAI-BAT/launch.json`
- 변경1: `openBrowser: false` → `true`
- 대상2: `C:/NewsFlowAI/app/layout.json`
- 변경2: `validationConfigSha256`을 후보 launch.json 바이트의 SHA-256에 결속
- `readOnly: true`, `decryptCredentials: false`, 포트18768, 프로필종류, 설치 ID와 데이터 경로는 유지
- 실제169 DB·키·미디어·자동화·유료API·SNS 권한 변경 없음
- 프로그램 코드와 기존 운영본을 변경/실행하지 않음

실제 파일 후보는 비공개 `local-write-results/prepared-start-config`에 보존한다. 승인 후 적용 전 현재 파일과의 동일성/두 필드 차이만 재확인하면 된다. 실제169 쓰기 활성화와는 별개다.
