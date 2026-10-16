# PR #25/#26 단일 작업실 AI 자동화 통합

## 기준 및 충돌 해결

- 기준: PR #26 `feat/newsflow-single-workspace` / `942ec2afaa71e2378d42dd24196cac822a20ed8f`.
- 선택 재사용: PR #25 `feat/newsflow-ai-news-automation` / `fb53d4898581902be1dce9c2f60a889aa45ffcd2`.
- 공통 조상: PR #24 `515f9544dfa2df587a95b2bafeceef43d08a64a7`.
- 신규 브랜치: `feat/newsflow-unified-ai-workspace`; 새 Draft PR base는 PR #26 브랜치.
- 두 브랜치를 병합하지 않았다. 공통 수정 파일 `autopilot_routes.py`, `task_views.py`, `easy_home.html`, `autopilot_job.html`을 비교했다. PR #26의 공통 상세 partial·조회 모델·카드·플레이어를 유지하고 PR #25의 실행 문맥·분석/대본/사용량 기록을 연결했다. 기존 작업 템플릿 wrapper를 덮어쓰지 않았다.

## 통합된 흐름

작업실에서 **실제 뉴스 + RSS 직접 선택 → 실행별 자료 전송/계정 사용량 동의 → 같은 AI의 분석·대본 생성 → 같은 작업실 대본 검토 → 기존 음성·FFmpeg → 최종 영상 검토 → 재생·MP4 저장**으로 이어진다. 기존 상세 URL은 유지한다.

- 기본 AI·모델·30/45/60초·음성·수집 정책·분야·기간을 요청 ID와 함께 고정한다. 설정 저장과 GET은 추론을 시작하지 않는다.
- 기사/출처, 분석 실행 ID, 대본 실행 ID/초안, 렌더 ID와 검토 상태를 기존 DB에 연결한다. 새 migration이나 데이터 경로 변경은 없다.
- 반복 확인/새로고침/재시작은 성공한 분석·대본을 재사용한다. 실패·시간 초과·결과 불명 요청은 자동 재전송하지 않는다.
- PR #26의 두 메뉴(작업실·설정), 최근 작업/영상 목록, 중복 제거, 선택형 플레이어·다운로드를 재사용한다. 동의와 차단 안내도 작업실 안에 표시한다.
- 경로 지원과 현재 인증 확인을 구분한다. 외부 전송·비용 승인, 대본·출처·권리·최종 검토, CSRF/Origin/CSP, DPAPI와 예약 보호를 유지한다.

## AI별 범위

| AI | 통합 범위 | 이번 실제 실행 |
|---|---|---|
| Claude Code | 기존 공식 CLI로 RSS 분석·대본, 실행별 동의 | Fake만 실행; 실제 구독 추론 NOT VERIFIED |
| Codex | 기존 공식 인증 어댑터로 RSS 분석·대본 | Fake만 실행; 실제 구독 추론 NOT VERIFIED |
| OpenAI API | 기존 승인·토큰 한도·분석/대본 어댑터 | Fake/경계 테스트만; 실제 API 0건 |
| Offline | 기존 체험 뉴스·로컬 대본·제작 유지 | 핵심 자동 테스트 |
| Claude API | 미구현 | 실행하지 않음 |

AI 웹 검색은 전부 **BLOCKED**다. RSS로 자동 전환하거나 대체 Provider를 호출하지 않는다. RSS 자료를 AI 검색 결과로 표시하지 않는다. 구독 사용량은 무료·무제한이 아니며 로컬 토큰 기록을 공급사 청구량/잔여량으로 표시하지 않는다.

## 검증

