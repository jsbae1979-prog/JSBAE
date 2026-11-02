# 직접 토큰 연결·외부 저장소 검증

기준: `8f8d2f954f9c710c93bdf21f1c4a4fc66827b19e`의 Meta 다중 계정 기능. 작업 브랜치는 `codex/newsflow-character-shorts-automation-20261030`이다.

## 변경 범위

- `meta/direct.py`: 기존 검증된 grant 파서를 재사용하는 본인 사용자 토큰 조회. 앱 시크릿·로그인 중계·토큰 교환 없이 GET만 사용한다.
- `meta/service.py`, `graph.py`, `routes.py`: 직접 조회/페이지 선택/재연결, 소유자·만료·권한 검증, 안전한 오류 응답. 기존 서버 로그인과 연결 기록은 보존한다.
- `meta/storage.py`, `media.py`, `publishing.py`: 외부 저장소 임시 PUT/GET URL 암호화, 파일 해시별 전달, 게시 승인 후 업로드, 다운로드 해시 검증, 결과 불명 재전송 차단.
- `MetaAccounts.tsx`, `MetaPublishPanel.tsx`: 토큰 입력 및 페이지 선택을 기본 화면에 배치하고, 게시 대상별 저장소 연결을 제공한다. 토큰과 주소는 저장 요청 뒤 입력칸에서 지운다.
- 두 action 카탈로그 및 BAT 정확한 경로 목록에 새 POST 경로 2개 등록. 기존 전역 외부 실행 차단과 LocalAccess/Origin/CSRF는 유지한다.
- Windows CI의 Python 3.12/3.14 작업에 Fake Meta 검사를 추가한다. 실제 CI 결과와 로컬 검사는 구분한다.

## 안전 경계

모든 검사는 별도 임시 DB, 합성 토큰, Fake Graph/저장소, 독립 headless 브라우저로 수행했다. 실제 사용자의 토큰·키를 읽거나 등록하지 않았다. 실제 로그인, API 조회, 미디어 업로드, 게시, 운영 파일/DB migration, Stop/Start는 하지 않았다. 기존 미커밋 변경과 운영 데이터·키·이미지·영상·백업은 변경 대상에서 제외했다.

## 검증 명령 및 결과

기본 `python` 대신 기존 Windows Python 3.12/3.14 가상환경 실행파일을 사용했으며 `PYTHONPATH=src;tools;tests`로 실행했다. 아래 검사는 겹치는 항목이 있으므로 합산하지 않는다.

| 검사 | 명령 | 로컬 결과 |
|---|---|---|
| Meta 계정·직접 등록·게시·브라우저 | `python -m pytest -q -rs --tb=short tests/test_meta_accounts.py tests/test_meta_direct.py tests/test_meta_browser.py` | Python 3.14: 73 PASS / 0 FAIL / 0 SKIP |
| Python 3.12 호환 | `python -m pytest -q -rs --tb=short tests/test_meta_accounts.py tests/test_meta_direct.py` | 70 PASS / 0 FAIL / 0 SKIP |
| 이후 저장소 동시 변경·중단 보완 포함 | `python -m pytest -q -rs --tb=short tests/test_meta_direct.py` | Python 3.14: 26 PASS / 0 FAIL / 0 SKIP (앞선 23개 + 신규 3개) |
| 두 action 카탈로그·studio_v3 | `python -m pytest -q -rs --tb=short tools/studio_v3/tests` | 58 PASS / 0 FAIL / 0 SKIP |
| frontend 계약 | `node --test tests/*.test.mjs` | 47 PASS / 0 FAIL / 0 SKIP |
| React | `tsc --noEmit`, `vite build --configLoader runner` | PASS |
| 변경 Python 정적 검사 | `ruff check --no-cache src/newsflow/meta tests/test_meta_direct.py tools/bat_distribution/meta_access.py` | PASS |

Windows CI에는 위 Meta 3개 테스트 파일을 연결했다. 로컬 성공을 GitHub CI 성공으로 표시하지 않는다.

직접 등록 이전 실패 재검증(기존 작업의 결과): 93 PASS / 2 FAIL. 남은 실패는 `test_feed_cost_review_browser::test_cost_status_and_expired_additional_quote`, `test_feed_growth_browser::test_free_copy_and_manual_performance_browser`이다. 이번 Meta 변경으로 고쳤다고 주장하지 않는다.

전체 Python 검사는 `python -m pytest -q -rs --tb=short`로 별도 실행 중이며, 완료 수치는 후속 결과에 기록한다. 이전 전체 회귀가 통과했다고 주장하지 않는다. 전체 실행 이후의 저장소 보완은 별도 26개 집중 검사로 확인했다.

## 남은 조건

- 실제 본인 사용자 토큰으로 `debug_token` 및 페이지 목록 권한·API v26.0 수락 확인. 실패 시 앱 시크릿 내장이나 검증 생략으로 우회하지 않는다.
- 사용자 소유 외부 저장소와 해당 파일의 임시 PUT/GET 주소 준비. 본 구현은 서명 주소 소비자이며 저장소 사업자의 주소 발급 서비스가 아니다.
- 사용자 승인 계정·콘텐츠에 한해 실제 업로드/게시 검증. 별도 Windows 사용자 DPAPI 검증, 두 번째 실제 Meta 계정 연결은 미검증이다.
- Meta 앱 심사/고급 액세스/비즈니스 인증/정책 페이지 요건은 별도 유지된다. 직접 토큰 등록이 일반 사용자 공개 배포 승인으로 해석되지 않는다.

판정: 개발 기능 CONDITIONAL. 운영 적용·실제 연결·실제 게시는 미수행이다.
