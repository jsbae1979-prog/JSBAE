# UX 후속 정리 — 최종 검토·설정 순서·중복 안내

- 작성: 2026-10-19 KST.
- 기준: `375d18c8f9cfdcc85cec8e555caf645a78396831` (시작 작업 트리 clean).
- 구현·최종 브라우저 검증 코드: `758863cacc2a424c1c8805b5e994d88b0ce826f9`.
- 브랜치: `codex/newsflow-ux-video-app`. 로컬 커밋만 생성. 원격 push, PR #35 변경, main/다른 브랜치 병합 없음. 원격 상태를 재조회하지 않음.
- 판정: **요청한 Cloud UX 수정·관련 검증 PASS**. Windows와 실제 공급사 품질은 **NOT VERIFIED**.

## 변경

| 기존 불편 | 이번 변경 | 보존 |
|---|---|---|
| 완성 영상인데 장면 승인·제작 강조 | `validate`를 ‘미리보기·최종 검토’로 표시. 실제 재생 가능한 결과가 있는 최종 검토/완료 작업은 장면·승인 기록과 제작 진행 이력을 접음. ‘장면별 승인 대기’ 제거 | 제작 중인 작업의 생성·승인 진입, 최종 영상 검토, 별도 게시 승인 유지. 기록은 삭제하지 않음 |
| Higgsfield 연결보다 한도·모델 우선 | 키 등록 → 모델 준비 → 사용 승인·한도 순서. 미등록 키 안내가 연결 영역으로 이동 | 기존 폼 action·CSRF·hidden 운영값·키 저장·모델 확인·비용 검사 동일 |
| 기본 영상에 AI 영상 안내 | 선택에 따라 표시하는 기존 안내 한 곳만 유지. 접힌 옵션 속 무조건 노출 문구 제거 | Higgsfield 선택 시 모든 장면 생성과 별도 승인 안내 표시 |
| 제작 구성 중복 요약 | 음성·영상 선택 바로 아래와 중복되던 고급 옵션의 요약 제거. 전용 JS·미사용 CSS도 정리 | 실제 선택 필드·작업 snapshot·저장된 기본값 유지 |
| 모바일 저장 버튼 접근 | 기존 배치 유지, 스크롤·포커스 이동·버튼 중앙 가림·실제 저장·재진입 검증 | 고정 저장바나 새 설정 체계 도입 없음. 모바일 첫 화면에 항상 보이는 버튼은 아님 |

설정 탭은 기존 구현을 재사용했다. 음성·AI·렌더·게시 엔진, API 계약, DB/마이그레이션, 의존성, BAT, CI는 변경하지 않았다. 앵커·립싱크·BGM 및 추가 플랫폼 운영 활성화도 이번 범위에 포함하지 않았다.

변경 파일: `gui/templates/{autopilot_job_detail,production_form,video_ai_settings}.html`, `static/js/home_production.js`, `static/css/{creator,easy,workspace}.css`. 기존 테스트 `test_all_scene_browser.py`, `test_production_options_browser.py`, `test_settings_streamlined_browser.py`에 동선 검사를 추가했다. 테스트 삭제·skip 추가·승인 조건 완화 없음.

## 검증 결과

Cloud Linux, Python 3.12.14, Chromium 151, 합성 API/키/음성/클립 및 임시 DB를 사용했다. 실제 Windows 실행으로 보고하지 않는다.

| 실행 | 결과 | 설명 |
|---|---|---|
| 기준 코드 브라우저 | 4 passed / 0 failed / 0 skipped | 변경 전 화면 확보 |
| 개발 중 첫 관련 실행 | 99 passed / 3 failed / 0 skipped | 추가한 테스트의 POST 완료 대기 2건, 모바일 포커스·스크롤 측정 1건 실패 |
| 관련 8개 모듈 실행 | 103 passed / 1 failed / 0 skipped | 응답 대기 보완 후 모바일 smooth-scroll 완료 전 위치 측정만 실패. 제품 코드 동일 |
| 최종 코드 브라우저 재검증 | 4 passed / 0 failed / 0 skipped | 테스트에 스크롤 완료 대기·캡처 위치 고정을 적용한 `758863c`에서 실행. 앞선 실패 포함 |
| 각 테스트의 마지막 결과, 중복 제외 | **104 passed / 0 failed / 0 skipped / 0 errors** | 100개는 관련 실행, 4개는 최종 재검증. 단일 104건 실행 전체 PASS로 표시하지 않음 |
| Ruff / pip check / diff check | PASS | 패키지 충돌 없음 |

각 pytest 실행에는 기존 Starlette TestClient/httpx 지원 중단 예정 경고 1건이 있다. pip check의 캐시 디렉터리 권한 경고는 의존성 오류가 아니다. 실패는 생략하지 않고 [관련 실행 로그](evidence/ux-review-followup/scope.log)와 [최종 브라우저 로그](evidence/ux-review-followup/browser-final.log)에 구분했다.

**전체 회귀는 재실행하지 않았다.** 이전 `cc7b319`의 3827 passed / 10 skipped / 0 failed 결과와 이번 범위 검증을 구분한다. 과거 57 FAIL 및 그 해결 과정은 기존 보고서에 그대로 보존했다.

