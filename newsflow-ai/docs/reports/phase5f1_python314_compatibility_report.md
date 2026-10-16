# Phase 5F.1 — Python 3.14 호환성 보고서

기준: `feat/newsflow-phase5f` / `37597fdd25cd342326df626bd2e1390c62f2c06c`.
브랜치: `feat/newsflow-phase5f1`. 최종 판정은 사용자 검토 대기.

## 구현한 기능

- Python **3.12 및 3.14만 지원**. 3.13 제외, Ruff `py312` 문법 기준 유지.
- 기존 지원 `.venv`를 보존·우선 사용. 없으면 3.14 → 3.12 순서 선택. 지원하지 않는 기존 환경은 삭제·대체하지 않고 중단.
- 실행 검사·준비 점검·설치 지문·운영 점검에 공통 버전 정책 적용. 버전별 지문을 분리하며 의존성 변경 시 갱신.
- Windows Ctrl+Break를 Ctrl+C와 같이 처리해 Uvicorn 신호 재전달 후에도 정리·종료 로그를 보존.
- Python 3.14의 robots 규칙 변경에 대응해 CPython v3.12.10 공식 파서를 PSF 라이선스와 함께 고정. 기존 첫 일치·접두사·사용자 에이전트 정책 유지.
- 기존 의존성 고정과 migration 0001–0012 변경 없음. CI는 각 버전별 가상환경으로 격리.

## 변경 파일

- `pyproject.toml`, `setup.bat`, `run.bat`, `tools/windows_launcher.py`.
- `src/newsflow/python_policy.py`, `easy_setup.py`, `main.py`, `operations/{autorun,startup}.py`.
- `news/rss_adapter.py`, `news/vendor/*`, `tools/ci_feed_review.py`.
- 관련 정책·Windows·마법사·운영·글꼴 테스트, `tools/ci_fixture_server.py`, `tools/ci_validation.py`, `tools/ci_python_compatibility_validation.py`.
- `.github/workflows/newsflow-phase5f1-windows.yml`, README, START_HERE, Windows 안내 및 AGENTS의 Python 지원 버전 문구.

## 핵심 테스트 결과

- Python **3.14.7** 전용 `.venv`: 생성·고정 의존성·네이티브 wheel 설치 성공, `pip check` 통과. 기존 Python 3.14 설치 변경 없음, 3.12 MSI 재시도 없음.
- 정책·런처·마법사·운영 핵심 91개, 실패 영역 재검증 36개 통과.
- 실제 `setup.bat` / `run.bat`, 7단계 마법사, Offline 대본, 영상 보관함·게시 대기함·운영 GUI 통과.
- 합성 현재 사용자 DPAPI·운영 암호화·재시작·변조 차단 통과. 기존 보안 경로 검사 유지.
- Higgsfield Fake Provider의 실제 Chrome/FFmpeg·중복 제출 방지·재시작 복구·최종 MP4 통과. 실제 공급사 호출 없음.

## 전체 회귀 결과

- 로컬 Windows 11 / Python 3.14.7: **2340 passed, 4 skipped**, Ruff·pip check 통과.
- 4개 제외는 기존 조건: 일반 사용자 symlink 불가, Windows 실 DPAPI 환경용 분기, 유료 AI opt-in, 실제 RSS opt-in. 임의 skip 추가 없음.
- Cloud Python 3.12.15 / 3.14.8: 각각 **2336 passed, 8 skipped**, Ruff·pip check 통과. Windows 3.12.10 / 3.14.8: 각각 **2341 passed, 3 skipped**, SAPI·DPAPI·BAT·Chrome·30/45/60초 영상·예약·Fake Provider·문서 점검 전체 단계 통과. 최종 Actions 4개 작업 모두 success. [Actions](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38866269727).
- 발견·수정: 표준 robotparser 동작 차이, Windows 자식 프로세스 종료 관측, 글꼴 폭 고정 테스트, CI 러너 기본 pipx 충돌 및 Cloud Playwright 누락. 의존성 버전 변경 없이 해결.
- Starlette/httpx TestClient 사용 중단 예고 경고 1개는 기존 기능 정상인 비차단 경고로 유지.

## 실제 Windows 11 실행 결과

- 설치된 Google Chrome에서 실제 프레임 디코딩·재생 시간 진행 확인.
- MP4: **1080×1920, H.264/AAC, 30 fps, 30.021354초**, 무음 체험 영상.
- Ctrl+Break 정상 정리 후 `server_stop` 로그 확인. 재시작 후 SQLite 무결성 `ok`, migration `0012`, 영상 SHA256 유지.
- 영상 SHA256: `aebdb7e8c32d67ad527e61b25f46e07e0262d5b2a347536029eba1901c9c4e00`.
- 예약 엔진·중복 방지·재시작·놓친 예약 몰아 실행 금지: 실제 Chrome/FFmpeg와 테스트 주입 시계로 통과. 운영 시계는 변경하지 않음.
- 기존 데이터 없음 확인 후 최초 생성. 생성한 SQLite·설정·영상 보존. 유료 AI 사용·OAuth·SNS 작업 기록 모두 0건. Task Scheduler 실제 등록 없음.

## 미해결 문제 / 미검증 사항

- 로컬 SAPI는 기존 PowerShell 정책에 의해 차단됨. 정책 변경 없이 무음 모드 검증. 사람 청취·편집 품질은 NOT VERIFIED.
- Codex에서 실행한 자식 프로세스의 논리적 `%LOCALAPPDATA%`는 Codex 패키지 LocalCache로 리디렉션됨. 생성 데이터는 `C:\Users\ching\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\NewsFlowAI`에 보존되며, 직접 실행한 일반 사용자 셸의 데이터 폴더와 구분해야 함. FFmpeg도 같은 `LocalCache\Local\NewsFlowAI-tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin` 아래에 있음. 직접 실행 시 기존 자료를 사용하려면 해당 물리 경로를 `NEWSFLOW_DATA_DIR`, `NEWSFLOW_FFMPEG`, `NEWSFLOW_FFPROBE` 세션 변수에 지정할 수 있음. 이동·삭제는 수행하지 않음.
- 운영 vault가 리디렉션 경로를 거부한 것은 보안 검사 정상 동작. 경로 검사를 완화하지 않고 리디렉션 없는 작업 폴더에서 동일 합성 네이티브 DPAPI 검증 통과.
- 직접 실행한 비패키지 사용자 PowerShell 및 서로 다른 Windows 사용자 DPAPI 격리는 로컬 NOT VERIFIED; 후자는 disposable Windows CI의 두 버전에서 실제 합성 DPAPI 격리·정리 통과.
- 실제 유료 API·OAuth/SNS, OS 자동 시작 등록, Phase 5G는 수행하지 않음.

## GitHub 브랜치·SHA·PR

- [Draft PR #16](https://github.com/jsbae1979-prog/JSBAE/pull/16), base `feat/newsflow-phase5f`.
- 최종 검증 코드 SHA: `c35629b89dfe3cf06c4b2153268ffa6c976b1e8a`.
- 보고서·개발 안내 전용 후속 커밋은 제품·테스트·CI 코드를 변경하지 않음. 최종 체크아웃 SHA는 `git rev-parse HEAD`로 확인.
- main 및 기존 PR #1–#15 변경·병합, force push·기존 커밋 재작성 없음.
