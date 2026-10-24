# 뉴스 기본 이미지·Higgsfield 안내 후속 개선

PR #35 / `codex/newsflow-ux-video-app`. 기준 `c5ed43ffd7140aeca0e7c2521882a06227905805`, 검증 코드 **`672bebd8f50030534c0dcb43332a5641265692ec`**. 2026-10-24 KST.

요청한 두 항목만 변경했다. 원본이 없거나 표시할 수 없는 기사에는 사진 대신 기존 뉴스 아이콘과 ‘이미지 없음’을 표시한다. Higgsfield 화면은 실제 전체/장면별 모드 규칙에 맞게 안내를 나눴다. **엔진·API·DB·승인 정책 변경 없음.**

## 1. 뉴스 기본 썸네일

- 홈 뉴스 목록과 뉴스 선택 화면의 `news-topic-atlas.png` 사진형 fallback을 제거했다. 자산 파일 자체와 다른 기존 이미지는 보존했다.
- 기존 뉴스 아이콘의 SVG 경로를 재사용했다. 그림은 `aria-hidden`, 상태는 실제 HTML ‘이미지 없음’으로 표시한다.
- 출처 제공 대표 이미지가 있으면 기존 same-origin `/news/{id}/thumbnail` 경로, lazy loading, alt, 크기·자르기 방식을 그대로 사용한다. SSRF/TLS/robots·캐시·권리 검사는 변경하지 않았다.
- 이미지가 없으면 바로 아이콘을 표시하고, 요청 실패 시 기존 `hidden` 처리에 따라 아이콘을 표시한다. 출처 이미지가 성공하면 아이콘은 보이지 않는다.
- 검증 중 **캐시된 오류가 defer 스크립트의 error listener 등록보다 먼저 발생하는 경우**를 발견했다. 최초 실행 시 이미 로딩 완료됐지만 `naturalWidth === 0`인 이미지도 숨기도록 보완했다. 새 요청·재시도·다른 이미지 공급사 호출은 추가하지 않았다.
- 홈의 분야별 HTML 부분 갱신에도 동일한 표시가 적용된다. HTML/CSS/JS만 바뀌었고 기사 제목·요약·URL·원본 이미지 메타데이터는 수정하지 않았다.

## 2. AI 영상 방식과 실제 엔진 대조

| 확인한 엔진 규칙 | 근거 | 화면 반영 |
|---|---|---|
| `mode=full`은 준비된 모델이 필요하며 모든 장면을 generated로 만든다. 음성·모델 계약을 저장한다 | `video/ai/service.py:create_plan`, `video/ai/production.py` | ‘전체 AI 영상 · 모든 시각 장면’으로 명시 |
| 전체 계획의 장면을 카드로 변경하거나 모델을 임의 변경할 수 없다 | `update_scenes`, `review`, `test_final_production.py` | 생성 실패 시 카드로 자동 대체하지 않음을 짧게 안내 |
| 독립 mixed 계획은 카드로 시작하며 장면별 카드·로컬 이미지·생성을 선택한다. 숏폼 훅 설정이 있으면 첫 장면은 AI 후보가 될 수 있다 | `create_plan`의 scene source 분기, `update_scenes` | ‘장면별 선택 · 고급’ 카드에 해당 범위를 안내 |
| 기존 Autopilot 전체 AI 작업에 속하는 계획은 owner 정책으로 모든 장면 생성 조건을 유지한다 | `full_job`, `check_full_plan`, `write_policy` | 개별 mixed 설명과 별도로 ‘기존 전체 AI 작업 … 모든 장면 AI 정책 유지’ 표시 |
| 계획 저장 자체는 공급사 제출이 아니다. 생성 승인과 결과의 장면 검토·합성 승인이 따로 필요하다 | `confirm_generation`, `review`, `approve_compose` | 계획 저장·생성·장면 검토·합성·완성 검토/게시 승인을 구분 |
| 실패·결과 불명은 자동 재제출/성공 처리하지 않는다 | `recover`, `test_full_plan_unknown_never_replays` | 기존 검사·상태·재시도 정책 불변 |

이전 ‘고른 장면만 유료 생성’, 무조건 ‘기본은 카드’로 읽히는 공통 문구를 제거했다. 두 기존 카드에서 실제 모드별 차이가 드러나므로 **새 절차 SVG는 불필요하다고 판단해 추가하지 않았다.** 기본 FFmpeg 제작 링크, 선택 기본값 `full`, 폼 이름·POST 경로, 비용/모델/키 준비 검사, 음성 동의와 게시 승인은 그대로다. 실제 Higgsfield 서비스 동작을 확인한 것은 아니며 Fake 검증이다.

## 3. 전후 화면

