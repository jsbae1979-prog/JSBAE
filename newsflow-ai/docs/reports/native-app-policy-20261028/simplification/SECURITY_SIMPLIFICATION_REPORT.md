# 검증 보안 정책 간소화 결과

사용자의 “불필요한 보안 정책을 제거하고 중요도가 높은 보호만 유지” 지시에 따른 후속 결과다. 이전 차단/CI 기록은 삭제하거나 성공으로 덮지 않는다.

## 제거·간소화한 제한

- 검증 도구 읽기 목록이 바깥 Guard와 안쪽 gate에서 달랐던 중복 제한을 제거했다.
- 고정된 개발 소스/React 자산/검증 도구/Python runtime의 읽기 목록을 한 번 정의해 세 경계에 공유한다.
- 필요한 소스 읽기마다 별도 예외 승인·등록을 반복하는 절차를 없앴다.
- 이 범위의 Windows CI 집중 검증을 다시 허용했다. 운영·로컬 앱 실행 권한을 추가한 것은 아니다.
- IPv6 거부 검사에서 IPv4 소켓을 쓰던 검증 코드만 바로잡았다. 허용 주소/차단 규칙을 완화한 수정이 아니다.

## 유지한 중요 보호

| 보호 대상 | 유지하는 경계 |
|---|---|
| 운영 데이터·코드·백업 | 읽기는 승인된 소스만, 쓰기는 Runner TEMP 합성 workspace만. 운영 DB·ledger·미디어·설정·백업 미사용 |
| 인증정보 | API 키·OAuth·DPAPI 자료 미사용. 상속 환경 제거 및 별도 사본 메모리도 정리 |
| 과금·SNS | 외부 API·DNS·인터넷·게시 차단. 실제 생성·게시 요청하지 않음 |
| SQLite | 등록 합성 DB만. ATTACH/extension/경로 우회/authorizer 교체 차단 |
| 임의 실행 | shell/EXE/제작 worker 차단. 필요한 읽기용 I/O 스레드만 제한 허용 |
| 네이티브 소유권 | 기존 고정 바인딩만. 외부 핸들·포인터·PID·DLL·심볼 거부 |
| 사용자 승인·결과 불명 | 제품의 비용·게시 승인 및 자동 재전송 금지 정책 유지 |
| 변경 통제 | PR #35/main/운영 Guard·실행 경로 수정 없음 |

위 보호는 검증 전용 사본과 CI harness에 적용한다. 운영 Guard를 전역 해제하거나 제품 보안 정책을 변경하지 않았다. 일반 개발에 새 가상화·사용자·방화벽 환경을 요구하지 않는다.

## 재검증 이력

1. 76ef6a5fb47544b37886db50ac7fc2af68817d32 / CI 40534745092: 중복 소스 읽기 차단 해소. 8 PASS / 0 FAIL / 1 ERROR / 0 SKIP.
2. ERROR는 test_07의 AF_INET 소켓에 IPv6 literal을 넣어 감사 경계 전 주소 변환에서 발생한 socket.gaierror였다. 소켓 family를 주소에 맞추어 검사하도록 고쳤다. 이 첫 실행도 실제 증거로 보존한다.
3. 수정 코드 ed79908c250debab480b60f6bbc124e372717934의 최종 CI 결과는 아래에 별도 기재한다.

이전 28·39·32·29 및 7·59·42 PASS는 이전 증거로만 유지한다. 이번 신규 결과에 합산하거나 최신 전체 회귀로 표시하지 않는다.

## 최종 Windows CI 결과

최종 검증 코드: **b0f530d73562284d407011f9de55869b7c8f1204**.
[Windows Actions 40535977417](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40535977417), job 122301194499: **SUCCESS**, Windows Server 2025 / Python 3.14.7.

