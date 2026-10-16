# UX/UI 2차 개편 — 제작 흐름 통합

기준: `af6cbe3435f018ea969f0f50cc3b7dac8da69211` (PR #23). 신규 브랜치: `feat/newsflow-ux-workflow-unification`.

## 변경 전 중복 분석

A: 동일 기능, B: 비슷하지만 실행·승인이 다름, C: 유지할 고급 기능.

| 화면·기능 | 분류와 실제 차이 | 대표 진입점 |
|---|---|---|
| 홈 / Autopilot 시작 | A: 동일 quick-start POST 중복 | 홈 제작 폼 |
| 작업 현황 / 홈 작업 카드 | A: 동일 작업 이력 | 작업 현황; 홈은 최근 작업만 |
| 뉴스 선택 / 뉴스 탐색 | B/C: 제작 대상 선택과 출처 관리·필터 | 제작 중 선택; 관리 기능은 설정 |
| AI Studio / AI 기본 설정 | B: 실행별 선택과 저장된 기본값 | 기본값은 설정, 실행 변경은 고급 |
| Video Studio / 영상 설정 | B/C: 제작별 수정과 저장된 음성·품질 기본값 | 제작 과정; 상세 편집 접기 |
| Autopilot / AI Studio | B: offline/openai 자동 엔진과 CLI 수동 검토 흐름 | 홈에서 실제 지원 경로로 연결 |
| 예약 / 운영 점검 | B/C: 앱 일정 실행과 Windows 로그인 작업 등록 | 설정; 각 승인 그대로 |
| 내 영상 / Video Studio 이력 | A: 동일 RenderJob 목록 | 내 영상 |
| 게시 대기함 / 내 영상 | B: PublishDraft 사실·권리·최종 검토는 별도 | 영상별 검토 동작; 전체 대기함은 고급 |
| API 설정 / 기본 AI | B: 선택과 키·비용 승인은 다름 | 설정의 선택 AI 연결 |
| 음성 설정 / 마법사 / 제작 선택 | A/B: video_default_* 공통값, 제작별 음성은 별도 | 기본값은 통합 설정 |
| Higgsfield / FFmpeg | B/C: 유료 장면 생성과 로컬 최종 합성 | 선택형 설정·기존 제작별 승인 |
| 운영 로그·실행 설정 | C: 진단과 상세 설정 | 설정 → 고급 관리 |

기존 `studio_*`, `autopilot_*`, `video_default_*`를 재사용한다. `ai_*`, `tts_el_*`, `video_ai_*`의 비용·동의 게이트를 합치거나 초기화하지 않는다. 새 migration은 추가하지 않는다.

## 단계별 실제 적용

| 단계 | 실제 실행·제한 |
|---|---|
| 뉴스 수집 | 등록 RSS 또는 로컬 체험 자료; 원문 정책 유지 |
| 분석·대본 | 기본 `studio_*` 선택 재사용. Claude/Codex는 실행별 동의와 대본 검토 흐름. 체험 제작은 Offline임을 명시 |
| 음성 | `video_default_*` 재사용. Supertonic·SAPI·ElevenLabs 선택 보존; 사용할 수 없으면 안내. 외부 TTS는 별도 동의 |
| 장면 | FFmpeg 기본 카드. Higgsfield 선택은 기존 계획·비용 승인으로 연결; 자동 생성하지 않음 |
| 자막·MP4 | 기존 FFmpeg 및 문장 WAV 측정 타이밍 유지 |
| 검토·게시 준비 | 대본·최종 결과·출처·권리 검토 유지; SNS 실행 차단 |

연결 상태는 설정/설치·인증/실제 성공 이력/확인 시각을 나누어 표시한다. 기록이 없으면 미확인으로 표시하며 페이지 GET은 외부 인증·생성 요청을 하지 않는다. 로컬 음성 목록 조회와 파일 존재 검사는 실행 성공을 의미하지 않는다. 모델 무결성·FFmpeg 버전 확인은 명시적인 로컬 점검이다.

## 주요 변경과 재사용

- 주 메뉴 4개. 사이드바 고급 메뉴 제거; 설정의 고급 관리에서 기존 화면을 연다.
- 홈에 뉴스·길이·현재 AI/음성/영상 구성, 시작 버튼 하나, 최근 작업·결과만 표시한다.
- 설정의 단일 저장 폼이 기존 키를 원자적으로 갱신한다. OpenAI/Higgsfield/ElevenLabs의 승인·키·예산은 별도 유지한다.
- 초기 길이·음성·AI·모델·장면 선택을 검증하여 기존 `IntelligenceRun.options`에 기록한다. 이후 분석/대본/영상은 이를 이어받고, 실제 실행 기록과 구분한다.
- 선택한 OpenAI 모델과 기존 자동 엔진 모델이 다르면 대본 검토 경로로 안내한다. Claude/Codex의 완전 자동 실행을 추가하지 않았다.
- 자동 제작과 수동 분석·대본·영상 작업을 같은 목록에 표시하고 연관 기록의 중복을 제외한다. 실패 요청도 조치 필요로 표시하며 자동 재전송하지 않는다.
- Supertonic 기본 선택 저장 시 고정 모델 무결성을 확인한다. 기존 사용 불가 음성을 다른 설정 저장만으로 덮어쓰지 않는다.
- 기존 migration/제작 엔진/비밀키 저장 서비스는 변경하지 않았다.

## Windows Chrome 검증

2026-10-16, 기존 Python 3.14.7 가상환경·FFmpeg 9.0.2 사용. 실제 데이터의 설정은 바꾸지 않고 별도 `validation-output/ux-workflow-unification/ui-test-data`에서 제작했다.

| 시나리오 | 관찰 결과 |
|---|---|
| A 연결 상태 이해 | 7단계의 실제 엔진·설정 필요/확인 필요·비용/확인 시각·성공 이력 구분 표시 확인 |
| B Claude 적용 범위 | 통합 설정에서 Claude 선택 저장 → 홈 → 대본 검토 안내 → AI 화면. 자동 직접 실행 미지원·외부 전송 동의·사용량 문구 확인. 실제 Claude 추론은 실행하지 않음 |
| C Supertonic 실제 사용 | 기본 F1 저장 → 기존 Autopilot → 실제 AudioTrack `supertonic/supertonic:F1/success` → FFmpeg MP4 성공 |
| D 45초 보존 | Claude 안내·AI 초기 문맥 45초 유지. 별도 Offline 체험 제작의 대본/스토리보드/작업/MP4도 45초 유지. Claude/Codex 분석→대본 전달은 Fake 핵심 테스트 |
| E 결과·검토 동선 | 대본 검토, 최종 확인 대기, 완료 작업, 내 영상 및 영상별 검토 진입 확인 |
| F 고급 기능 | 기본 네 메뉴만 표시. 설정의 고급 관리에서 기존 세부 화면 접근 유지 |

실제 MP4: `validation-output/ux-workflow-unification/ui-test-data/outputs/videos/video-1eaddc9be8de4819a136460946838b10.mp4`.
1080×1920 H.264/AAC, 컨테이너 45.02168초, 영상 45.000326초. Chrome 재생 시간이 0→8.50→15.80초로 진행하고 미디어 오류 없음. 문장 WAV 기반 타이밍 `measured_sentences`, 마지막 발화 종료 36.810초, 잘림·축약 없음. 이는 기술적 실행 확인이며 발음·자막 체감 품질에 대한 사람 평가가 아니다.

화면 캡처는 사용자 데이터 노출 방지를 위해 Git에 포함하지 않았다. 로컬 `validation-output/ux-workflow-unification/`에서 `before-home.png`, `before-settings.png`, `after-home.png`, `after-settings.png`, `claude-45-context.png`, `script-review-45.png`, `after-tasks.png`, `after-library.png`, `advanced-only-settings.png` 확인 가능.

## 보존·테스트

- 사용자 SQLite 읽기 전용 백업 후 run.bat 정상 종료·재시작. 전체 테이블 행 수, 설정 해시, 기존 MP4 2개 해시가 전후 동일. SQLite integrity_check `ok`.
- 기존 Codex 기본 선택과 Heami 기본 음성 보존. 임시 검증 데이터만 Claude/F1/45초로 설정했다.
- CSRF/Origin/CSP, 외부 전송 동의, 비용 승인·한도, DPAPI, 중복 요청 보호를 유지했다. 실제 AI/음성 유료 API·OAuth·SNS 호출 없음.
- 변경 범위 핵심 테스트를 실행하고 실패한 이전 UI 기대값/Windows 호스트 의존 fixture만 수정 후 재확인했다. 전체 pytest는 실행하지 않았다.
- 최종 Windows Python 3.12/3.14 Actions 결과와 코드 SHA는 아래에 기록한다.

## 변경 파일

`gui/{autopilot,intelligence,video,video_ai,voice}_routes.py`, 새 `production_{context,status,routes}.py` 및 `task_views.py`, `easy_setup.py`, `main.py`, 대응 홈/설정/AI/영상/작업/음성 템플릿, `static/css/easy.css`, `static/js/{home_production,production_settings}.js`, 변경 영역 테스트, 전용 Windows workflow와 이 보고서.

## 남은 범위

- 실제 Claude/Codex 추론·현재 계정 인증과 ElevenLabs/Higgsfield 유료 호출은 이번 작업에서 미검증.
- 사람의 발음·영상 품질 및 처음 사용하는 사람의 이해도 평가는 NOT VERIFIED. Chrome 시나리오는 개발자의 기능·표시 검증이다.
- Higgsfield 고급 합성은 기존 승인 시점의 기본 음성을 사용한다. 최초 음성과 차이가 있으면 승인 화면에서 명시한다. 해당 경로의 외부 음성 자동화는 확장하지 않았다.
- Codex 웹 검색은 BLOCKED. 기존 엔진이 지원하지 않는 조합은 수동 검토·설정 해결 경로로 안내한다.

## GitHub

최종 검증 결과 기록 대기. 기존 PR #1–23 및 main은 변경하지 않는다.