Cloud Chromium, 동일 합성 기사 3개(원본 제공/원본 없음/로딩 실패). 원본 제공 테스트 이미지는 사진으로 오인되지 않는 단색 래스터다. 다음 캡처는 기사 영역/모드 안내가 읽히도록 스크롤한 실제 뷰포트이며 화면 합성이나 가짜 after가 아니다.

| 화면 | 1366×768 | 1920×1080 | 390×844 |
|---|---|---|---|
| 홈 뉴스 영역 | [전](evidence/visual-asset-followup/before/home-1366.png) · [후](evidence/visual-asset-followup/after/home-1366.png) | [전](evidence/visual-asset-followup/before/home-1920.png) · [후](evidence/visual-asset-followup/after/home-1920.png) | [전](evidence/visual-asset-followup/before/home-390.png) · [후](evidence/visual-asset-followup/after/home-390.png) |
| 뉴스 선택 | [전](evidence/visual-asset-followup/before/news-1366.png) · [후](evidence/visual-asset-followup/after/news-1366.png) | [전](evidence/visual-asset-followup/before/news-1920.png) · [후](evidence/visual-asset-followup/after/news-1920.png) | [전](evidence/visual-asset-followup/before/news-390.png) · [후](evidence/visual-asset-followup/after/news-390.png) |
| AI 영상 | [전](evidence/visual-asset-followup/before/ai-video-1366.png) · [후](evidence/visual-asset-followup/after/ai-video-1366.png) | [전](evidence/visual-asset-followup/before/ai-video-1920.png) · [후](evidence/visual-asset-followup/after/ai-video-1920.png) | [전](evidence/visual-asset-followup/before/ai-video-390.png) · [후](evidence/visual-asset-followup/after/ai-video-390.png) |

기존 스타일·뉴스 카드 크기를 유지하면서 실제 원본이 없는 상태를 구분할 수 있다. 각 크기에서 가로 넘침 없음. AI 방식 선택을 바꿔도 POST/공급사 호출이나 새 계획은 생기지 않았다. 임시 기사 데이터가 유지되는지 비교했다.

## 4. Cloud 검증

Python 3.12.14, Chromium. 운영 앱이 아닌 임시 DB·격리 앱·Fake adapter로 검증했다.

```bash
PYTHONPATH=src:tests:tools \
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_VALIDATION_OUTPUT=/tmp/newsflow-visual-followup/after \
.venv/bin/python -m pytest -q -rs -p windows_final_guard \
tests/test_visual_asset_followup.py tests/test_news_thumbnails.py tests/test_final_production.py \
--junitxml=/tmp/newsflow-followup-cloud.xml
```

**관련 범위 결과: 36 passed / 1 failed / 0 skipped / 0 errors, warning 1건. 전체 PASS 아님.**

- 새 브라우저·full/mixed 계획 검사: 3 PASS. 실제 출처 이미지 유지, 미보유/오류 fallback, 홈 부분 갱신, 3가지 크기, 방식 선택, 기사 보존·새 계획 없음 확인.
- 기존 검사: 33 PASS / 1 FAIL. 뉴스 URL/다운로드 정책, 잘못된 이미지·재요청 억제, full 모드 30/45/60초 계약, 카드 대체 차단, 승인 누락, 중복·결과 불명 재제출 방지, 음성 동의·설정 고정 등.
- 단일 잔존 실패: `tests/test_news_thumbnails.py::test_additive_migration_preserves_synthetic_legacy_tables`. 테스트는 Alembic head를 `0017`로 기대하나 현재 제품은 이미 `0018`이다. baseline `c5ed43f`를 별도 임시 폴더로 추출하여 **같은 Python·의존성·테스트 전체 1건·guard**로 실행한 결과도 동일 이름·오류 메시지로 FAIL. [비교 JSON](evidence/visual-asset-followup/comparison.json).
- 해당 오래된 버전 기대값이나 migration은 이번 범위에서 수정하지 않았다. 이후 보존 단언에 도달하지 못한 이 테스트로 모든 DB 보존을 PASS라고 주장하지 않는다.
- 이번 단일 실패 비교는 **기존 전체 57개 목록 전체를 재비교했다는 뜻이 아니다**. 기존 57 FAIL 기록은 유지하고 전체 회귀를 반복하지 않았다.
- Ruff(추가 테스트): PASS. `pip check`: 의존성 충돌 없음. Cloud pip 캐시 권한 안내와 Starlette/httpx deprecation warning은 숨기지 않았다.