- Windows 11 / 기존 Python 3.14.7 `.venv`: 변경 영역 402개 중 최초 **400 PASS / 2 FAIL**. 두 실패는 누락된 snapshot fixture의 `source`와 설치되지 않은 음성의 준비 상태 기대값이었다. 이 두 테스트만 보정·재실행해 **2 PASS**. 테스트 삭제/skip 및 보안 완화 없음. Ruff PASS.
- 새 통합 테스트: Fake Claude/Codex × 30/45/60초, 같은 Provider·실행 ID 연결, 인라인 동의, GET 무호출, 중복/재시작 무재전송, 실패 차단, 웹 검색 무 fallback, CSRF/Origin.
- 실제 Windows Chrome: 별도 `127.0.0.1:8779` 테스트 서버에서 웹 검색 차단 → RSS 직접 선택 → 같은 화면 동의 → Fake Claude 분석 1회/대본 1회 → 대본 검토 → Supertonic F1·FFmpeg → 최종 검토 → 같은 화면 재생·저장 확인.
- 테스트 서버는 기존 사용자 DB와 분리했으며 실제 Claude/Codex/OpenAI 호출 메서드를 차단했다. 합성 RSS 자료는 실제 기사/실제 AI 추론 검증으로 간주하지 않는다.
- 영상: 1080×1920, H.264 + AAC, **30.021680초**. Chrome `readyState=4`, 재생 시각 증가, media error 없음. 다운로드 파일과 원본 SHA-256 동일.
- 테스트 작업 `2a23b7736ad2434f913b024660280c8f`, 분석 #1/대본 #2/렌더 #1. 정상 재시작 후 ID·단계·영상 해시 동일, 새 Fake 호출 **0회**. 최종 사람 검토는 대기 상태를 유지했다.
- 원래 `run.bat`으로 8765 앱을 기존 데이터 경로 그대로 재실행했다. 실제 사용자 작업실·설정 확인: 기존 저장 Codex/Heami/체험 30초 및 작업·영상 유지.
- 원본 DB `integrity_check=ok`, 전체 테이블 건수·설정 해시·기존 MP4 2개 해시 작업 전후 동일. 사용자 데이터 백업은 로컬 검증 폴더에만 보존했다.
- 최종 Windows Python 3.12/3.14 CI: 실행 후 아래 GitHub 기록에 결과를 기입한다. 로컬 Python 3.12 재설치/실행은 수행하지 않았다.

로컬 샘플과 화면 캡처는 Git에서 제외한다:

- `validation-output/unified-ai-workspace/ui-test-data/outputs/videos/video-f7459d0b44f84f2eb59cb63d0b0d6bf0.mp4`
- SHA-256 `b2fa62a29bbf3121313356ac4d889606298315c957db699248c63e34fb6653de`
- `validation-output/unified-ai-workspace/{inline-consent,script-review,final-review-playback,inline-player,live-workspace,live-settings}.png`

## 변경 파일

- Autopilot: `backend.py`, `contracts.py`, `service.py`.
- Intelligence: `capabilities.py`, `provider.py`, `schema.py`, `service.py`.
- GUI: `autopilot_routes.py`, `task_views.py`, `production_context.py`, `production_routes.py`, `production_status.py`.
- 화면: `easy_home.html`, `autopilot_start.html`, `autopilot_start_guide.html`, `autopilot_job_detail.html`, `simple_settings.html`.
- 정적 파일: `workspace.css`, `autopilot.js`, `home_production.js`.
- 테스트 10개: `test_ai_news_automation_backend.py`, `test_ai_news_automation_gui.py`, `test_ai_news_contract.py`, `test_unified_ai_workspace.py`, `test_easy_ui.py`, `test_single_workspace.py`, `test_ux_navigation.py`, `test_ux_workflow.py`, `test_ux_workflow_context.py`, `test_ux_workflow_settings.py`.
- 신규 CI `.github/workflows/unified-ai-workspace-windows.yml` 및 이 보고서. 총 32개 파일.

## GitHub 기록 및 남은 검증

- 코드 SHA / 최종 SHA / Draft PR / Windows Actions: 업로드·CI 완료 후 기록.
- 실제 Claude/Codex 구독 추론, 실제 OpenAI API, 실제 RSS 원문 내용의 품질 및 사람의 음성·영상 품질 평가: **NOT VERIFIED**.
- ElevenLabs/Higgsfield는 기존 별도 승인 경로를 유지하며 이번 자동 제작의 무승인 실행 대상이 아니다. AI 웹 검색, Claude API 추가 구현 없음.
- 인증정보·DB·키·모델 가중치·WAV·MP4·사용자 데이터는 커밋하지 않는다. 기존 PR/main 변경·병합, 실제 유료 API·SNS 호출 없음. 통합 완료 후 판정을 기다린다.
