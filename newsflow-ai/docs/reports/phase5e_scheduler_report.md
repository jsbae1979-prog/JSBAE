# Phase 5E — 예약 자동 제작 및 운영 자동화

최종 보고: 2026-10-16 12:06 KST. **Phase 5E 구현·Cloud/Windows 회귀·실제 브라우저 검증 완료**. 실제 유료 AI·OAuth·SNS 실행과 OS 작업 등록은 0건, 실제 과금은 0입니다. 추가 개발과 main 병합은 하지 않습니다.

검증 코드 SHA: `cc295ac57b86c848d702e71ff40f108ea35a3af7`. [Draft PR #14](https://github.com/jsbae1979-prog/JSBAE/pull/14), base `feat/newsflow-phase5d1`, head `feat/newsflow-phase5e`. [Windows Actions](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38842249544).

## 기준 및 구현

- Base `feat/newsflow-phase5d1`, `2b4657e6a0fe484df134e827ce303c3e9fb14200`; 작업 전 clean, 원격 기준 SHA 일치 확인.
- 신규 `feat/newsflow-phase5e`. 기존 PR #1–#13 및 main을 변경·병합하지 않습니다.
- 예약/실행별 UUID, 일별·요일별·단발 KST 예약, 기본 일시 중지, 명시적 켜기, CAS 수정/중지/해제, 다음 미래 시각 및 실행 이력.
- `Scheduler` → 기존 `AutopilotCoordinator` → 기존 수집·intelligence·video/TTS/FFmpeg·검증·게시 초안 서비스. 재구현 없이 기존 기사 claim, 단계별 artifacts, 실제 뉴스 script/final review를 유지합니다.
- `production_schedules`와 `scheduled_runs`의 additive **0012**. 기존 0001–0011 변경 없음.
- `scheduler.lock` + 프로세스 lock + SQLite 짧은 BEGIN IMMEDIATE + occurrence unique + deterministic Autopilot request ID. 결과 불명은 자동 재실행·성공 처리하지 않습니다.
- 예약을 놓친 시간이 90초 초과이면 기간 전체를 한 건의 skipped로 기록하고 다음 미래 예약으로 이동. 90초 이내는 한 건만 실행. 앱 종료 중 제작·자동 OS 실행 없음.
- 실패/중단/다른 작업 점유는 직접 안전 재시도만. 취소와 예약 일시 중지는 분리. 이미 만든 영상과 대본을 보존합니다. DB 복사본의 활성 예약은 자동 실행을 막기 위해 일시 중지합니다.
- `/schedules`: 기존 Easy UI에 예약 폼, 안내, 다음 시각, 제작 진행률, 실행 이력과 기존 완료 영상 링크를 추가. 읽기 전용 상태 갱신은 입력/동의 중에는 폼을 교체하지 않습니다.
- 예약은 항상 `ai_mode=offline`, 기본 영상만. 저장된 유료 AI 설정을 상속하지 않고 scheduled context에서도 유료 mode를 거부합니다. OAuth/SNS 실제 호출 차단은 그대로입니다.

자세한 정책 및 공식 Windows Task Scheduler 조사: [예약 사용 안내](../scheduling.md). 현재 사용자·로그온 시·최소 권한으로 기존 앱을 띄우는 연계 가능성을 확인했으나 OS 작업 등록은 **0건**, 실제 OS 연동은 **NOT VERIFIED / 미구현**입니다.

## 검증

| 항목 | 판정 | 근거 |
|---|---|---|
| Cloud 전체 pytest | PASS | **2289 passed / 7 skipped / 1 warning / 0 failed**, 161.45초. 기존 2230개 케이스 유지 + 신규 66개. |
| 예약 단위/통합/GUI HTTP | PASS | KST·DST 독립, 중복/CAS, 단발·장기 누락, grace 경계, 잠금, 시작 commit 전후 crash, 실제 뉴스 review, 안전 retry/cancel, 기사 재제작 차단, DB 복사·0011 업그레이드, CSRF/Origin/XSS |
| Cloud 실제 Chromium | PASS | 예약 저장→명시적 활성화→기존 Autopilot 전체 합성 실행→MP4 재생→로컬 대기함→프로세스 재시작→동일 파일 보존→장기 누락 skip |
| 기존 Easy UI 실제 브라우저 회귀 | PASS | 기존 ci_autopilot_validation: 간편/단계별 제작, 대본 수정·검토·취소, 재시작 산출물, 중복409, 오류 안내, 320px/200% 레이아웃. 실제 서버/FFmpeg/Chromium. |
| 실제 MP4 | PASS | 30.021초, H.264/AAC, 1080×1920, 30fps, 2채널 무음. 브라우저 재생 시간 증가 및 재시작 후 SHA256 동일 확인 |
| 화면 크기 | PASS | 실제 Chromium 1440 desktop, 390 mobile, 1280/CSS zoom200% 가로 넘침 없음. 사용자 편의성 연구를 뜻하지 않음 |
| Windows 전체 회귀/BAT/Chrome/DPAPI | PASS | **2293 passed / 3 skipped / 1 warning / 0 failed**, 350.27초. 실제 BAT·Chrome·예약·DPAPI·기존 기능 검증 전체 SUCCESS. |
| 기존 유료 비용·결과 불명·OAuth·보안 | PASS (Cloud 회귀) | 기존 테스트 삭제/skip 추가 없음. 외부 AI key/live flag를 비운 환경. 예약 합성 시나리오 DB의 유료 사용/예약·OAuth connection·SNS attempt 0 |
| 공식 Task Scheduler 문서 | PASS (문서 열람) | 2026-10-16 KST Microsoft HTTPS GET 200, 위 안내 문서의 세 URL |
| 사용자 Windows 11 PC / 청취·영상 품질 / 실제 RSS·AI | NOT VERIFIED | 이번 합성 흐름으로 실제 서비스나 사용자 PC 품질을 주장하지 않음 |

실행 명령:

```text
NEWSFLOW_FONT_PATH=<검증된 한국어 글꼴> NEWSFLOW_LIVE_TEST=0 NEWSFLOW_AI_LIVE_TEST=0 python -m pytest -q -rs --junitxml=<output>/pytest.xml
python tools/ci_scheduler_validation.py --mode cloud --browser-executable /usr/bin/chromium --output <output>/gui
python tools/ci_docs_link_check.py --output <output>/docs
```

Windows의 3 skip은 기존 실제 AI/RSS opt-in 2개와 실제 DPAPI가 있는 Windows에서 해당하지 않는 fail-closed 조건 1개입니다. 신규 skip은 없습니다.

Cloud의 7 skip: opt-in 실제 AI/RSS 2개 + Windows 전용 5개. 기존 `StarletteDeprecationWarning` 1건은 숨기거나 제거하지 않았습니다. 실제 Windows BAT 검증은 Linux에서 주장하지 않습니다.


## Windows Actions 최종 결과

[실행 38842249544](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38842249544): **SUCCESS**, 검증 SHA `cc295ac57b86c848d702e71ff40f108ea35a3af7`. 실행 시각 **2026-10-16 11:47:43–12:04:31 KST**. `windows-latest`의 실제 OS는 **Windows Server 2025**, Python 3.12.10, FFmpeg 7.1.1, Google Chrome입니다. 사용자 Windows 11 PC 검증으로 대체하지 않습니다.

| 검증 단계 | 판정 | 실제 수행 범위 |
|---|---|---|
| 전체 pytest | PASS | 2296개 중 2293 pass / 3 기존 skip / 0 failed. 기존 Starlette/httpx 경고 1건. |
| BAT·포트·데이터 | PASS | run.bat 시작/종료, 중복 실행·포트 충돌 거부, LOCALAPPDATA 경로, SQLite 저장·재시작·조회. 종료는 taskkill process tree; 사용자 Ctrl+C는 NOT VERIFIED. |
| Windows DPAPI | PASS | 합성 전용 및 production boundary의 **합성 값만** 암호화·격리·회전·복구. 실제 토큰은 사용하지 않음. |
| 기존 GUI/제작 | PASS | 실제 Chrome GET/POST/Origin/CSRF, 간편/단계별/실제뉴스 fixture 검토 흐름, 대본 수정, 취소, 복구, 게시 초안 보존. |
| 초기 설정·영상 | PASS | setup BAT·마법사·라이브러리·30/45/60초 합성 MP4 재생. 사람 품질 평가는 별도 NOT VERIFIED. |
| 기존 AI 영상 | PASS (Fake) | Fake Provider만 사용, 승인·한도·결과 불명 보호, labelled MP4·재시작 보존. 실제 Higgsfield 호환성/가격/품질은 NOT VERIFIED. |
| 신규 예약 | PASS | 실제 Chrome 예약 활성화→6단계 합성 Autopilot→MP4 재생→로컬 초안→앱 프로세스 재시작→동일 SHA256 영상→장기 누락 한 건 skipped, 자동 추가 제작 0. |
| 레이아웃 | PASS | 예약 화면 desktop/mobile/CSS zoom200%, JS 오류·외부 브라우저 요청 0. 사람 사용성 평가는 NOT VERIFIED. |
| 공개 RSS 별도 점검 | PASS / BLOCKED / NOT VERIFIED | 22개 중 17개 시도: 13 PASS, robots 4 BLOCKED, 비활성 5 NOT VERIFIED. Chosun 연결 검사 100개 파싱 PASS이나 **기사 저장을 하는 검사가 아님**. 실제 RSS 기반 예약 운영·Google News 접근을 PASS로 확대하지 않음. |
| 한국어 음성 | NOT VERIFIED | 설치된 한국어 SAPI 음성 0개. 일반 설치 SAPI 합성→WAV→MP4 기술 검사는 PASS, 한국어 발음·사람 청취는 미검증. |

예약으로 생성한 Windows MP4: **30.021029초 / H.264 + AAC / 1080×1920 / 30fps**, 252,526 bytes. SHA256 `2d9cbc736fb5c8e80360c742d98e493b382034edd884c20ab309f3fc8e98b1d4`. 재시작 전후 동일. 예약 시나리오 DB: 기사 8개·대본 1개·영상 1개·게시 초안 1개·Autopilot attempt 6개·artifact 7개, 실제 게시 job/attempt 0. 유료 사용 row/연결 계정/OAuth connection 0. Fake 비용 기록은 실제 과금 증거로 사용하지 않습니다.

워크플로 annotations 37개 모두 notice, warning/failure annotation 0. Node.js 20 사용 중단 경고 없음. pytest의 기존 경고 1건은 별도 유지합니다. 실제 서비스 인증·유료 생성·SNS 게시를 검증한 것으로 표시하지 않습니다.

증거: [워크플로/단계](evidence/phase5e/windows/workflow-run.json), [JUnit](evidence/phase5e/windows/pytest.xml), [pytest 요약](evidence/phase5e/windows/pytest-summary.txt), [BAT·기존 GUI](evidence/phase5e/windows/result.json), [예약 결과](evidence/phase5e/windows/scheduler/scheduler-result.json), [Windows 예약 화면](evidence/phase5e/windows/scheduler/02-reservation-enabled.png), [완료 화면](evidence/phase5e/windows/scheduler/04-completed-video.png), [실제 MP4](evidence/phase5e/windows/scheduler/scheduled-preview.mp4), [Fake AI 영상](evidence/phase5e/windows/ai-video/ai-video-validation.json), [공개 RSS](evidence/phase5e/windows/feed-review/feed-review.json), [한국어 음성 탐지](evidence/phase5e/windows/voice/voice-probe.json).

## 발견·수정 및 한계

- 실제 브라우저에서 hidden `action` 필드가 `form.action`을 가려 예약 켜기가 잘못된 URL로 전송되는 결함을 재현했습니다. Easy form이 `getAttribute('action')`을 사용하도록 수정했고, 상태 갱신 후 재생성된 폼에도 이벤트를 연결하여 실제 활성화 POST를 검증했습니다.
- 전체 회귀에서 기존 DB 복사 도구가 새 revision을 거부함을 확인했습니다. 0012를 지원하고 복사본 예약을 일시 중지하여 원본/복사본 동시 실행 위험을 줄였습니다. 원본과 기존 데이터 보존을 테스트했습니다.
- 기존 schema-head/화면 phase 표기 assertion만 현재 revision/phase로 갱신했습니다. 기존 보안 assertion은 유지했습니다.
- 합성 fixture의 취소한 기사는 기존 제작 claim이 남습니다. 재시도 검증에서는 다른 기사를 사용하고, 같은 기사 재제작 차단은 별도로 확인했습니다.
- 실제 Windows OS 재부팅/절전·사용자 Windows 11 PC 동작은 NOT VERIFIED. 자동 테스트는 앱 프로세스를 종료·재시작하여 영속 상태와 산출물을 확인했습니다.
- 서버가 꺼져 있으면 예약 실행 없음. Windows 자동 기동, 절전 깨우기, OS 예약 작업은 제공하지 않음.
- KST만 지원하며 다른 시간대의 DST 예약 UI는 제공하지 않음. UTC 저장/KST 계산은 OS 시간대와 무관.
- 동시 제작 1개; 검토 대기 작업도 다음 실행을 막음. 예약 50개 제한. 지난 실행 무제한 소급 없음.
- 체험 뉴스는 8개이며 이미 제작한 기사에 대한 claim을 해제하여 무한 반복하지 않음.
- 유료 AI 무인 제작·실제 SNS 게시·Phase 6은 구현하거나 실행하지 않음.

## 변경 파일

신규: `scheduler/`(timing/service), migration0012, `gui/scheduler_routes.py`, `templates/schedules.html`, `static/js/scheduler.js`, `tests/test_scheduler*.py`, `tools/ci_scheduler_validation.py`, 신규 Phase5E Windows workflow, 예약 안내와 이 보고서/증거.

수정: `main.py` lifespan, `db/models.py`, Autopilot start/context/backend, `migrate_data.py`, Easy UI home/start/base/CSS/form 이벤트, CI fixture의 테스트 전용 clock 주입, schema head/phase 표시를 검사하는 기존 테스트, README/AGENTS/architecture. 실제 provider·OAuth·기존 migration은 변경하지 않음.

## Git 및 다음 단계

검증 코드 SHA는 위 `cc295ac57b86c848d702e71ff40f108ea35a3af7`이며 이후 보고서·증거만 별도 커밋합니다. 최종 문서 커밋 SHA는 PR HEAD/최종 제출 메시지에서 확인할 수 있습니다. main 및 기존 PR #1–#13의 원격 ref는 작업 전 snapshot과 동일하며 `evidence/phase5e/protected-refs.json`에 기록했습니다. 사용자 Windows 11에서 앱 기동·절전 후 복귀·한국어 음성·완성 영상의 직접 평가가 다음 승인 판단에 필요합니다. OS 자동 기동, 유료 AI 무인 실행, Phase 6은 별도 승인 전 진행하지 않습니다.


## 실제 GUI 화면 및 증거

아래는 목업이 아닌 실제 Cloud Chromium 캡처입니다. 예약 실행 시각은 테스트 도구에서만 주입한 합성 시계(2031-01-02)를 사용했습니다. 운영 앱에는 시계 변경 환경변수/GUI 플래그를 추가하지 않았습니다.

- [예약 입력](evidence/phase5e/cloud/gui/01-reservation-form.png)
- [예약 활성화](evidence/phase5e/cloud/gui/02-reservation-enabled.png)
- [제작 진행](evidence/phase5e/cloud/gui/03-production-running.png)
- [완료 영상](evidence/phase5e/cloud/gui/04-completed-video.png)
- [게시 대기함](evidence/phase5e/cloud/gui/05-local-review-queue.png)
- [놓친 예약 안내](evidence/phase5e/cloud/gui/06-missed-explanation.png)
- [모바일](evidence/phase5e/cloud/gui/07-mobile.png) · [200% 확대](evidence/phase5e/cloud/gui/07-zoom-200.png)
- [생성 MP4](evidence/phase5e/cloud/gui/scheduled-preview.mp4) · [브라우저/DB/미디어 JSON](evidence/phase5e/cloud/gui/scheduler-result.json)
- [전체 pytest 원문](evidence/phase5e/cloud/pytest.txt) · [JUnit](evidence/phase5e/cloud/pytest.xml) · [기존 Autopilot 브라우저 회귀](evidence/phase5e/cloud/autopilot/autopilot-result.json)

Cloud 재접속 지침은 Phase 5E용 **환경 설정 초안**으로 저장했습니다. 네트워크·비밀정보·저장소 구성은 바꾸지 않았으며 자동 Publish하지 않았습니다. 사용자가 환경 설정에서 검토·저장 후 Publish해야 적용되며, 새 Cloud 인스턴스 복원 검증은 NOT VERIFIED입니다.

다운로드 검토용 `phase5e_review.html`은 Cloud 관리형 브라우저의 `file://` 접근 제한으로 직접 파일 열기 검증이 **NOT VERIFIED**입니다. 앱의 HTTP GUI 검증과 별개입니다. ZIP의 원본 PNG/MP4 및 Markdown 보고서도 함께 제공합니다. Windows에서 받은 텍스트 증거는 내용 변경 없이 CRLF→LF로 정규화했으며 원본/저장 SHA256을 `evidence/phase5e/windows/line-ending-normalization.json`에 보존했습니다.
