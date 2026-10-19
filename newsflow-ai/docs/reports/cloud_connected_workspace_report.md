# PR #35 — Cloud 통합 제작·게시 검증 및 Windows 실행 준비

보고 시각: 2026-10-19 09:50 KST. 최종 운영 대상은 Windows 11이다. Cloud는 격리 개발·검증에만 사용했다.

## 범위와 변경

기준은 PR #35 `75077729adcbe67fcf9954462485405747db621d`(UX 검증 코드 `dbd4ba4`), 제작·게시 엔진 기준은 PR #34 `590ffd4`이다. 기존 `codex/newsflow-ux-video-app` / Draft PR #35를 이어간다. 신규 PR·main/PR #34 수정·병합은 없다.

제품 변경은 홈의 기존 `/create` 링크를 **새 뉴스로 쇼츠 만들기**로 명확하게 표시하고 검색란 범위를 설명하는 것, 그리고 **같은 작업 URL로 승인 후 이동할 때 오래된 검토 화면이 남는 결함**을 수정한 것이다. 브라우저 재현 테스트에서 이전 화면이 유지되는 실패를 확인한 뒤 `autopilot.js`에 같은 작업 경로의 성공 응답 후 새로 읽기만 추가했다. 게시 검토를 저장해도 같은 페이지 갱신 전 미저장 경고 상태가 해제되지 않을 수 있는 문제도 브라우저에서 재현해 `app.js`의 저장 완료 이벤트를 갱신 분기 앞으로 이동했다. 승인 요청을 재전송하지 않고 변경된 상태를 GET으로 읽는다. 기존 `/autopilot/quick-start`·실행별 동의·저장된 제작 설정을 재사용한다. 새 뉴스 검색 API, 독립 제작 엔진, 음성 엔진, 복잡한 설정 화면이나 디자인 개편은 없다. 보관 기사 검색은 기존 `GET /news?q=…` 그대로다.

추가 파일은 실제 기존 서비스 연결을 검증하는 `tests/test_cloud_workspace_flow.py`, 기존 BAT를 격리 TEMP 프로필에서 점검하는 `tools/ci_windows_launch_smoke.py`, PR35 전용 Windows 3.12/3.14 workflow와 본 보고·최소 증거다. DB/migration·키 저장·OAuth·API 비용·검색/대본/TTS/FFmpeg/게시 엔진은 수정하지 않았다. 추정 사전 예약·요청별 금액 한도도 다시 도입하지 않았다.

## Cloud에서 완료한 것

앱/UI·Cloud 검증 SHA: `f8326f78e7ed15e9719c3cd174cbbea255dce846`. 최종 Windows 점검 코드 SHA: `009d6095aceacecf8cdd55fefa76bb38db8f3095`이며, f8326f7 이후 변경은 CI BAT 도구의 하위 서버 종료 대기뿐이다. 앱·UI·엔진·테스트는 동일하다. 이후 커밋은 보고서·증거만 추가한다.

| 검사 | 결과와 범위 |
|---|---|
| 사전 API·게시·UI 계약 (`7507772`) | PASS — 201 passed / 0 failed / 0 errors / 0 skipped, warning 1. 제품 문구·상태 화면 갱신/저장 경고 보완 전 실행. 검색·분석·대본·예산·timeout·현재 통합 게시 계약은 이후 변경하지 않음 |
| 최종 UI·통합 범위 (`f8326f7`) | PASS — 50 passed / 0 failed / 0 errors / 0 skipped, warning 1. 최종 코드에서 작업실·편집·선택·API GUI·동일 URL 새 상태 및 저장 경고·실제 FFmpeg 브라우저 흐름을 함께 검증 |
| 실제 HTTP/Chromium 통합 | PASS · 위 50건에 포함된 통합 2건 및 브라우저 상태 회귀 2건 — Fake OpenAI/Claude API 각각 1건과 화면 갱신/저장 경계 브라우저 회귀. 합성 API/계정/TTS만 주입하고 실제 Autopilot·IntelligenceService·SQLite·FFmpeg·게시 서비스를 사용 |
| Ruff / pip check / diff check | PASS — 설치 의존성 변경 없음 |
| 기존 전체 회귀 | **FAIL 기록 유지** — `dbd4ba4`의 3503 passed / 57 failed / 20 skipped / 0 errors. 이번에는 전체를 재실행하지 않았고 최신 전체 PASS나 실패 수 감소를 주장하지 않음 |

