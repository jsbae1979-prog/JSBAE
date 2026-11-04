# 사진 피드 편집 — 남은 회귀 실패 후속 정리

- 날짜: 2026-11-01
- 기준: `fa3e2be05aa1cb4e573a31d0e0f591c8a4881a01`
- 브랜치: `codex/newsflow-photo-feed-editor-20261101`
- 결과: 이전 전체 실행에서 남았던 **15개 실패 항목 모두 후속 PASS**. 처음 재검사 13 PASS / 2 FAIL, 원인 보완 후 해당 2개 PASS. 서로 다른 15개 기준이며 반복 검사를 합산하지 않았다.
- 제품 코드·운영 설치·실제 데이터·키·미디어·백업 변경 없음. 유료 호출·수집·SNS·운영 재시작 없음.

## 수정한 테스트 6개

| 파일 | 확인한 현재 동작과 보완 |
|---|---|
| `tests/test_card_response_diagnostics.py` | 현행 카드 프롬프트 버전 v3 확인. 기존 성공 결과 재사용, 미확정 기록 보존 및 중복 호출 방지 검사는 유지 |
| `tests/test_character_automation_browser.py` | 저장된 스토리는 재생성 확인 창을 열 수 있음. 확인 전에 추가 호출이 없고 취소 후에도 기존 1회만 유지되는지 검사 |
| `tests/test_creation_models.py` | 이미 구현된 참조 이미지 생성을 Fake로 검사. 동의·검토 누락 시 전송 없음, 정확한 로컬 이미지 전달, 원본 보존, 동일 결과 재사용 검사 |
| `tests/test_elevenlabs_saved_voices.py` | 현행 목록 범위 오류 문구 확인. 이전 페이지 토큰 혼용 차단, 호출 없음, 캐시 보존 검사는 유지 |
| `tests/test_quote_rss_settings_browser.py` | 통합 ‘뉴스 수집 방식 → 등록 RSS → 수집 시작’으로 확인 창을 열음. 실제 수집은 실행하지 않음 |
| `tests/test_usability_browser.py` | 문서·스타일 로딩 후 미리보기 비율을 측정. CSS 9:16과 기존 실제 크기·경계 검사를 모두 유지 |

## 검증 환경 누락 해결

운영 환경 설치나 전역 설정 변경 없이 기존 개발 검증 자료만 사용했다.

- 시간대: 기존 격리 `tzdata 2026.5 / IANA 2026e`를 테스트 프로세스의 `PYTHONPATH`에 연결. 해당 7개 검사 PASS.
- 과거 GUI: 기존 격리 `baseline-src/newsflow`를 `NEWSFLOW_BASELINE_GUI_SOURCE`로 연결. 과거 소스 대신 현재 소스를 끼워 넣지 않았다.
- 복구 기준: `STEP13_ROOT`에 기존 격리 자료를 연결. 기준 `0a59bfb41eec6b243e4470f67cd53c1e7cd07e52`의 5개 코드 파일을 저장소의 `baseline-code-manifest-safe.json`과 SHA-256 대조해 모두 일치 확인.
- FFmpeg: 기존 비공개 검증 설치 후보의 `tools/ffmpeg.exe`·`ffprobe.exe`, 저장소 NotoSansKR 글꼴을 테스트 프로세스에 명시. 현재 운영 설치의 실행파일·프로필을 사용하지 않았다.
- 실시간 RSS와 유료 AI opt-in은 꺼 둠. 외부 요청은 Fake이며 브라우저는 격리 localhost에만 접근.

재현할 때는 승인된 위 자료 경로를 테스트 프로세스 환경에 지정한 뒤 `python -m pytest -q -rs`에 [결과 JSON](regression-followup.json)의 테스트 목록을 전달한다. 자료 누락을 테스트 통과나 skip으로 감추지 않는다.

## 판정과 범위

**후속 실패 항목 정리 완료. 운영 미반영.**

직전 전체 실행의 19개 실패 중 사진 피드 관련 4개는 이미 최종 코드에서 통과했고, 나머지 15개가 이번에 통과했다. 전체 6천여 개를 이번에 다시 실행하지 않았으므로 새로운 ‘전체 회귀 PASS’로 표시하지 않는다. 기존 사진 피드 집중 100 PASS, studio_v3 58 PASS, 최종 관련 22 PASS는 재사용한다.

경고(Starlette 사용 중단 예고, 레거시 HTML 합성 자료의 SQLAlchemy NULL 조회, JUnit record_property 형식)는 실패와 구분해 유지한다. 관련 없는 제품 코드나 기존 로컬 변경은 고치지 않았다. 실제 운영 적용과 실제 공급사 생성 품질 검증은 이번 작업에서 수행하지 않았다.
