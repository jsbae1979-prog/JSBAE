# 자동 제작 게시 문구 연결 결과

- 보고: 2026-10-20 KST
- 기준: `ce727a814246d5773b72b0d1c1791b2ac9211a05`
- 구현 코드: `3081b048cc4c3a9732d2c8a0157ef4b73e6235c1`
- 브랜치: `codex/newsflow-ux-video-app`, 로컬 보존. 원격 push·PR 변경·main 병합 없음.

## 변경

`PipelineBackend._queue`가 게시 화면과 같은 `suggest_metadata`를 사용한다. 자동 제작 완료 시 MP4에 연결된 영상 스냅샷·출처로 제목, 설명, 출처 링크, 제목 기반 해시태그를 만들고 기존 `PublishingService.create`로 게시 대기 초안을 저장한다. 최신 편집 대본을 이미 제작한 영상의 문구로 잘못 가져오지 않는다.

예약 엔진은 `Autopilot.start` 및 같은 `PipelineBackend`를 사용하므로 새 예약 제작도 이 경로를 사용한다. 예약의 기존 지원 대상인 YouTube·Instagram 및 유료 실행 차단 정책은 변경하지 않았다. TikTok 예약 제작이나 무인 SNS 게시를 추가한 것이 아니다.

합성 뉴스·외부 AI 초안의 사실 확인 미완료·무음 안내를 보존한다. 잘못된 형식이나 민감정보로 자동 채움이 중단되면 고정 문구로 대체하지 않고 초안 저장을 중단한다.

기존 작업 ID 기반 중복 방지 및 저장 초안 재사용을 유지한다. 이전 방식의 초안과 사용자가 수정한 제목·설명·태그·카테고리·revision을 덮어쓰지 않는다. 사실·출처·권리 확인, AI 표시 판단, 최종 게시 승인도 자동 처리하지 않는다. 결과는 계속 `review_required`, 외부 게시 실행은 `false`다.

## 검증

Cloud / Python 3.12.14 / 격리 DB·Fake 뉴스·영상·미디어 검사·계정 사용.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs \
  tests/test_autopilot_metadata.py tests/test_autopilot_backend.py \
  tests/test_autopilot_boundaries.py tests/test_autopilot_state.py \
  tests/test_scheduler.py tests/test_scheduler_gui.py \
  tests/test_publish_metadata.py tests/test_publish_metadata_gui.py \
  tests/test_unified_publishing.py tests/test_unified_publishing_gui.py
.venv/bin/ruff check src tests
git diff --check
```

- **PASS: 199 passed / 0 failed / 0 skipped / 1 warning**, 32.51초.
- **PASS:** Ruff, diff check. 초기 테스트 파일의 import 정렬 문제를 수정했다.
- **PASS:** 합성 수집→대본→Fake 영상→검증→초안 저장의 기존 통합 테스트.
- **PASS:** 수동/예약 문맥의 YouTube·Instagram 초안에 공통 문구 저장, 출처·미확인 안내 보존.
- **PASS:** 새 Backend 인스턴스로 재시도해도 기존 초안 한 건과 사용자 수정/빈 설명 보존.
- **PASS:** 민감정보·잘못된 대본 차단, 영상과 대본 연결 검사, 승인 누락 및 중복/결과 불명 회귀.
- **PASS:** Cloud Chromium의 문구 수정→저장→재진입 및 데스크톱/좁은 화면 기존 UI 회귀.
- 경고: 기존 Starlette/httpx 사용 중단 경고.
- 로그: `/tmp/newsflow-autopilot-metadata-tests.txt`.

실제 유료 API·OAuth·SNS 호출은 0건이다. 운영 앱·데이터·키·기존 MP4를 변경하거나 재시작하지 않았다. DB migration 및 UI 재설계도 없다.

## 미검증과 범위

Windows PC 및 Windows Actions의 이번 코드 실행, 실제 플랫폼 업로드, 실제 음질·콘텐츠 품질은 **NOT VERIFIED**다. Fake 영상 검사는 실제 MP4 렌더링 품질 검증이 아니다.

전체 회귀를 반복하지 않았으며 기존 **57 FAIL** 기록을 유지한다. 위 통과는 변경 범위의 결과다. 게시 문구 자동 채움은 로컬 자료 정리이며 새로운 AI 생성 호출이나 모든 플랫폼 옵션의 자동 승인이 아니다.

보고서 작성 후 추가 개발을 중단한다.