실행 명령(프로젝트 루트):

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
NEWSFLOW_VALIDATION_OUTPUT=/tmp/newsflow-ux-followup-final \
NEWSFLOW_SETTINGS_EVIDENCE=/tmp/newsflow-ux-followup-final/settings \
.venv/bin/python -m pytest \
 tests/test_all_scene_browser.py tests/test_settings_streamlined_browser.py \
 tests/test_production_options_browser.py tests/test_production_choices.py \
 tests/test_settings_simplification.py tests/test_all_scene_safety.py \
 tests/test_creator_ui.py tests/test_blue_studio_browser.py \
 -q -rs --junitxml=/tmp/newsflow-ux-followup-final.xml
```

최종 재검증은 같은 환경에서 출력 경로를 `/tmp/newsflow-ux-followup-verified`로 바꾸고 `tests/test_all_scene_browser.py tests/test_settings_streamlined_browser.py -q -rs --junitxml=/tmp/newsflow-ux-followup-verified.xml`을 실행했다. 최종 재검증 전에는 제품 소스를 추가 수정하지 않고 테스트의 응답·스크롤 대기와 캡처 위치만 보완했다.

## 실제 확인한 동선

- Fake OpenAI/Claude 각각의 분석·대본 → 별도 Fake 장면 생성 승인 → 장면 검토 → 합성 승인 → 실제 로컬 FFmpeg → MP4 브라우저 재생 → 최종 검토 → 로컬 게시 대기함 보관.
- 최종 검토와 완료 상태 모두 미리보기 단계 강조, 승인 진입 버튼 제거, 기존 기록 링크는 접힌 영역에서 키보드로 열기 가능.
- 대기함 등록 후 `content_reviewed=False`, 대상 계정 없음 유지. 기존 공급사 요청 수 증가 없음.
- 기본 FFmpeg + Fake ElevenLabs 경로도 최종 검토를 강조하며 AI 장면 기록은 나타나지 않음.
- 1366×768, 1920×1080, 390×844에서 가로 넘침 검사. 저장 버튼 포커스·뷰포트 내 배치·중앙 클릭 지점 가림 검사 및 모바일 실제 저장 후 재진입.
- 합성 키 접기/비노출, 키 바이트·서비스 승인값 보존, 기본값 변경과 제작 화면 반영, 기존 링크 이동, 설정 탭 전환·키보드 조작·유효성 검증 유지.
- 기본/AI 영상 선택을 반복해도 선택에 맞는 안내만 표시. 설정 저장/표시 조작이 공급사 호출을 실행하지 않음.

## 전후 화면

[전후 화면 갤러리](evidence/ux-review-followup/review.html) · [SHA·검증·이미지 해시](evidence/ux-review-followup/summary.json)

- [최종 검토 — 변경 전](evidence/ux-review-followup/before-review.png) / [변경 후](evidence/ux-review-followup/after-review.png)
- [Higgsfield — 변경 전](evidence/ux-review-followup/before-higgsfield.png) / [변경 후](evidence/ux-review-followup/after-higgsfield.png)
- [제작 화면](evidence/ux-review-followup/production-desktop.png) / [모바일 제작](evidence/ux-review-followup/production-mobile.png)
- [설정 첫 화면](evidence/ux-review-followup/settings-desktop.png) / [모바일 저장 버튼](evidence/ux-review-followup/settings-mobile-save.png)

원본 PNG 11장. 전후는 이번 작업에서 각각 기준 SHA와 검증 SHA의 실제 Cloud 브라우저로 촬영했다. 검토 비교 이미지는 요소 전체, Higgsfield 비교 이미지는 전체 페이지이며 나머지는 실제 뷰포트다. 이미지를 축소한 것을 Windows 배율 검증으로 간주하지 않는다. 검토 갤러리의 이미지 11장과 링크 9개를 임시 loopback 정적 서버에서 Chromium으로 열어 확인한 뒤 서버를 종료했다. 브라우저의 로컬 file URI 접근은 관리 정책상 차단되어 그 경로의 열기는 미검증이며 정책을 변경하지 않았다. 파란 윤곽선은 키보드 포커스다. 전후 합성 데이터 시각·내용 차이를 제품 성과 변화로 해석하지 않는다.

## 보존·미검증

- 실제 유료 AI·공급사 계정·OAuth·SNS 호출: **0건**. 기존 Fake transport와 브라우저 외부 요청 차단 사용. 운영 데이터·키·설정·영상·프로세스 접근/재시작 없음.
- 승인 전 생성 차단, 결과 불명·재시도·비용 보호 등 기존 안전성 검사 통과. 서버 로직은 변경하지 않았다.
- Windows 11 PC, Python 3.14, Windows Actions, 실제 한국어 음질·자막 싱크·공급사 영상 품질·실계정 게시: **NOT VERIFIED**.
- 다음 단계: 사용자 검토. Windows PC 복귀 후 실행·청취·시청 검증은 별도 승인 범위. 이번 작업 후 추가 개발·원격 반영 중단.
