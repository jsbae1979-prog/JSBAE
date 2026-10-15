# NewsFlow AI — Phase 5B Windows Easy Setup 보고서

확인일: 2026-10-15. 대상: Windows 11 / Python 3.12. Cloud는 개발·테스트 용도입니다.

다운로드: 같은 폴더의 `phase5b_windows_easysetup_report.zip`에 이 보고서, 시작 안내, 사용자 확인표, Cloud/Windows 증거와 실제 MP4를 포함합니다. 검증용 합성 자료이며 사용자 DB·비밀키를 포함하지 않습니다. 무결성 목록은 `phase5b_evidence/sha256.json`입니다.

## 1. 결과 요약

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| Windows 준비 점검·설정 마법사 | PASS | 구현 및 HTTP/브라우저 검사; 기존 run.bat 유지 |
| Cloud 전체 pytest | PASS | 942 passed / 6 skipped / 1 warning / 0 failed |
| Windows 전체 pytest·실제 BAT·Chrome | PASS | 947 passed / 1 skipped / 1 warning / 0 failed; Actions 38693103037 |
| Cloud·Windows 30·45·60초 MP4 | PASS | H.264/AAC, 1080×1920, 실제 Chromium 재생·스트림 타이밍 |
| 한국어 자막 줄바꿈·안전 영역 | PASS | Pillow 글꼴 raster, 줄 폭 검사, 초과 자막 거부·실제 영상 제작 |
| 한국어 음성·사람의 영상 품질 | NOT VERIFIED | 아래 자동 검사와 분리 |
| 실제 OAuth·SNS 실행 | PASS | 실제 호출 0건, 기존 차단 회귀 유지 |
| 사용자 Windows 11 PC 운영·쉬운 설치의 사용자 평가 | NOT VERIFIED | Actions runner는 사용자 PC/사용성 평가가 아님 |

## 2. Windows 설치 구조

`START_HERE.html → setup.bat → run.bat → 처음 설정하기` 순서입니다. 시작 안내 HTML은 별도 서버 없이 브라우저에서 읽을 수 있습니다. Python 3.12 공식 다운로드, FFmpeg 공식 다운로드 안내, 사용자 PATH 설정, 한국어 글꼴·음성 준비, 실행·종료·백업 절차를 제공합니다.

- 기존 `run.bat` 파일은 변경하지 않았습니다. 기존 포트 8765와 loopback 바인딩을 유지합니다.
- 새 `setup.bat`는 Python 3.12를 확인하고 기존 Windows launcher의 `--setup-only` 경로를 사용합니다. 전용 가상환경/패키지 점검 후 `newsflow.easy_setup`을 실행합니다. 필수 점검 실패는 비정상 종료 코드이며 정상 실행으로 표시하지 않습니다.
- CLI는 기존 migration 잠금을 잡고 SQLite 스키마를 초기화합니다. 실행 중 앱과의 충돌은 거부하며 기존 DB·토큰·영상·설정을 삭제하지 않습니다. 기존 `data/newsflow.db`가 발견되면 기존 안전 이전 절차를 안내합니다.
- 준비 점검은 Python, FFmpeg/ffprobe 버전, 한국어 글꼴 raster, 한글·공백 파일 생성/읽기/정리, 롤백하는 DB 쓰기 확인, 600MB 여유 공간, 선택적 한국어 SAPI 음성을 확인합니다. 외부 요청을 하지 않습니다.
- 사용자 데이터는 `%LOCALAPPDATA%\NewsFlowAI`, 출력은 `outputs\videos`, 실행 로그는 `logs`를 유지합니다. 저장 위치 변경이나 기존 파일 이동을 마법사에서 수행하지 않습니다.
- 프로그램 종료는 실행 창의 Ctrl+C를 안내합니다. 브라우저 탭 종료는 서버 종료가 아닙니다. 포트 충돌 시 기존 실행을 확인하도록 안내하며 자동 포트 변경은 없습니다.

