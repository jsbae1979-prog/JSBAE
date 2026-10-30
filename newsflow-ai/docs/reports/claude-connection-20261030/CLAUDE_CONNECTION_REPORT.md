# Claude 연결 확인 복구 준비

현재 판정: **CONDITIONAL** — 개발 수정·합성 검증 완료, 운영 적용 및 실제 인증 확인 대기.

## 확인된 원인

사용자가 보는 인증된 Chrome의 설정에서 Claude 키 저장 상태와 `claude-sonnet-4-6` 선택은 확인했다. 그러나 운영 실행 경계에 기존 `POST /api-settings/claude_api/check` 연결이 없어 요청이 처리되지 않는 구조다. 경로만 추가하면 일반 키 저장소의 의도된 복호화 차단 때문에 확인할 수 없으므로 두 연결을 함께 복구했다. 또한 React 공통 조회가 `verified=False`로 고정되어 있고 화면도 키 저장 여부만 보고 미검증 문구를 표시했다. 실제 기록이 존재해도 확인 상태가 반영되지 않는 표시 결함을 함께 보정한다. 키 자체가 잘못되었거나 현재 확인 기록이 만료되었다고 단정하지 않는다. 실제 공급사 요청은 보내지 않았다.

## 최소 수정

- `tools/bat_distribution/claude_connection_check.py`: 정확한 Claude 확인 경로에서 기존 로컬 인증·Origin·CSRF 통과 후 현재 프로필의 보호 저장소를 사용한다. 선택된 모델의 공식 HTTPS 모델 정보 GET 한 번, 본문 없음, 기존 15초·64KiB·리다이렉트 차단을 유지한다.
- `src/newsflow/gui/api_settings_routes.py`: 운영 실행기가 제공한 확인 함수를 연결한다. 기존 일반 실행 경로는 유지한다.
- `tools/bat_distribution/windows_live.py`: 정상 운영 프로필에 위 연결을 설치한다. 합성·검증 실행 경로를 확대하지 않는다.
- `tests/test_claude_operating_connection_check.py`: Fake 저장소·응답으로 연결과 보호 동작을 검증한다.
- `src/newsflow/gui/studio_v3.py`와 React 설정 표시: 키 등록 상태와 현재 모델의 유효한 인증 기록을 함께 확인한다. 인증 확인은 생성·검색·결제 성공과 구분한다.

모델 조회는 [Claude 공식 Models API](https://platform.claude.com/docs/en/api/http/models/retrieve)의 GET 계약을 사용한다. 인증·모델 조회 성공이 유료 생성·검색·결제 가능성을 증명하지는 않는다. 기존 생성 승인, 회차별 비용 한도, 24시간 인증 확인 기간과 모델 변경 시 무효화는 유지한다. 키 재등록·삭제, 전역 복호화 및 외부 실행 허용은 추가하지 않는다.

## 검증

집중 검사 **38 PASS / 0 FAIL / 0 ERROR** (신규 38, 영향받는 기존 0). 연결 경계 31개와 상태 조회·합성 Chrome 화면 7개다. TypeScript 검사·React 빌드·diff 검사 PASS. 모든 외부 통신과 복호화는 합성 대역이며 실제 키·운영 DB를 사용하지 않았다. 세부 테스트는 `SAFE_EVIDENCE.json`에 기록한다. 기존 전체 회귀·GUI·패키징 결과를 재사용했고 다시 실행하지 않았다.

첫 테스트 실행은 새 테스트 파일 위치에 공용 합성 app fixture가 적용되지 않아 setup ERROR 31건이 발생했다. 기존 공용 fixture가 적용되는 tests 경로로 이동해 해결했다. 이후 기존 연결 서비스가 최초 확인 시 빈 검색·생성 proof 필드 2개를 만드는 정상 동작을 기대값이 누락해 테스트 FAIL 1건이 발생했고 기대값을 보정했다. 실제 운영 실행이나 외부 API 요청은 없었다.

UI 테스트는 제한된 Windows 실행 환경에서 TestClient의 내부 socketpair 초기화가 대기하여 assertion 이전에 2회 중단했다. 정상 승인된 실행 환경에서 동일한 합성 검사 7개가 통과했으며 제품 코드나 보안 정책을 변경해 통과시키지 않았다.

## 운영 상태와 다음 작업

운영 코드·설정·데이터·키·미디어·백업은 변경하지 않았다. 정상 Stop·Start를 아직 수행하지 않았다. 실행 중인 Python에 반영하려면 새 사용자 승인이 필요하다. 승인 후 기존 보존 절차로 정확한 Python 4개와 React 빌드 변경 파일만 적용하고, Chrome에서 기존 인증 경로로 모델 정보 조회 1회만 확인한다. 생성·SNS는 실행하지 않으며 실패 시 자동 재요청하지 않는다.

## 운영 반영 후보

구현 SHA: `f91afae3c979cef9636c9aa5e0a7fc1357e49826`. 기존 운영 전용 연결을 보존하는 정확한 문맥 수정으로 Python 4개와 React 자산 2개를 별도 폴더에 준비했다. 운영 원본은 변경하지 않았다.

- `app/product/newsflow/gui/api_settings_routes.py` — SHA-256 `6c617630231d6a39299851343f6159a9a017865e73c05d94743fb344cd319e13`
- `app/product/newsflow/gui/studio_v3.py` — SHA-256 `b5e5155d1998feefaf83d0159e8810113143ccc93b5d5d1ebc158de4eaf486df`
- `app/controller/bat_distribution/claude_connection_check.py` — SHA-256 `2dd40b0bd34127c2aa44f543d702312a20e3b26a739642b5ff7ea0318061161f`
- `app/controller/bat_distribution/windows_live.py` — SHA-256 `276e0b270abcea2c0e4459299be225313f9da28262a5049feae3e46a6ce0ebb5`
- `app/frontend/dist/assets/index-WABMv2Ne.js` — SHA-256 `96e8610c6d643bc5c04f4a2f25878823912e3d2f6c33253e05599869bb7dd7d7`
- `app/frontend/dist/index.html` — SHA-256 `7e0b87e1c7e93f0c379ce31d49a3ba6770756c0d1faa9d9601e1d1260e50db55`
