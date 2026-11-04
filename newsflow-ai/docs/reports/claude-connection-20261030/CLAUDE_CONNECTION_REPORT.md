# Claude 연결 확인 복구 결과

최종 판정: **ACCEPTED — Claude 인증·모델 조회와 Chrome 표시 복구 범위**. 유료 생성·검색·결제 가능성은 검증하지 않았다.

## 원인

1. 전환 전 백업에 있던 Claude 인증 확인 기록은 기존 24시간 유효기간이 지나 만료되어 있었다. API 키 자체가 만료되었다는 뜻은 아니다.
2. BAT 운영 실행 경계에 기존 `POST /api-settings/claude_api/check` 연결이 빠져 있었다. 경로만 추가하면 일반 보호 저장소의 복호화 제한에 걸리므로, 정상 인증 요청 범위에서만 해당 저장 키를 사용하는 연결이 필요했다.
3. React 공통 조회의 `verified=False`와 키 등록 여부만 보는 문구 때문에 실제 인증 결과도 화면에 반영되지 않았다.

## 최소 수정

- `tools/bat_distribution/claude_connection_check.py`: 정확한 Claude 확인 경로에서 기존 로컬 인증·Origin·CSRF 통과 후 현재 프로필의 보호 저장소만 사용한다. 선택 모델의 공식 HTTPS 모델 정보 GET 한 번, 본문 없음, 기존 15초·64KiB·리다이렉트 차단을 유지한다.
- `src/newsflow/gui/api_settings_routes.py`, `tools/bat_distribution/windows_live.py`: 기존 API와 운영 요청 범위 연결. 일반 실행 경로와 다른 공급사·생성·검색 요청의 기존 정책은 유지한다.
- `src/newsflow/gui/studio_v3.py`: 등록 키와 현재 모델의 유효한 인증 기록을 함께 조회한다. 키값은 읽지 않는다.
- `frontend/src/studio/management/Settings.tsx`, `frontend/src/studio/Workbench.tsx`: 실제 결과를 ‘인증 확인 / 인증·모델 확인’으로 표시한다. 공통 생성 완료 상태 문구는 변경하지 않았다.
- 신규 검사: `tests/test_claude_operating_connection_check.py`, `tests/test_claude_connection_ui.py`.

[Claude 공식 Models API](https://platform.claude.com/docs/en/api/http/models/retrieve)의 GET 계약을 재사용한다. 키 등록·삭제, TTL 변경, 생성 승인, 1회 비용 한도 변경, 전역 복호화·네트워크 허용은 추가하지 않는다.

## 집중 검증

- 신규 **38 PASS / 0 FAIL / 0 ERROR**: 요청 경계 31개, 조회·합성 Chrome 상태 7개.
- TypeScript·React 빌드 PASS.
- 실제 조회 후 인증 배지가 ‘생성 완료’로 표시되는 문구 결함을 발견해 정적 UI만 보정했다. 해당 Chrome 검사 1개를 강화하여 **1 PASS 재검증**했고 기존 6개 조회 검사는 반복하지 않았다. 중복 재검증을 새 테스트 수로 합산하지 않는다.
- 최초 합성 테스트의 fixture 위치 문제 setup ERROR 31건과 빈 proof 필드 기대값 FAIL 1건은 테스트 준비·기대값을 고쳐 해결했다. UI 테스트의 제한된 Windows 내부 socketpair 초기화 대기 2회는 assertion 이전에 중단했고 승인된 실행 환경에서 통과했다. 운영 또는 공급사 실패로 기록하지 않는다.
- 전체 회귀·패키징·기존 GUI 검증은 반복하지 않았다. 개발·테스트의 실제 공급사 호출은 0회다.

## 승인 후 운영 확인

사용자의 ‘운영 반영·Stop/Start 1회·모델 조회 승인’에 따라 적용했다.

- 정상 Stop **1회**, 종료 코드 **0**. 정상 Start **1회**. 운영 `127.0.0.1:18768`, 소유 PID `32312`.
- 변경 전 프로필 128개 항목과 변경 프로그램·설정을 별도 보관했다. 정상 재시작 직후 47개 테이블·기사 169건·127개 비일시 프로필 파일 불변을 확인했다.
- 사용자가 보는 새 Chrome에서 기존 정상 인증 후 ‘Claude API’를 선택하여 모델 정보 조회를 **한 번** 제출했다. `claude-sonnet-4-6` 인증·모델 확인 성공. 자동 재요청 0회, 유료 생성 0회, SNS 0회.
- 인증 확인 후 47개 테이블 유지, 기사 169건 및 설정 외 46개 테이블 불변. 설정은 인증 확인 시각 관련 3개 값만 갱신됐고 나머지 사용 승인·한도·모델 설정은 불변이다.
- DB를 제외한 비일시 프로필 파일 125개, 저장 키·미디어·원본 DB·백업 A/B 보존을 확인했다. 키·토큰·쿠키 원문은 출력하거나 업로드하지 않았다.
- 배지 문구는 정적 파일 2개만 추가 반영했다. **추가 재시작 0회**, PID·DB·설정·ACL 불변을 확인했다.
- Chrome 새로고침 후 최종 배지 **‘인증 확인’**, 세부 문구 **‘인증·모델 확인’**을 직접 확인했다. Chrome 설정 화면을 열어 두었다.

운영 Python 연결 구현 SHA: `f91afae3c979cef9636c9aa5e0a7fc1357e49826`. 최종 UI 포함 구현 SHA: `464493cab1db21e108c044430cfbd301b8849d7b`. 보고서 후속 커밋은 운영 코드 변경이 아니다. 브랜치: `codex/newsflow-character-shorts-automation-20261030`.

## 범위와 남은 확인

이번 작업은 Claude 연결 확인 복구까지다. 실제 스토리·이미지·영상 생성, 계정 청구·잔액, 웹 검색, 다른 공급사 인증을 성공했다고 주장하지 않는다. 기존 실패 기록을 지우거나 유료 요청을 재전송하지 않았다. main·PR #35·운영 데이터·백업은 변경하지 않았고 외부 배포·PR 병합은 하지 않았다.