**제약:** Python과 FFmpeg의 자동 설치기는 아닙니다. 아직 신규 사용자가 Python 설치와 FFmpeg PATH 등록을 해야 합니다. 무설치·완전 원클릭 설치로 보고하지 않습니다. 단계별 시작 안내와 진단으로 준비 과정을 줄였습니다.

### Python 별도 설치 없는 배포 가능성

Python 3.12와 PyInstaller `onedir` 패키지에 FastAPI/Jinja/static/Alembic/PowerShell 파일을 포함하는 Windows x64 배포가 가능합니다. 이번 단계에서는 설계만 했으며 빌드·서명·EXE Installer는 **NOT VERIFIED / 미구현**입니다. 깨끗한 Windows 11에서 DLL·DPAPI·SAPI 검증, 코드 서명 및 SmartScreen, FFmpeg 빌드별 재배포 라이선스, 안전한 업데이트/롤백·데이터 보존 검증이 선행되어야 합니다. 임의 EXE 다운로드나 보안 검증 우회는 구현하지 않았습니다.

## 3. 초기 설정 마법사

1. 시작 안내: 체험 뉴스와 로컬 검토영상의 의미 설명.
2. 뉴스 수집 방식: 체험 뉴스 또는 등록 출처. 실제 출처를 자동 활성화하지 않음.
3. AI 기능: 외부 API 없는 기본 대본만 설정. 외부 AI 동의와 키는 기존 AI Studio의 별도 경계 유지.
4. 영상 제작: 30/45/60초, YouTube Shorts/Instagram Reels 목적지. 실제 연결/게시 없음.
5. 음성과 자막: 설치된 한국어 SAPI 음성 또는 무음, 자막 40/48/56px와 안전 영역 위치.
6. 저장 위치: 데이터/영상 경로 확인 및 백업 안내.
7. 완료·테스트: 필수 준비 점검 통과 후 적용. 별도 클릭으로 합성 뉴스의 30초 체험 제작.

기존 설치의 뉴스 방식·영상 길이·목적지를 첫 진입 기본값으로 불러옵니다. 입력 중 상태는 기존 `AppSetting`에 보존하며 완료 전에는 기존 제작 기본값을 변경하지 않습니다. 최종 적용은 SQLite 트랜잭션 하나로 처리합니다. revision 확인으로 오래된 창/중복 제출을 거부하고 이전 단계 건너뛰기를 차단합니다. 별도 테이블이나 migration이 필요하지 않아 `0001`~`0008`을 변경하지 않았습니다.

새 검토영상의 렌더 시작 시 음성·자막 설정을 읽고 기존 AudioTrack/SubtitleTrack에 기록합니다. 이미 제작한 영상은 바꾸지 않습니다. 설치되지 않은 음성을 몰래 다른 음성으로 대체하지 않으며, 장면보다 긴 음성은 실패로 처리합니다.

## 4. GUI 개선과 화면 증거

주 메뉴를 **홈 / 자동 제작 / 뉴스 / 제작 영상 / 게시 대기함 / 설정**으로 구성했습니다. 고급 Dashboard·AI/Video/Publishing Studio와 출처 설정은 유지했습니다. 기존 작업 진행률·취소·복구 동선에 준비 점검 링크를 추가했습니다.

새 제작 영상 보관함은 실제 파일이 있는 영상의 미리보기/저장/대본 편집/영상 상세와 실행 이력 진입을 제공합니다. 준비되지 않은 영상은 완료로 표시하지 않습니다.

스크린샷: `phase5b_evidence/easysetup/` 안의 시작·음성/자막·저장 위치·설정 완료·오류·30/45/60초 완료·영상 보관함·320px/200% 확대 화면. 최종 실행 산출물만 첨부합니다. Cloud Chromium 실동선과 Windows Chrome 실동선은 각각의 증거로 구분합니다.