숫자가 겹치는 테스트가 있어 위 실행 건수를 더해 전체 회귀 수치로 표시하지 않는다. 신규 브라우저 fixture의 계정 유형 enum과 비동기 응답/화면 갱신 대기를 작성 중 보완했다. 한 Cloud 실행에서 Chromium 경로를 누락해 25 passed / 5 setup errors가 났고 명시적 경로로 관련 UI 18건을 다시 검증했다. 테스트를 삭제·skip하거나 보안 검사를 완화하지 않았다. warning은 기존 Starlette/httpx TestClient deprecation이다.


최종 Cloud 명령(설치된 Chromium 경로만 테스트에 명시):

```text
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium NEWSFLOW_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc python -m pytest -q -rs tests/test_single_workspace.py tests/test_creator_ui.py tests/test_creator_scene_browser.py tests/test_model_picker_browser.py tests/test_ux_navigation.py tests/test_api_shorts_gui.py tests/test_publish_save_browser.py tests/test_cloud_workspace_flow.py
python -m ruff check src tests tools
python -m pip check
```

## 뉴스 → 대본 → 영상 → 게시의 실제 연결

1. **보관 기사 선택:** 기존 뉴스 검색·상세·AI 선택 계약을 유지한다. 현재 서비스의 저장 기사 기반 분석·대본은 범위 테스트로 확인했다. 이전 PR35 화면 검증 자료를 반복 복사하지 않는다.
2. **새 뉴스:** 홈 → 기존 `/create` → 저장된 OpenAI/Claude API·분야·기간·확보 정책 → 실행별 자료 사용·비용 동의. 동의 없이 POST하면 422이고 Fake Provider 호출도 0건이다. 실제 앱 설정을 Fake로 활성화하는 환경변수나 사용자 옵션을 만들지 않았다.
3. **API 처리:** 같은 선택 API에서 search → analysis → script를 각 1회 처리하고 해당 provider/model·출처·미확인 상태·실행 ID를 보존한다. IntelligenceService 및 기존 API 계약을 사용한다. 합성 API 비용 저널은 test_only이고 실제 청구가 아니다.
4. **대본 검토·편집:** 작업실의 검토 대기 → 기존 편집기 POST → revision 2 저장 → 같은 작업실로 복귀. 저장만으로 API/TTS를 재호출하지 않는다. 실제 사람 검토를 자동으로 완료했다는 뜻은 아니다.
5. **기존 영상 제작:** 명시적 대본 검토 후 합성 WAV(실제 말소리 없음)와 기존 FFmpeg로 1080×1920 H.264/AAC 약 30초 MP4를 생성한다. Chrome/Chromium에서 재생 시간이 진행되고 다운로드한 파일과 로컬 파일 SHA-256이 일치한다. 자막·오디오 스트림/측정 타이밍 경로는 검증하지만 한국어 발음·의미상의 싱크·콘텐츠 품질은 NOT VERIFIED다.
6. **검토 대기함:** 완성 영상 검토 후 같은 작업의 대기함 초안을 저장한다. 이 시점에도 계정 ID는 없고 내용·권리·출처 승인 체크는 false다. 작업 완료가 게시 승인이 되지 않는다.
7. **게시 준비·Fake 게시:** 같은 MP4의 YouTube/Instagram/양쪽 선택 → 기존 검토 저장 → 별도 게시 승인 → 기존 플랫폼 서비스에 주입한 Fake 전송. 공개 게시 동의 없이 실행하면 422이며 두 Fake 전송도 0건이다. API·OAuth·실제 업로드는 없다.
8. **플랫폼 독립 상태:** OpenAI 통합 브라우저에서 YouTube 완료 / Instagram 처리 대기를 표시하고, SQLite 저널에서 통합 게시 객체를 재구성한 뒤 Instagram만 이어간다. YouTube Fake 전송은 총 1회다. Claude 브라우저에서는 YouTube 단독 완료를 확인한다. 기존 통합 게시 테스트에서 Instagram 단독·실패·불명·동시 실행·승인 부재·연결 부재·다운로드만 수행하는 경로를 함께 확인했다. 서비스 재구성 검증과 OS/앱 재시작 검증은 구분한다.

