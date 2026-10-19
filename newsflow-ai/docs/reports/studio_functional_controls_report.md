# 목업 차이의 기능 연결 검증

- 작성: 2026-10-19 KST
- 시작 HEAD: `a86d9434c4d9ef5e786ec636a88b737c42ff9638` (작업 트리 clean)
- 구현·검증 코드: `0b19b2fd6e2fa3c5223083bcd631007d3e1450f7`
- 로컬 브랜치: `codex/newsflow-ux-video-app`
- 원격 push / PR #35 변경 / main 병합: 수행하지 않음. 원격 상태는 이번 작업에서 재조회하지 않음.

## 구현한 기능

| 영역 | 실제 연결 | 보존 사항 |
|---|---|---|
| AI 대본 | 전문 뉴스·쉬운 설명·핵심 브리핑, 톤 2종, 시청자 3종. 한국어. 기존 분석에서 같은 Provider·모델로 새 초안 생성 | 허용 목록 서버 검증, 별도 외부 전송·비용 동의, 원본 기사 선택 범위·출처·대본·MP4 보존. 새 초안도 `review_required` |
| 영상 | 장면별 바로 전환 / 검정 페이드. 4번째 효과 타임라인에서 선택 장면 이동. 실제 FFmpeg 필터 적용 | 효과는 새 영상 작업 snapshot에 고정. 기존 작업은 컷 유지. 원래 음성·자막 길이와 최종 검토·게시 승인 유지 |
| 성과 | 저장된 게시 자료의 카테고리별 조회수·영상 수·비중 | 동일 플랫폼/계정/합성 여부 필터 유지. 여러 분야는 복합 주제 한 번만 집계. 미수집 값을 0으로 만들지 않음 |
| 차트 결함 수정 | 하루치 조회수만 있을 때 영역 채움이 임의의 다음 시점까지 이어지던 표시 수정 | 측정된 첫·마지막 X 좌표 안에서만 영역 표시 |

스타일 변경은 기존 대본을 자동 편집하지 않습니다. 대본 상세의 **대본 스타일 변경 · 새 초안**을 열고 선택·동의·생성을 실행합니다. 현재 편집 중인 미저장 대본이 아닌 **원래 저장된 분석 자료**에서 새 초안을 만듭니다. 변경만으로 호출하지 않으며 새 초안을 다시 검토해야 합니다. Offline의 고정 초안은 사용자 스타일을 반영했다고 표시하지 않고 비기본 스타일 요청을 차단합니다. Autopilot의 기존 기본값·작업 기록에는 소급 적용하지 않았습니다.

장면 효과는 **기본 영상 구성 화면**에서 장면별 선택 후 새 MP4에 적용됩니다. 자막 뒤에 고정 페이드 필터를 적용하고 음성·장면 길이는 그대로 유지합니다. 짧은 장면에서는 효과 길이를 제한합니다. 임의 FFmpeg 문자열·명령·경로를 받지 않습니다. Higgsfield 장면 계획의 별도 생성·검토·승인 경로는 유지했습니다.

카테고리는 제작 당시 게시 초안에 보존한 근거에서 읽습니다. 이후 뉴스 분류가 바뀌어도 게시 기록을 재분류하지 않습니다. 비중은 저장된 지표 집합 내 조회수 비중으로, 성장률·추천 점수·미래 성과 예측이 아닙니다. 기존 조회 범위(최근 최대 2,000개 저장 지표), 플랫폼별 일별/누적 스냅샷 정책을 따릅니다.

## 계약·파일 변경

기존 `/ai/generate`에 선택적 `script_style`, `script_tone`, `script_audience`, `source_draft_id`를 추가했습니다. 원본 초안을 지정하면 분석 ID·Provider·모델 일치와 기존 선택 기사 범위를 검증합니다. `IntelligenceService.generate`에서 서버 관리 표현 옵션을 근거와 실행 options에 저장하고, 기존 OpenAI·Claude 공통 요청으로 전달합니다. 사실 확인·구조·출처·복제·비밀정보 검사는 그대로 수행합니다.

기존 `/video/render`에 선택적 장면별 `effects`를 추가했습니다. `VideoCoordinator`가 `VideoProject.snapshot.effects`를 저장하고 작업 실행 시 검증해 `ScenePlan`으로 복원합니다. 기존 요청·작업은 기본 컷을 사용합니다. **새 DB migration이나 기존 migration 수정은 없습니다.**

변경: `intelligence/{presentation,provider,service}.py`, `gui/{intelligence_routes,video_routes}.py`, `gui/templates/{ai,script_style,video,analytics}.html`, `video/{engine,service}.py`, `publishing/analytics.py`, `static/{css/studio-fidelity.css,js/studio-pages.js}`.

검증: 신규 `test_studio_functional_controls.py`, `test_studio_controls_browser.py`, `test_studio_category_metrics.py`. 기존 `test_studio_pages.py`는 효과 트랙 추가에 따라 선택 버튼 수를 4→5로 바꾸고 효과 트랙의 존재·선택 검사를 추가했습니다. 기존 테스트 삭제·skip 또는 보안 완화는 하지 않았습니다.

## 검증

최종 검증 결과: **291 passed / 0 failed / 0 errors / 0 skipped / 1 warning**, 131.19초. 검증 SHA `0b19b2fd6e2fa3c5223083bcd631007d3e1450f7`. Ruff·pip check·git diff --check PASS. 경고는 기존 Starlette TestClient의 httpx 지원 중단 예정 안내입니다.