| 화면 | 실제 Cloud 자료 |
| --- | --- |
| 홈·제작 진행·게시 대기함 | [홈](phase5b_evidence/dashboard.png), [진행](phase5b_evidence/progress.png), [대기함](phase5b_evidence/queue.png) |
| 설정 시작·음성·저장 위치 | [시작](phase5b_evidence/easysetup/wizard-welcome.png), [음성/자막](phase5b_evidence/easysetup/wizard-voice-subtitle.png), [저장 위치](phase5b_evidence/easysetup/wizard-storage.png) |
| 설정 오류·완료 | [도구 누락 안내](phase5b_evidence/easysetup/setup-error.png), [완료](phase5b_evidence/easysetup/wizard-completed.png) |
| 제작 영상 보관함 | [영상 3개](phase5b_evidence/easysetup/video-library.png) |
| 화면 대응 | [320px](phase5b_evidence/easysetup/layout-320.png), [CSS 200%](phase5b_evidence/easysetup/layout-1440.png) |
| 실제 MP4 | [30초](phase5b_evidence/easysetup/setup-30s.mp4), [45초](phase5b_evidence/easysetup/setup-45s.mp4), [60초](phase5b_evidence/easysetup/setup-60s.mp4) |

Windows 실화면: [마법사](phase5b_evidence/windows/easysetup/wizard-completed.png), [오류 안내](phase5b_evidence/windows/easysetup/setup-error.png), [영상 보관함](phase5b_evidence/windows/easysetup/video-library.png), [320px](phase5b_evidence/windows/easysetup/layout-320.png). Windows 생성 MP4: [30초](phase5b_evidence/windows/easysetup/setup-30s.mp4), [45초](phase5b_evidence/windows/easysetup/setup-45s.mp4), [60초](phase5b_evidence/windows/easysetup/setup-60s.mp4).

## 5. 한국어 영상 검증

Cloud와 Windows 실제 제작은 30·45·60초 각각 H.264/AAC, 1080×1920 세로 영상이며 실제 브라우저 재생 시간을 확인합니다. 자막 기본값 변경(56px, y=1280)이 DB에 반영되고, 자막 cue가 0부터 전체 길이까지 끊김 없이 연결되는지 검사합니다. 영상/오디오 스트림 시작 시각 차이 <0.1초, 길이 차이 <0.15초를 검사합니다.

자막 줄바꿈은 글꼴 너비 900px 안에 들어가는지, 원래 한국어 문자열이 보존되는지 확인합니다. 지나치게 긴 자막은 잘라서 성공 처리하지 않고 거부합니다. 실제 영상 및 화면 자료는 첨부 MP4·PNG에서 확인할 수 있습니다.

**음성 구분:** 전체 길이 영상은 무음 검토영상입니다. 스트림 타이밍 PASS는 실제 한국어 발음·말과 자막의 의미적 싱크 PASS가 아닙니다. Windows 검사는 설치 음성의 Culture를 조회하고 한국어 음성이 있는 경우에만 실제 한국어 WAV와 비무음 파형을 검사합니다. 음성이 없으면 NOT VERIFIED로 기록하며 영어 음성을 한국어로 간주하지 않습니다. 사람의 청취·시청 평가는 수행하지 않았습니다.

## 6. Cloud 및 Windows 회귀

```text
python -m pytest -q -rs --junitxml=<evidence>/pytest.xml
python -m ruff check src tests tools
python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output <evidence>/legacy
python tools/ci_autopilot_validation.py --mode cloud --browser-executable /usr/bin/chromium --output <evidence>/autopilot
python tools/ci_easysetup_validation.py --mode cloud --browser-executable /usr/bin/chromium --output <evidence>/easysetup
```

최종 검증 HEAD: `ccd08967bba4d4fd4491c26fe4ae1959ae8f6a39`. 애플리케이션 코드는 `f88ede2`와 동일하고, Windows 검증 도구의 탐색 동기화·SQLite 정리만 보완했습니다.

최종 HEAD에서 전체 pytest와 새 설정 브라우저 검사를 다시 실행했습니다. 기존 Studio/Autopilot Cloud 증거는 동일 애플리케이션 코드에서 실행한 결과이며, 이후 변경은 새 Windows 검증 도구의 동기화·정리에 한정됩니다. Windows는 최종 HEAD에서 모든 단계를 다시 실행했습니다.