브라우저의 외부 요청·JS 오류는 0건이다. 테스트는 새 pytest TEMP DB·합성 키/계정만 사용하며, urllib 외부 어댑터 접근은 실패하도록 막았다. 실제 서비스 키·토큰을 읽거나 외부로 MP4를 보내지 않았다. 실제 유료 API·Google/Meta 인증·SNS 업로드/게시 호출은 **0건**이다.

## Windows Actions

첫 실행 `39180889013`은 최종 성공으로 사용하지 않는다. Python 3.12는 범위 221건 통과 후 BAT 점검의 TEMP 경로 차이로 거부됐고, 3.14는 220건 통과/1건 브라우저 화면 갱신 중 수동 reload 경합 실패였다. 두 번째 실행 `39181710354`에서는 두 버전 모두 223건이 통과했지만, 부모 BAT 종료만 기다린 후 하위 서버의 server_stop 기록을 즉시 검사해 BAT 단계가 실패했다. 기존 호환성 검증 도구와 같은 최대 30초의 실제 종료 기록 대기를 추가했다. 종료 기록 assertion을 제거하지 않았다. OS/Python TEMP 경계 검사를 완화하지 않고 실제 Python TEMP 경로로 호출을 수정했다. 브라우저는 실제 화면 상태 완료와 성공 응답을 기다리며, 발견된 같은 URL 상태 갱신 결함도 보완해 다시 검증했다.

최종 코드의 완료된 실행만 아래 결과로 사용한다.

