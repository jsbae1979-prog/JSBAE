# NewsFlow AI 전체 로컬 검증 — 2026-11-03

## 대상과 범위

- 브랜치: `codex/newsflow-character-shorts-automation-20261030`
- 검사 기준 HEAD: `dc843b3a6351849f47339cb1f2353243a660eb8c`
- 기존 미커밋 파일 3개를 보존한 작업 폴더를 검사했다. 해당 파일 목록과 보존 결과는 `validation.json`에 기록했다. HEAD 단독의 깨끗한 체크아웃 검사로 표시하지 않는다.
- Windows 11 / Python 3.14.7 AMD64 / pytest 8.4.2 / Node 24.19.0.
- 개발용 임시 프로필, 모의 공급사, 로컬 FFmpeg를 사용했다. 운영 앱 시작·종료·배포, 실제 수집·유료 생성·OAuth 교환·업로드·SNS 게시는 수행하지 않았다.

## 결과

| 검사 | 결과 |
|---|---|
| 전체 Python `tests` | 7221 PASS / 0 FAIL / 0 ERROR / 14 SKIP |
| 글꼴 미지정으로 제외된 10개만 재검증 | 10 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| frontend 계약 검사 | 48 PASS / 0 FAIL / 0 SKIP |
| 추가 frontend 검사 | 18 PASS / 0 FAIL / 0 SKIP |
| TypeScript 검사 / React 빌드 | 종료 코드 0 / 0 |
| `tools/studio_v3/tests` | 58 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| `tools/feed_top3/tests` | 25 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| 합성 앱 HTTP smoke | 26 PASS / 0 FAIL / 0 ERROR |

전체 Python 실행 시간: 3141.93초. 프런트엔드 두 묶음은 서로 다른 파일이며 총 66건이다. 도구 테스트와 HTTP 검사는 별도 결과로 기록하며 전체 Python 수치에 더해 단일 회귀 수치로 표시하지 않는다.

같은 검사 ID를 중복 계산하지 않고 글꼴 후속 결과를 반영하면 Python 최종 확인 범위는 **7,231 PASS / 0 FAIL / 0 ERROR / 4 SKIP**이다. 남은 4건은 현재 사용자에게 허용되지 않은 심볼릭 링크 검사, Windows 실제 DPAPI 환경에서 적용되지 않는 대체 암호화 검사, 별도 승인 없는 유료 AI·실제 RSS opt-in 검사다. 운영 보안 설정이나 외부 호출 권한을 바꿔 실행하지 않았다.

HTTP smoke는 React 경로 12개, 읽기 모델 10개, JS·CSS·한글 폰트 3개, DB 불변 1개를 확인했다. 실제 브라우저의 시각 검증이나 운영 앱 검증이 아니다.

## 과거 실패와 비교

이전 중간 작업본의 전체 검사(`auto-full.xml`)는 6,975 PASS / 113 FAIL / 24 ERROR / 50 SKIP이었다. 이번에는 기존 FFmpeg·FFprobe 경로, tzdata 2026.5, 승인된 GUI 비교 기준을 연결했다. 테스트를 통과시키기 위한 상태 강제나 assertion 삭제는 하지 않았다.

기존 실패·오류 ID 137개 중 이번 PASS 135개, 여전히 FAIL/ERROR 0개, 동일 ID 미발견 2개다. 두 실행의 코드 버전은 다르므로 모든 차이를 환경 개선만의 효과로 단정하지 않는다.

동일 ID가 없는 2건은 후속 검사를 확인했다. 피드 성과 직접 입력을 포함하던 브라우저 검사는 해당 기능 정리 후 `test_free_title_caption_edit_preserves_versions_without_performance_requests`로 바뀌었으며 PASS다. 인증기간 검사는 `AUTH_EXPIRED` 안내문 변경으로 parameter ID가 달라졌으며 해당 조건도 PASS다. 이전 UI 요구를 다시 복원하거나 검사 조건을 무조건 통과하도록 바꾸지 않았다.

## 실행 명령

```text
python -m pytest -q -rs --tb=short -o junit_family=legacy -o faulthandler_timeout=120 -p no:cacheprovider --basetemp=<temporary/full> --junitxml=<evidence/full-python.xml> tests
node --test tests/*.test.mjs
node --test frontend/tests/*.test.cjs frontend/tests/quote-settings-dirty.mjs
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build --configLoader runner
python -m pytest -q -rs --confcutdir tools/studio_v3/tests tools/studio_v3/tests
python -m pytest -q -rs --confcutdir tools/feed_top3/tests tools/feed_top3/tests
```

Node 실행은 기존 설치 경로를 사용했다. 임시 TEMP·APPDATA·LOCALAPPDATA·데이터 경로를 사용하고 실제 공급사 자격정보 환경변수를 제거했다. 라이브 검사 옵션은 끄고, 도구 검사에는 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`을 적용했다. 원문 로그·JUnit은 로컬 검증 폴더에 보존하고 공개 가능한 집계·해시만 커밋한다.

## 데이터와 프로그램 보존

운영 프로그램 파일 3,089개, 사용자 프로필 비DB 파일 416개, DB 49개 테이블(기사 394건), 운영 실행 설정, 원본·백업 A/B를 읽기 전용으로 대조했다. 전체 검사 도중 확보한 비교 기준과 종료 후 상태를 대조했으며, 첫 검사 시작 전 스냅샷으로 과장하지 않는다. 불변 여부는 `validation.json`의 `preservation`에 기록했다. 이전 대화의 169건은 과거 기준이며 현재 기사 수를 그 값으로 되돌리지 않았다.

## 경고와 미검증

- React 빌드의 큰 JS 청크 경고와 lucide 지시문 경고는 남아 있다. 한글 폰트의 빌드 시 경로 경고가 있었으나 실제 빌드 파일과 임시 앱 HTTP 200을 확인했다.
- Python 전체 검사에는 15개 경고가 있다: TestClient/httpx의 향후 호환성 안내와 `gui/video_routes.py:260–261`의 NULL ID 조회 경고다. 현재 실패는 없으나 별도 유지보수 대상이다. 이번 검증에서 관련 없는 제품 변경을 추가하지 않았다.
- Python 3.12 전체 회귀는 이번에 실행하지 않았다. 기존 CI와 이번 로컬 결과를 혼합하지 않는다.
- CI 전용 전체 앱 폼 통합 검사는 로컬에서 실행하지 않았다. 해당 검사의 CI 환경 제한을 우회하지 않았다.
- 실제 계정 인증, 토큰 갱신, 외부 파일 전달, 유료 생성·청구, SNS 게시, 사용자 Chrome 시각 검토는 미검증이다.
- 이번 검증 결과만으로 실서비스 연결·외부 배포가 완료됐다고 판정하지 않는다.

## 최종 판정

**로컬 무료 전체 검증 ACCEPTED. 실제 계정·업로드·게시 운영 검증은 CONDITIONAL.** 제품 코드와 운영 설치본은 변경하지 않았으며, 검증 보고서와 비민감 집계만 개발 브랜치에 보존한다.
