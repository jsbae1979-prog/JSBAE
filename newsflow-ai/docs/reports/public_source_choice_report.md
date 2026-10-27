# 공개 출처 선택과 다기사 분석 경로 확인

- 작성: 2026-10-20 KST
- 기준: `64505bb` / 검증 코드: `43aeab9c75c3017d1db34984ed666cb4d397d4a1`
- 브랜치: `codex/newsflow-ux-video-app`. 로컬만 변경, 원격 PR #35/main 변경 없음.

## 공개 출처 선택

통합 게시 작업실과 기존 YouTube·Instagram 게시 양식에 **게시 설명에 자동 출처 링크 포함** 체크박스를 추가했다. 선택하면 기존 공통 문구 생성기가 만든 출처 묶음을 설명에 넣고, 해제하면 그 묶음만 제거한다. 직접 작성·수정한 출처는 설명에서 편집한다. 기존 설명의 다른 문장과 내부 원문 기록을 삭제하지 않는다.

화면에서 보이는 최종 설명을 기존 검토 저장 경로로 저장한다. 체크박스는 설명 편집 보조 기능이며 별도의 숨은 승인/설정 플래그가 아니다. 재진입 시 저장된 설명에 출처 묶음이 있는지로 표시 상태를 복원한다. 기존 게시 초안의 공개 여부를 일괄 변경하지 않는다. JavaScript가 없으면 체크박스를 비활성화하고 설명 직접 편집은 유지한다.

자동 제작은 계속 내부 출처를 보존한 초안을 만든다. 사용자는 게시 전 해당 초안의 공개 출처를 선택할 수 있다. 선택을 저장한 뒤 자동 제작 저장 경로가 재실행되어도 기존 초안을 덮어쓰지 않는 정책은 유지한다. 새로운 전역 설정이나 DB migration은 없다.

출처·사실·저작권 검토와 AI 표시 판단 및 플랫폼별 최종 게시 승인은 그대로다. 라이선스에서 출처 표시를 요구하는 자료는 표시해야 한다는 안내를 유지한다. 출처 공개 해제는 사용 허가나 사실 확인을 대신하지 않는다.

## 여러 기사 분석 여부 — 실제 코드 확인

- `autopilot/backend.py:_select`: 통합/API 제작의 후보를 최대 10개 범위에서 확보하고, 뉴스 활용 수준 등으로 선별한 후보를 `service.analyze(candidates, ...)`에 전달한다. 여러 기사 후보의 제목·요약·출처 비교가 가능하다. 실제 후보가 한 개일 수도 있다.
- 같은 단계에서 추천/선택한 기사 하나를 `article_id`로 확정한다.
- `_script`: `service.generate(..., article_ids=[ctx['article_id']])`로 전달한다.
- `intelligence/service.py:generate`: 해당 선택 ID에 맞춰 직접 기사 근거 목록을 제한한다. API 경로에서는 기존 분석 결과도 참고 자료로 유지하지만, 여러 유사 기사 전체를 대본의 직접 근거로 넘기는 자동 종합 제작은 아니다.
- 원문 전체를 무단 수집하는 구조가 아니며 RSS/API 검색으로 확보한 제목·요약·출처를 사용한다.

따라서 **여러 후보 분석은 구현되어 있지만, 복수 유사 기사를 하나의 영상으로 종합하는 자동 제작이 완료되었다고 판정할 수 없다.** 이번 변경에서 기사 선정·대본 생성·비용/승인 경로를 임의로 확대하지 않았다.

## 검증 결과

Cloud Python 3.12.14 / Chromium / 임시 DB·합성 계정·Fake 서비스.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_SOURCE_CHOICE_EVIDENCE=/tmp/newsflow-source-choice-evidence \
.venv/bin/python -m pytest -q -rs \
  tests/test_publish_source_choice.py tests/test_publish_metadata.py \
  tests/test_publish_metadata_gui.py tests/test_autopilot_metadata.py \
  tests/test_autopilot_backend.py tests/test_autopilot_boundaries.py \
  tests/test_unified_publishing.py tests/test_unified_publishing_gui.py \
  tests/test_youtube_gui.py tests/test_instagram_gui.py
.venv/bin/ruff check src tests
git diff --check
```

- **PASS: 141 passed / 0 failed / 0 skipped / 1 warning**, 49.43초. 경고는 기존 Starlette/httpx 사용 중단 경고.
- **PASS:** Ruff, diff check.
- **PASS:** 세 게시 양식에서 출처 해제/복원, 수정된 설명 저장, 설정 이동 후 재진입, 내부 `VideoProject.sources`/`PublishDraft.sources` 보존.
- **PASS:** 1366×768 및 390×844 실제 Cloud 브라우저에서 옵션 접근·가로 넘침 확인, 키보드 Space 조작, 선택만으로 외부 호출/승인 발생하지 않음.
- **PASS:** 자동 제작 초안 저장·재실행·보존 및 기존 승인/중복/결과 불명 회귀.
- 증거: `/tmp/newsflow-source-choice-tests.txt`, `/tmp/newsflow-source-choice-evidence/source-choice-1366.png`, `source-choice-390.png`.
- 실제 유료 API·OAuth·SNS 호출 **0건**, 운영 앱/DB/키/영상 변경 및 재시작 없음.

Windows PC/Windows Actions, 실제 공급사·업로드, 실제 다기사 종합 제작 품질은 **NOT VERIFIED**. 전체 회귀를 반복하지 않았으며 기존 **57 FAIL** 기록을 유지한다. 이번 범위의 통과를 전체 PASS로 확대하지 않는다.