Cloud 전체 회귀는 **942 passed / 6 skipped / 1 warning / 0 failed**, 총 948개입니다. Skip은 실제 RSS opt-in 1개와 native Windows 검사 5개입니다. 기존 Starlette/httpx 폐기 예정 warning 1개를 숨기지 않았습니다. Ruff도 PASS입니다. 기존 Studio·Autopilot 및 새 마법사의 실제 서버/Chromium 동선은 PASS입니다. [Cloud 요약](phase5b_evidence/cloud-summary.json), [pytest](phase5b_evidence/cloud-pytest.log), [JUnit](phase5b_evidence/cloud-pytest.xml), [기존 GUI](phase5b_evidence/cloud-legacy-result.json), [Autopilot](phase5b_evidence/cloud-autopilot-result.json), [마법사/MP4](phase5b_evidence/easysetup/easysetup-result.json).

**Windows 최종 결과: PASS — [Actions run 38693103037](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38693103037), 검증 코드 `ccd08967bba4d4fd4491c26fe4ae1959ae8f6a39`.** 전체 pytest는 **947 passed / 1 skipped / 1 warning / 0 failed**입니다. Skip은 실제 RSS opt-in 1개입니다. 기존 Starlette/httpx 경고 1개가 있으며 Node.js 20 사용 중단 경고나 새로운 경고는 전체 job log에서 발견하지 않았습니다. 모든 workflow 단계가 성공했습니다. 실제 `setup.bat` 2회·`run.bat` 기동/종료·Chrome POST·DPAPI·운영 vault 합성 암호화·기존 Autopilot·마법사 오류 후 재시작·영상 3개 생성/재생·뉴스 8개와 게시 초안 3개 보존을 확인했습니다.

[Windows 요약](phase5b_evidence/windows/summary.json), [실행 SHA와 단계](phase5b_evidence/windows/actions-run.json), [pytest](phase5b_evidence/windows/pytest.xml), [경고/결과](phase5b_evidence/windows/pytest-summary.log), [BAT/기존 GUI](phase5b_evidence/windows/result.json), [DPAPI](phase5b_evidence/windows/credential-vault.json), [운영 vault](phase5b_evidence/windows/production-credential-vault.json), [Autopilot](phase5b_evidence/windows/autopilot-result.json), [마법사/MP4/보존](phase5b_evidence/windows/easysetup/easysetup-result.json).

Windows runner의 **한국어 SAPI 음성은 0개**였습니다. 설치된 다른 SAPI 음성의 실제 WAV/MP4 생성은 기존 검사에서 통과했지만, 한국어 음성 생성과 발음·자막 의미 싱크는 **NOT VERIFIED**입니다. 새 Windows workflow만 추가했으며 기존 8개 workflow는 변경하지 않았습니다. Windows에는 기존 전체 pytest, native DPAPI/운영 vault, 실제 BAT·Chrome·Autopilot을 모두 유지하고 setup.bat 2회 실행, 마법사/실제 글꼴 누락 오류/재시작 복구, 30/45/60초 영상을 추가했습니다.

진행 중 발견한 실패: 새 DB 보존 테스트 fixture의 source_id 누락은 fixture를 올바르게 연결해 수정했습니다. 브라우저 자동화의 문자열 predicate가 CSP에 거부되어 함수 predicate로 수정했습니다. CSP에 unsafe-eval을 추가하거나 실패 검사를 제거하지 않았습니다. 앞선 Windows run 두 건은 기존 기본값 보존·읽기 전용 DB 판별 보완 커밋으로 대체되어 취소되었으며 성공 근거로 사용하지 않습니다.

실패한 Windows run `38671327268`은 전체 pytest 947 passed / 1 skipped까지 통과했지만, 새 검증 도구에서 완료 화면 자동 갱신과 `page.goto`가 충돌하고 미닫힌 SQLite 연결이 임시 DB 정리를 막아 **FAIL**했습니다. 테스트는 완료 DOM 상태를 기다리도록 고쳤으며 SQLite 연결은 `closing()`으로 닫습니다. 성공 표시는 프로세스·파일 정리까지 끝난 뒤 기록하도록 했습니다. 이 run을 Windows 완료 근거로 사용하지 않습니다. 애플리케이션 보안과 검사 assertion을 완화하지 않았습니다.