최종 결과 전에 캡처 준비에서 fixture 등록·필수 메타데이터 누락·비동기 부분 갱신/지연 이미지 로딩 대기 문제를 고쳤고, 제품에서는 캐시된 이미지 오류 처리를 보완했다. 초기 실패 로그를 함께 보존했다. 실패 테스트 삭제·skip·보안 완화 없음.

## 5. Windows 검증

실제 GitHub Actions `windows-latest` + Chrome, Python 3.12 / 3.14에서 동일 37건을 실행했다. [Actions #40064158836](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40064158836), 검증 SHA `672bebd8f50030534c0dcb43332a5641265692ec`.

| 환경 | 관련 테스트 | baseline 동일 실패 1건 재실행 | Ruff / pip check |
|---|---|---|---|
| Windows Python 3.12.10 | **36 PASS / 1 FAIL / 0 skip / 0 error** | 같은 테스트 이름·`0018 != 0017` 메시지 재현 | PASS / PASS |
| Windows Python 3.14.9 | **36 PASS / 1 FAIL / 0 skip / 0 error** | 같은 테스트 이름·`0018 != 0017` 메시지 재현 | PASS / PASS |

**Actions 결론은 FAILURE이며 그대로 보존했다.** 실패를 허용 성공 처리하거나 skip하지 않았다. 새 UI/계획 테스트 3건은 두 환경 모두 PASS이며, 이번 범위에 남은 실패는 baseline과 동일한 1건이다. [Windows 비교](evidence/visual-asset-followup/windows-comparison.json), [3.12 원본 XML](evidence/visual-asset-followup/windows-3.12/tests.xml), [3.14 원본 XML](evidence/visual-asset-followup/windows-3.14/tests.xml).

Chrome에서도 각 3크기(1366×768, 1920×1080, 390×844)의 원본/없음/실패 이미지, 홈 부분 갱신, AI 방식 선택, 새 계획 미생성·외부/POST 0건을 확인했다. [Windows 3.12 뉴스 화면](evidence/visual-asset-followup/windows-3.12/news-1366.png), [Windows 3.14 AI 안내 모바일](evidence/visual-asset-followup/windows-3.14/ai-video-390.png). 그 외 PNG/JSON도 환경별 evidence 폴더에 있다.

Python 버전별 임시 데이터/프로필을 사용했다. Windows 사용자 PC, 실제 화면 배율·기존 운영 DB·DPAPI 키·MP4·실제 공급사 품질은 NOT VERIFIED다. 이번에는 UI·상태/계약 테스트만 수행했으며 BAT·렌더링·실계정/게시 전체를 재검증한 것으로 확대하지 않는다.

## 6. 변경 파일 및 보존 범위

제품 변경:

- `src/newsflow/gui/templates/news_thumbnail.html` — 기존 뉴스 SVG/HTML 상태 표시.
- `src/newsflow/static/css/news-thumbnails.css` — 중립 표시·원본 이미지와 상태 전환.
- `src/newsflow/static/css/dashboard.css`, `studio-pages.css` — 사진형 기본 배경 제거.
- `src/newsflow/static/js/news-thumbnails.js` — 캐시된 초기 오류 처리.
- `src/newsflow/gui/templates/news.html` — 기본 이미지 안내를 실제 표시와 일치시킴.
- `src/newsflow/gui/templates/video_ai.html` — 실제 모드·승인 단계 설명만 수정.

검증·자료 변경:

- `tests/test_visual_asset_followup.py` — 격리 Chrome 상태/모드·Fake 계획 검사.
- `.github/workflows/newsflow-cloud-connect-windows.yml` — 기존 workflow에 수동 `visual-assets` 범위 추가, Windows 3.12/3.14 한정. 다른 검증 모드 유지. 광범위 push CI는 `[skip ci]`, 이번 범위는 명시적 dispatch.
- 이 보고서와 `docs/reports/evidence/visual-asset-followup/` — 전후 PNG, 원본 로그/XML, 비교 JSON 및 재현 자료.

뉴스/영상 엔진·DB/migration·API/OAuth·비용/게시 승인 정책·데이터 모델은 변경하지 않았다. 운영 사용자 DB·키·설정·MP4에는 접근하지 않았고 운영 앱도 재시작하지 않았다. 합성 이미지 adapter 요청 2건은 로컬 Fake 응답이며 실제 외부 호출이 아니다. 실제 유료 API/공급사·OAuth·SNS 호출 0건, 새 이미지 API 사용 0건.

남은 사항: 기존 migration 버전 고정 기대값 FAIL, 기존 전체 57 FAIL 기록, 사용자 Windows 11 배율/실제 데이터/실계정·공급사 품질 NOT VERIFIED. 기존 준비·승인 정책을 추정해서 변경하지 않았다. Draft PR #35 유지, main 병합·운영 반영 없이 보고 후 중단.