**PASS · 최종 Actions [39182144245](https://github.com/jsbae1979-prog/JSBAE/actions/runs/39182144245)**, code `009d6095aceacecf8cdd55fefa76bb38db8f3095`. 해당 실행의 전체 job/단계가 success임을 API에서 확인했다.

| Windows runner | 범위 pytest | Chrome/Fake API→MP4→Fake 게시 | 실제 BAT·종료·재시작 | Ruff·pip check |
|---|---|---|---|---|
| Python 3.12.10 | 223 passed / 0 failed / 0 errors / 0 skipped / warning 1 | PASS | PASS | PASS |
| Python 3.14.8 | 223 passed / 0 failed / 0 errors / 0 skipped / warning 1 | PASS | PASS | PASS |

native current-user DPAPI는 합성 비밀값의 기존 회귀 1건을 포함해 실행했다. 실제 서비스 토큰은 발급·저장·조회하지 않았다. [최종 Actions/단계/수치](evidence/cloud-connected-workspace/windows-actions.json) · [3.12 BAT](evidence/cloud-connected-workspace/windows-312-bat.json) · [3.14 BAT](evidence/cloud-connected-workspace/windows-314-bat.json). 최종 정리 시 runner 테스트 프로세스 트리는 기존 CI cleanup으로 종료하며, CTRL_BREAK 정상 종료의 증거는 첫 서버의 실제 server_stop 기록으로 구분한다.

[Actions artifact · 합성 JSON/PNG](https://github.com/jsbae1979-prog/JSBAE/actions/runs/39182144245#artifacts)에서 두 Python 버전의 원본 자료를 확인할 수 있다. 기존 실패 실행 두 건은 [시도 이력](evidence/cloud-connected-workspace/windows-attempts.json)에 FAIL로 보존했다. 이전 성공으로 최종 성공을 대체하지 않았다.

Windows workflow는 기존 lockfile·Chrome·FFmpeg/ffprobe·한국어 글꼴·Windows DPAPI를 사용한다. API/게시/GUI 범위만 실행하고 3500여 건 전체 회귀는 반복하지 않는다. `run.bat`는 실제 cmd.exe에서 실행하며, 새 TEMP의 `LOCALAPPDATA`로 기본 `%LOCALAPPDATA%\NewsFlowAI` 위치를 확인한다. 최초 실행→기본 라우트→중복 실행 거부→CTRL_BREAK 종료 기록→동일 SQLite 값·무결성 재조회까지 확인한다. 별도 테스트 서버는 loopback 임시 포트, BAT smoke는 기존 기본 8765를 사용한다. 기존 포트 점유 시 다른 앱을 종료하지 않고 점검을 거부한다.

GitHub에 업로드하는 artifact는 합성 결과 JSON·핵심 화면 PNG뿐이다. MP4/WAV/DB/DPAPI 파일·키·토큰은 업로드하지 않는다. CI 실행은 사용자 Windows 11 PC 실행의 증거가 아니다.

## 기존 실패 57개 중 핵심 관련 항목

[정확한 57개 ID별 분류](evidence/cloud-connected-workspace/prior-57-triage.json)는 이전 동일 환경 비교 결과와 JUnit 실패 문맥·현재 구현을 검토한 결과다. 모두 구식이거나 모두 해결됐다고 단정하지 않는다.

- 이전 CLI 자동 제작/작업실 20+7+7건은 현재 로컬 `topic_reference`·안내와 이전 AI 분석/CLI 호출 기대의 차이가 중심이다. 특히 CLI script 오류 대신 로컬 검토 단계에 도달한 항목은 미해결 경로 차이로 남긴다. 현재 승인 대상인 OpenAI/Claude **API** 흐름과 분리하여 새 검증을 수행했다. CLI 로그인·추론 테스트는 실행하지 않았다.
- `test_realcontent`의 3건은 timeout/rate limit/응답 오류 후 retryable=True를 기대한다. 결과 불명·중복 비용 방지를 위해 False인 기존 보호를 완화하지 않았다. 현재 API 실패·timeout·재시도 차단 계약은 범위 테스트로 확인했다.
- 작업 저널의 `request` 키, `news_usage` 인수 추가, 준비 미완료일 때 동의 대신 승인 설정 안내를 요구하는 차이가 있다. 이번 정상 흐름/승인 없는 요청 차단과 별개로 기존 테스트 불일치를 남겼다.
- 나머지 메뉴·화면 문구/추정 안내, Cloud 모의 Windows kernel32 문제 등은 제품 결함 여부와 환경·기대값 문제를 구분해야 한다. native DPAPI는 Windows CI 결과로 별도 기록한다. 추정 비용 UI를 되살리거나 오래된 테스트를 삭제하지 않았다.

새 검증에서 현재 API 정상 흐름의 엔진 결함은 확인되지 않았다. 작업실의 같은 URL 승인 후 화면 갱신 및 게시 검토 저장 후 경고 상태 결함은 브라우저에서 확인하고 최소 JS 수정으로 보완했다. [이전/수정 JS의 동일 fixture 비교](evidence/cloud-connected-workspace/navigation-defect-reproduction.json)에서 document 재조회가 1회→2회로 바뀌며 최신 상태가 표시됨을 확인했다. 검증한 Fake 시나리오가 통과했다는 범위의 결론이며, 전체 제품 무결함·실계정 운영 성공을 의미하지 않는다.

## Windows PC 복귀 후 최소 확인

1. 로컬 Codex/터미널에서 현재 브랜치와 `git status --short --branch`를 확인한다. 미커밋 변경이 있으면 먼저 별도 보존한다. 작업 중 파일을 덮어쓰거나 기존 커밋을 재작성하지 않는다. 원격 PR35 브랜치를 fetch하고 동일 로컬 브랜치에서만 `git pull --ff-only origin codex/newsflow-ux-video-app`로 가져온다. 기존 로컬 브랜치가 없으면 `git switch --track origin/codex/newsflow-ux-video-app`를 사용한다. main을 체크아웃해 병합하지 않는다.
2. 기존 앱을 정상 종료한 뒤 사용자 데이터 `%LOCALAPPDATA%\NewsFlowAI`를 보존/백업한다. DPAPI 키 파일은 같은 Windows 사용자 경계에 묶이므로 임의 재생성·다른 계정 이동·로그 출력하지 않는다. 실제 DB·기존 영상 호환성은 사용자 PC에서 확인할 항목이다.
3. Python 3.12 또는 3.14, FFmpeg/ffprobe PATH, Chrome, 한국어 SAPI 노출 상태를 확인하고 기존 `run.bat`를 일반 권한으로 실행한다. Python 3.13은 지원하지 않는다. `http://127.0.0.1:8765`로 접속하며 LAN 공개나 자동 포트 변경을 하지 않는다. 설치 실패·중복 실행 시 README 안내를 따르고 임의로 다른 프로세스를 종료하지 않는다.
4. 기존 초기 설정에서 저장 위치·음성·자막을 확인한다. 우선 무API 체험 제작·MP4 저장/재생·정상 종료·재실행 후 기존 자료 보존을 확인한다. 이어서 사람의 30/45/60초 시청·한국어 발음·자막 싱크·실제 화면 배율을 기록한다. OS 자동 시작/예약 등록은 별도 명시적 동의가 있을 때만 진행한다.
5. 실제 RSS·AI 요청·계정 연결·비공개 업로드는 별도 승인된 검증 범위에서 수행한다. 키 저장과 실제 인증/검색 성공은 다르며, 설정 저장만으로 실제 호출을 켜지 않는다.

기존 [운영 점검 문서](https://github.com/jsbae1979-prog/JSBAE/blob/009d6095aceacecf8cdd55fefa76bb38db8f3095/newsflow-ai/docs/windows_operational_readiness.md)는 Phase5F 시점 설명과 고정 브랜치 링크를 포함한다. 현재 기능·설치는 이 PR35 브랜치의 [README](https://github.com/jsbae1979-prog/JSBAE/blob/009d6095aceacecf8cdd55fefa76bb38db8f3095/newsflow-ai/README.md)와 현재 화면을 기준으로 한다. Windows PC가 연결되어 있다고 주장하지 않는다.

## 실계정 연결 준비 (모두 실행하지 않음)

- **YouTube:** Google Cloud 프로젝트, YouTube Data API 활성화, Desktop OAuth client 설정·동의 화면/테스트 사용자·해당 채널 권한을 준비한다. 앱의 동의 화면·테스트 사용자·할당량과 identity 조회/업로드 scope를 각각 확인한다. 실제 채널 로그인과 identity/업로드 권한 확인, 비공개 MP4 1회 업로드 승인은 별도 단계다. Shorts는 기존 YouTube 업로드 API와 분류 요건을 사용하며 새 업로드 API를 만들지 않는다.
- **Instagram:** Meta 앱, Facebook Login for Business의 user access token 구성, Page에 연결된 Business/Creator 계정과 권한(`instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`), 사용자 Page 관리/콘텐츠 권한을 준비한다. 배포 대상에 따라 App Review·Advanced Access·Business Verification이 필요하다.
- **인증 중계:** 기존 [HTTPS 인증 중계 문서](https://github.com/jsbae1979-prog/JSBAE/blob/009d6095aceacecf8cdd55fefa76bb38db8f3095/newsflow-ai/docs/INSTAGRAM_AUTH_RELAY.md)를 사용한다. 정확한 HTTPS `/oauth/callback`, 서버 측 App Secret 관리, 인증 query/body/header 비기록, 단일 worker·일회성 verifier·세션 만료 정책을 준비한다. Windows 앱에 공유 App Secret을 넣지 않는다. 중계는 인증만 담당하며 MP4를 공개 URL로 만들거나 보관하지 않는다. 이번 작업에서 서버·DNS·인프라 배포나 Meta 인증은 하지 않았다.

## 증거와 종료

[이번 보고서·최소 증거 ZIP 다운로드](cloud_connected_workspace_review.zip). 기존 UX 전체 화면 ZIP은 재생성하지 않는다.

[Cloud 요약](evidence/cloud-connected-workspace/cloud-summary.json) · [OpenAI Fake 흐름](evidence/cloud-connected-workspace/cloud-openai-flow.json) · [Claude Fake 흐름](evidence/cloud-connected-workspace/cloud-claude_api-flow.json) · [대본 검토 화면](evidence/cloud-connected-workspace/cloud-api-script-review.png) · [합성 플랫폼 부분 결과 화면](evidence/cloud-connected-workspace/cloud-synthetic-partial-result.png) · [기존 엔진 보존 확인](evidence/cloud-connected-workspace/preservation.json).

Windows 사용자 PC·실제 API·계정/OAuth·게시·한국어 청취 및 콘텐츠 품질은 **NOT VERIFIED**다. 기존 UX 전후 스크린샷/ZIP은 원래 커밋에 보존하며 중복 생성하지 않았다. 실제 유료 호출·운영 데이터/키/설정 변경·운영 앱 재시작·사용자 PC 원격 접근·main/다른 PR 병합은 없다. 검증 자료 제출 후 추가 개발 없이 판정을 기다린다.