명령(Cloud Linux, Python 3.12.14):

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
NEWSFLOW_CONTROL_EVIDENCE=/tmp/newsflow-controls-committed \
.venv/bin/python -m pytest \
 tests/test_studio_functional_controls.py tests/test_studio_controls_browser.py \
 tests/test_studio_category_metrics.py tests/test_studio_fidelity.py tests/test_studio_pages.py \
 tests/test_video.py tests/test_intelligence.py tests/test_social_calendar_analytics.py \
 tests/test_api_shorts_intelligence.py tests/test_ai_video_compose.py \
 tests/test_production_choices.py tests/test_production_options_browser.py \
 tests/test_unified_publishing_gui.py -q -rs \
 --junitxml=/tmp/newsflow-controls-committed.xml
```

- Fake OpenAI / Claude: 스타일·톤·시청자 요청 전달, 같은 모델 유지, 출처·선택 기사 보존, 새 초안 저장, 원본 불변, 동의 누락·잘못된 값·원본 ID 거부.
- 영상: 효과 snapshot과 실행 계획 일치, 기존 컷 기본값 유지, 잘못된 효과·승인 누락 차단, 음성·자막/AI 클립 필터 회귀.
- 실제 FFmpeg: **2초 합성 무음 H.264/AAC 1080×1920 MP4**, 검정 프레임→가시 프레임 디코딩으로 페이드 확인, Cloud Chromium의 MP4 디코딩·재생 확인. 실제 음성·립싱크·30/45/60초 사람 평가로 확대 해석하지 않음.
- 실제 브라우저: 1366×768, 1920×1080, 390×844. 스타일 선택·동의 누락·명시적 POST·새 초안·영상 작업 생성, 효과 타임라인/장면 선택, 키보드 포커스, 가로 넘침 검사. 카테고리 화면은 합성 데이터를 명시.
- 기존 제작 옵션·Higgsfield 합성·통합 게시 GUI 관련 회귀 포함. 실제 SNS 요청은 수행하지 않음.

개발 중 테스트 수정: FFmpeg 검사 호출의 테스트 인스턴스 누락 수정, 새 효과 트랙에 맞춘 기존 버튼 수 검증 갱신. 초기 한글 글꼴 환경변수 미설정으로 생긴 기존 10개 skip은 설치된 CJK 글꼴을 지정해 57개 AI 합성 테스트 전부 실행했습니다. 잘못된 테스트 파일명을 지정한 한 명령은 수집 전에 실패했으며 성공 결과에 포함하지 않습니다. 마지막 화면 확인에서 발견한 단일 관측점 차트 문제까지 수정한 뒤 최종 커밋 검증을 수행했습니다.

기존 전체 회귀의 **57 FAIL 기록 유지**. 이번 변경 범위 결과를 전체 PASS로 간주하지 않습니다. Windows Actions를 새로 실행하지 않았고, 원격 코드 변경으로 우회하지 않았습니다.

## 화면·영상 증거

[화면 갤러리](evidence/studio-controls/review.html) · [pytest XML](evidence/studio-controls/pytest.xml) · [검증 메타데이터](evidence/studio-controls/validation.json) · [2초 합성 MP4](evidence/studio-controls/synthetic-fade-2s.mp4)

세 화면 × 세 크기 총 9개 실제 브라우저 캡처. 대본/모바일 일부는 조작부가 보이도록 스크롤한 뷰포트이며 전체 페이지 축소 이미지가 아닙니다. 이전 화면은 별도 합성 자료이므로 데이터 수치의 변화로 기능 효과를 비교하지 않습니다. PNG 원본을 보존했습니다.

## 남은 차이·미검증

**목업 전체와 완전히 동일하다고 판정하지 않습니다.** 이번 작업은 세 가지 기능 연결을 완료한 범위입니다.

- 앵커 인물 생성·립싱크 엔진, 앵커 실영상 소재, BGM 믹싱, 임의 효과 편집은 이번에 구현하지 않음. 기존 음성·Higgsfield·FFmpeg를 새 엔진으로 교체하지 않음.
- 타임라인은 실제 장면 선택·길이 기반 표시·효과 선택에 연결됨. 다중 영상 자유 드래그 편집기나 실제 녹음 파형이라고 표시하지 않음.
- 스타일별 실제 공급사 생성 품질, 한국어 발음/음성·자막 싱크, 유료 영상 품질: **NOT VERIFIED**. Fake는 전달·저장·승인 계약만 검증.
- Windows 11 사용자 PC, Python 3.14 실행, Windows 배율, Windows Actions: **NOT VERIFIED**.
- 실제 계정 성과 조회, OAuth, SNS 게시: **NOT VERIFIED**. 실제 계정·조회수·수익을 만들어 표시하지 않음.
- 실제 유료 API·공급사 계정 조회·OAuth·SNS 호출: **이번 작업 0건**. 테스트는 Fake 주입/합성 값, 로컬 FFmpeg와 임시 DB만 사용. 브라우저 외부 요청도 차단·0건 검사.
- 운영 DB·키·설정·기존 MP4 및 운영 프로세스에 접근하거나 변경하지 않음. 작업은 로컬 커밋에만 보존.