이어진 Windows run `38692314941`도 전체 회귀와 기존 동선은 통과했지만, 새 마법사 테스트가 고정 250ms 대기 후 이전 단계 DOM을 읽어 **FAIL**했습니다. 최종 검증 도구는 각 성공 POST의 Origin·303을 확인하고 실제 페이지 이동 완료 및 단계 값을 기다립니다. 검사를 생략하거나 임의 sleep을 늘린 방식이 아닙니다.

## 7. 기능·보안 보존

- 기존 920개 테스트를 유지하고 설정·오류·보존·음성·자막 관련 28개를 추가했습니다.
- CSRF/Origin/Host/CSP/SSRF/TLS·DPAPI 및 실제 OAuth/SNS 차단을 유지합니다.
- 설정 마법사는 API 키/토큰 입력을 받지 않습니다. 원문 도구 오류·환경변수·민감정보를 로그/HTML에 그대로 표시하지 않습니다.
- 외부 실행은 기존 인수 배열과 제한시간을 사용합니다. shell=True, 임의 다운로드, 프록시/TLS 변경은 없습니다.
- OAuth 실제 로그인·토큰 발급/저장·SNS 게시/업로드는 0건입니다. 합성 실행 DB·안전 카운터·브라우저 외부 요청 0·기존 차단 테스트를 함께 확인합니다. OS 전체 패킷 감시를 했다고 주장하지 않습니다.
- 작업 단일 실행·취소·중단 복구와 게시 전 사람의 검토 경계는 보존합니다. 스케줄러는 구현하지 않았습니다.

## 8. 미구현·미검증 사항

- 사용자 Windows 11 PC 실제 설치·수동 Ctrl+C·초보자 사용성 평가: NOT VERIFIED.
- Windows OS 디스플레이 배율과 브라우저 메뉴의 네이티브 확대: NOT VERIFIED. 자동 레이아웃 검사는 320px와 CSS zoom 200%입니다.
- 한국어 음성 품질과 사람이 보는 30/45/60초 완성 영상 품질: NOT VERIFIED.
- Python 없는 EXE/설치본, 자동 FFmpeg 설치: 미구현. 설치 안내와 점검만 제공.
- 실제 RSS·외부 AI API·OAuth·SNS: NOT VERIFIED, 이번 단계에서 실행하지 않음.

[사용자 Windows 11 확인표](../windows_user_checklist.md)를 제공합니다. 실제 사용자 검사 결과가 나올 때까지 자동화 성공을 실사용 승인으로 대체하지 않습니다.

## 9. Git 및 다음 단계

[변경 파일](phase5b_evidence/changed-files.txt) · [기존 브랜치/PR 보존 확인](phase5b_evidence/git-preservation.json).


- Base: `feat/newsflow-phase5a` / `d0ec31445ee32893378e6194d7bd16cda1b545d4`.
- Branch: `feat/newsflow-phase5b`.
- 구현: `5585030c3b83c9affa6dde7f3c26367d3347ca65`; 기존 기본값 보존: `634ea2fdd42322ac1d1e7d4503d86e4b82cf29f1`; 읽기 전용 DB 확인 및 최종 검증 코드: `f88ede2d1dc54040addf898c8f86cd4af48999c0`.
- Windows 검증 도구 보완 및 최종 검증 HEAD: `ccd08967bba4d4fd4491c26fe4ae1959ae8f6a39`.
- [Draft PR #9](https://github.com/jsbae1979-prog/JSBAE/pull/9), base `feat/newsflow-phase5a`. 기존 PR #1~#8과 main은 변경/병합하지 않았습니다.
- 이후 보고서·증거 커밋은 실행 코드/테스트와 구분합니다.

다음 승인 후보는 사용자 PC의 초기 설치·한국어 음성 품질 검증과 서명된 Windows 배포본의 별도 개발입니다. **스케줄러·실계정 OAuth·SNS 자동 게시·main 병합은 시작하지 않습니다.** Phase 5B 보고서 제출 후 중단합니다.