| 항목 | 이번 실제 결과 |
|---|---|
| 신규 보안 집중 검사 | **9 PASS / 0 FAIL / 0 ERROR / 0 SKIP** |
| Guard-first / 공유 읽기 목록 | true / true |
| 실제 create_app 초기화 | PASS |
| 실제 FileLock·합성 SQLite 저장/닫기/재열기 | PASS |
| 제작실 5개 shell | 모두 HTTP 200 |
| React JavaScript / CSS | HTTP 200, 474,728 / 101,811 bytes |
| 뉴스·쇼츠·캐릭터·이미지 모듈 읽기 API 4개 | 모두 HTTP 200, schemaVersion=1 |
| CSP | 기존 제한 유지, unsafe-inline/unsafe-eval 없음 |
| native Rtl 할당·해제 | 8 / 8 |
| 잔여 native handle / CRT descriptor / buffer / unresolved call | 0 / 0 / 0 / 0 |
| SQLite 연결 닫기 | 4개 닫힘 / 잔여 0 |
| 읽기용 I/O 스레드 | 1개 생성 / 종료 후 잔여 0 |
| 테스트 자식 프로세스 / 잔여 합성 파일 / cleanup error | 0 / 0 / 0 |
| 패키지 소스·기존 차용 코드·native 표 | 불변 true |
| 실제 유료 API·OAuth·SNS 호출 | 0 |

화면은 /studio/shorts, /studio/characters, /studio/images, /studio/images?mode=top3, /studio/news다. 직접 ASGI 메시지로 실제 동일 앱의 HTTP 응답을 받았다. 정적 이미지나 응답을 Fake로 대체하지 않았다. Python create_app 진입점·Guard-first 순서도 유지했다.

HTTPX의 불필요한 CLI/Click 콘솔 import를 제거하여 native 권한을 추가할 필요가 없어졌다. 기존 ctypes DLL/심볼 제한과 실제 FileLock/Rtl 메모리 소유권 경계는 그대로 유지했다. DLL을 미리 import하거나 차단된 API를 다른 native 경로로 호출하지 않았다.

9 PASS는 보안 테스트 수이며, 5개 shell·2개 자산·4개 API 응답을 합쳐 20 PASS 테스트로 계산하지 않는다. 이전 실행의 PASS 수와도 합산하지 않는다.

[최종 artifact 12748646799](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40535977417/artifacts/12748646799), ZIP SHA-256:
`de88c0cc114caa77ea10d0d9b53c4bf1164164833c0c1569f05aca9a58a484d8`.

## 판정과 남은 범위

- **정책 간소화 및 승인된 CI 초기화·읽기 응답 검증: 완료/PASS.**
- **전체 앱 인수 상태: CONDITIONAL.** 실제 Windows 11 로컬 GUI, 브라우저 React 실행, 실제 OS DPI, lifespan 전체 수명주기·스케줄러 실행은 이번 검증이 아니다.
- 자동/유료 생성·실제 SNS 게시 기능을 실행하거나 검증했다고 주장하지 않는다. 5개 제작실 전체 사용자 동선은 기존 합성 브라우저 증거와 구분한다.
- 소스 읽기 및 HTTP 테스트 의존성 때문에 발생했던 두 차단은 해소됐다. 같은 낮은 위험 항목의 별도 승인 절차를 반복하지 않는다.
- 이번 범위 밖의 운영 적용·운영 앱 제어·실계정 API·OS 설정 변경은 계속 별도 승인 대상이다.

## 변경 파일과 보존

변경은 tools/native_app_policy/의 verification_gate_app.py, run_app_policy.py, test_app_policy.py, app_initialization.py, provenance/hash/README, 전용 workflow에 한정했다. 제품 src/frontend, 운영 Guard, 설치된 filelock 및 기존 네 검증 도구 폴더는 변경하지 않았다. 앱 엔진/DB migration/API 계약도 수정하지 않았다.

브랜치 codex/newsflow-core-studios-rebuild-20261027에 보존했다. PR #35/main/운영 브랜치 변경·병합은 하지 않았다. 운영 DB·ledger·키·설정·미디어·백업을 입력으로 사용하거나 변경하지 않았다. 운영 앱은 제어하지 않았으며 운영 포트 8765는 거부 검사에서만 사용해 연결 전에 차단했다. 기존 untracked validation/도 보존했다.

이전 c650df5의 BLOCKED 보고는 당시 결과로 보존하며, 이번 실제 CI 증거가 해당 검증 소스 읽기/초기화 차단의 후속 해소 결과다. 새 전체 회귀를 실행한 결과가 아니다. 추가 실행·운영 전환 없이 종료한다.
