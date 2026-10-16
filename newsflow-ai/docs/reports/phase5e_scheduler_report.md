# Phase 5E — 예약 자동 제작 및 운영 자동화

작성 기준: 2026-10-16 KST. 개발 범위는 Phase 5E만이며 실제 유료 AI·OAuth·SNS 실행과 OS 작업 등록은 하지 않았습니다. Windows Actions 결과는 실행 완료 후 이 보고서에 별도 반영합니다.

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
| 실제 MP4 | PASS | 30.021초, H.264/AAC, 1080×1920, 30fps, 2채널 무음. 브라우저 재생 시간 증가 및 재시작 후 SHA256 동일 확인 |
| 화면 크기 | PASS | 실제 Chromium 1440 desktop, 390 mobile, 1280/CSS zoom200% 가로 넘침 없음. 사용자 편의성 연구를 뜻하지 않음 |
| Windows 전체 회귀/BAT/Chrome/DPAPI | NOT VERIFIED | 신규 브랜치 Windows Actions 실행 대기; 결과 완료 후 갱신 |
| 기존 유료 비용·결과 불명·OAuth·보안 | PASS (Cloud 회귀) | 기존 테스트 삭제/skip 추가 없음. 외부 AI key/live flag를 비운 환경. DB 유료 사용/예약·OAuth connection·SNS attempt 0 |
| 공식 Task Scheduler 문서 | PASS (문서 열람) | 2026-10-16 KST Microsoft HTTPS GET 200, 위 안내 문서의 세 URL |
| 사용자 Windows 11 PC / 청취·영상 품질 / 실제 RSS·AI | NOT VERIFIED | 이번 합성 흐름으로 실제 서비스나 사용자 PC 품질을 주장하지 않음 |

실행 명령:

```text
NEWSFLOW_FONT_PATH=<검증된 한국어 글꼴> NEWSFLOW_LIVE_TEST=0 NEWSFLOW_AI_LIVE_TEST=0 python -m pytest -q -rs --junitxml=<output>/pytest.xml
python tools/ci_scheduler_validation.py --mode cloud --browser-executable /usr/bin/chromium --output <output>/gui
python tools/ci_docs_link_check.py --output <output>/docs
```

Cloud의 7 skip: opt-in 실제 AI/RSS 2개 + Windows 전용 5개. 기존 `StarletteDeprecationWarning` 1건은 숨기거나 제거하지 않았습니다. 실제 Windows BAT 검증은 Linux에서 주장하지 않습니다.

## 발견·수정 및 한계

- 실제 브라우저에서 hidden `action` 필드가 `form.action`을 가려 예약 켜기가 잘못된 URL로 전송되는 결함을 재현했습니다. Easy form이 `getAttribute('action')`을 사용하도록 수정했고, 상태 갱신 후 재생성된 폼에도 이벤트를 연결하여 실제 활성화 POST를 검증했습니다.
- 전체 회귀에서 기존 DB 복사 도구가 새 revision을 거부함을 확인했습니다. 0012를 지원하고 복사본 예약을 일시 중지하여 원본/복사본 동시 실행 위험을 줄였습니다. 원본과 기존 데이터 보존을 테스트했습니다.
- 기존 schema-head/화면 phase 표기 assertion만 현재 revision/phase로 갱신했습니다. 기존 보안 assertion은 유지했습니다.
- 합성 fixture의 취소한 기사는 기존 제작 claim이 남습니다. 재시도 검증에서는 다른 기사를 사용하고, 같은 기사 재제작 차단은 별도로 확인했습니다.
- 서버가 꺼져 있으면 예약 실행 없음. Windows 자동 기동, 절전 깨우기, OS 예약 작업은 제공하지 않음.
- KST만 지원하며 다른 시간대의 DST 예약 UI는 제공하지 않음. UTC 저장/KST 계산은 OS 시간대와 무관.
- 동시 제작 1개; 검토 대기 작업도 다음 실행을 막음. 예약 50개 제한. 지난 실행 무제한 소급 없음.
- 체험 뉴스는 8개이며 이미 제작한 기사에 대한 claim을 해제하여 무한 반복하지 않음.
- 유료 AI 무인 제작·실제 SNS 게시·Phase 6은 구현하거나 실행하지 않음.

## 변경 파일

신규: `scheduler/`(timing/service), migration0012, `gui/scheduler_routes.py`, `templates/schedules.html`, `static/js/scheduler.js`, `tests/test_scheduler*.py`, `tools/ci_scheduler_validation.py`, 신규 Phase5E Windows workflow, 예약 안내와 이 보고서/증거.

수정: `main.py` lifespan, `db/models.py`, Autopilot start/context/backend, `migrate_data.py`, Easy UI home/start/base/CSS/form 이벤트, CI fixture의 테스트 전용 clock 주입, schema head/phase 표시를 검사하는 기존 테스트, README/AGENTS/architecture. 실제 provider·OAuth·기존 migration은 변경하지 않음.

## Git 및 다음 단계

검증 코드 SHA, Windows Actions URL 및 신규 Draft PR은 실행/생성 후 기록합니다. main 및 기존 PR 보존을 최종 확인합니다. 사용자 Windows 11에서 앱 기동·절전 후 복귀·한국어 음성·완성 영상의 직접 평가가 다음 승인 판단에 필요합니다. OS 자동 기동, 유료 AI 무인 실행, Phase 6은 별도 승인 전 진행하지 않습니다.
