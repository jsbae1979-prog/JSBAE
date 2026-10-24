# Windows 11 실사용 전환 사전 점검

2026-10-24 KST · Repository `jsbae1979-prog/JSBAE` · PR #35 Draft.

**최종 판정: CONDITIONAL. 운영 반영은 보류한다.** 사용자 PC에서 읽기 전용 현황 확인과 별도 승인된 격리 검증을 준비할 수 있으나, 실제 데이터 경로·DB revision·실행 중 작업·DPAPI 복원 조건이 확인되기 전에는 업데이트/재시작을 진행하지 않는다.

## 기준과 이번 변경

- 요청/시작 HEAD: **`0a59bfb41eec6b243e4470f67cd53c1e7cd07e52`**. 로컬/원격 일치, 작업 트리 clean으로 시작했다.
- Windows 검증 HEAD: **`341f062303d83c5a2f430bf0651ac2fe811ba696`**. 제품 소스·run.bat·의존성·migration은 기준 HEAD와 동일하다. 변경은 격리 pytest 및 기존 CI의 수동 `transition` 범위뿐이다.
- 이후 문서·근거만 제출한다. 최종 문서 SHA는 PR 댓글에 별도 기록한다. PR Draft 해제/main 병합/운영 배포 없음.
- 실행 가능한 절차·사용자 PC 체크리스트: [Windows 업데이트·백업·롤백 설계](../windows_update_backup_rollback.md).

## 1. 실행·저장 구조 — 코드로 확인 / 사용자 PC는 미확인

`run.bat`은 자신의 폴더로 이동하고 기존 `.venv\Scripts\python.exe`를 우선한다. 없으면 Windows launcher에서 3.14, 3.12 순으로 찾으며 3.13은 지원하지 않는다. `tools/windows_launcher.py`는 venv 설치 fingerprint 확인·필요 패키지 설치·pip check를 수행한다. 설치 실패는 서버 실행으로 이어지지 않는다. `.launch.lock`과 포트 사전 검사 후 `python -m newsflow.main`을 실행한다.

런타임은 데이터 폴더의 `server-<port>.lock`, `migration.lock`, 실제 소켓을 확보한 뒤 앱을 만든다. 기본 주소는 `127.0.0.1:8765`이며 포트 충돌 시 자동 변경하지 않는다. 설정에서 허용되는 바인딩도 loopback뿐이다. 일반 실행은 환경변수로 포트를 명시할 수 있으나 이번 운영 계획은 기본 8765를 유지한다. 자동 시작 경로는 명시된 데이터 루트와 8765를 사용한다.

`R`은 **실제 실행 시 확인해야 하는 데이터 루트**, `P`는 실제 설치된 `newsflow-ai` 폴더다. R은 일반 실행에서 `NEWSFLOW_DATA_DIR`가 있으면 그 경로, 없으면 실행 환경의 `%LOCALAPPDATA%\NewsFlowAI`다. Cloud의 `./data` fallback은 개발 전용이며 Windows 운영 경로가 아니다. 과거 LocalCache 또는 `C:\Codex\NewsFlowAI` 기록을 현재 운영 경로로 확정하지 않는다.

| 보존 대상 | 코드상 위치/연결 | 보존 방침·주의 |
|---|---|---|
| SQLite | `R/newsflow.db`, WAL/SHM 및 존재하는 journal | WAL 모드. 정지 시점 전체 세트 보존 + 복사본에서 canonical DB 생성. main DB만 복사 금지 |
| 설정·작업별 선택 | DB `app_settings`, Autopilot 요청/단계 JSON, draft sources/options, AI plan 계약 등 | 글로벌 기본값과 과거 작업별 고정값을 함께 보존 |
| 세션/CSRF | `R/session.key` 또는 명시한 환경변수 | 일반 API 키와 별개. 값/파일 외부 첨부 금지 |
| 뉴스/출처/중복/썸네일 메타데이터 | DB `news_sources`, `news_articles`, `article_mentions`, `article_scores`, `article_thumbnails`, `news_list_states` 등 | 기사 ID와 분석·초안 참조가 연결됨. 뉴스만 별도로 재수집해 대체하지 않음 |
| AI 분석/대본/편집 | `intelligence_runs`, `content_drafts`, `ai_usage`, `api_request_reservations` | 실행 결과·revision·출처·실제 사용량/결과 불명 기록 보존 |
| 영상·장면·음성·자막 | DB `video_projects`→`video_scenes`, `audio_tracks`, `subtitle_tracks`, `render_jobs` | draft/project/job ID와 출력 파일/해시 관계 보존 |
| 완성 MP4/로컬 이미지 | `R/outputs/videos`, `R/assets` | 전체 파일+SHA-256. 썸네일만 보존해 MP4를 누락하지 않음 |
| AI 생성 클립·중간 파일 | `R/ai-clips`, `R/render-tmp`; DB `ai_video_plans`, `ai_video_scenes`, `video_ai_usage` | 재시작 시 미참조 클립·일부 중간 폴더 정리가 있으므로 실행 전 백업 필요 |
| 외부 음성 캐시·사용 기록 | `R/tts-elevenlabs`의 WAV·ledger·측정 기록 | WAV만 복사하지 말고 ledger/동의·요청 기록도 보존 |
| Instagram 이미지 콘텐츠 | `R/outputs/generated-feed-images`, `R/outputs/image-posts`; `image_posts`, `image_post_deliveries` | DB 파일명·hash·계정별 delivery 상태와 실제 이미지를 함께 보존 |
| 캐릭터 제작 | `R/character`의 작업 JSON·참조·clip·final MP4·review·소리 자료 | DB 밖 JSON도 사용자 자료. 루트 전체 백업으로 포함 |
| AI API 키 | `R/ai-key.dpapi`, `anthropic-api-key.dpapi`, `video-ai-key.dpapi`, `tts-elevenlabs-key.dpapi`, `serpapi-key.dpapi`, `feed-delivery-key.dpapi` | Windows current-user DPAPI 또는 환경변수. 실제 파일 존재는 NOT VERIFIED |
| OAuth 클라이언트/토큰 | `R/youtube-desktop-client.dpapi`, `tiktok-desktop-client.dpapi`, `youtube-oauth/`, `instagram-oauth/`, `tiktok-oauth/`; DB `platform_accounts.credential_ref`, 연결/identity/rotation/lifecycle 기록 | 암호문·계정 바인딩·DB pointer를 같은 시점으로 복원. 다른 PC/SID 복원 보장 없음 |
| 게시 준비/승인/결과 | `publish_drafts`, `publish_validations`, `publish_jobs`, `publish_attempts`, `publish_evidence`, `publish_schedules` | success/unknown/failed·중복 방지 식별자를 함께 보존. 과거 DB 복원이 외부 게시를 취소하지는 않음 |
| 제작 예약·작업 복구 | `production_schedules`, `scheduled_runs`, `autopilot_jobs/attempts/artifacts/events/article_claims` | 활성화/일시중지와 진행 상태는 코드 업데이트와 별개. 초기화 금지 |
| 로그·운영 상태 | `R/logs`, `startup-status.json`, lock 파일 등 | 로그는 사설 보존·민감정보 점검. lock 파일 삭제로 실행 강제 금지 |
| DB 밖 기본 디렉터리 | `R/content`, `R/videos`, 기타 사용자 하위 폴더 | 오래된 구조·미확인 파일도 제외하지 않고 보존 |
| 설치 영역의 사용자 파일 | `P/.env` 존재 여부, `P/local-models/supertonic3` 또는 별도 모델 경로, 외부 로컬 자료 | tracked 소스와 구분. 기존 미커밋 파일·모델을 새 소스로 덮어쓰지 않음 |
| 외부 인증 중계/Secret Store | Meta 중계 서버 App Secret·환경변수·OS 보안 저장소 등 | PC의 data 폴더에 모두 있다고 가정하지 않음. 별도 승인된 보존/재등록 계획, 평문 export 금지 |

근거: `paths.py`, `config.py`, `db/session.py`, `main.py`, `intelligence/credentials.py`, `video/service.py`, `video/ai/{keys,clips,service}.py`, `video/elevenlabs_tts.py`, `oauth/{youtube,instagram,tiktok,production_dpapi}.py`, `publishing/{image_posts,image_generation,image_delivery}.py`, `character/service.py`, `video/supertonic_assets.py`.

## 2. 시작 시 변경/복구 영향

아래는 실제 코드 동작이며, 실행 중 업데이트를 금지하는 이유다.

- `create_app()` 자체가 DB `upgrade(head)`와 credential rotation/lifecycle/expiry, intelligence·수집·영상·OAuth·게시 상태 복구를 수행한다. 단순 import된 앱을 만들어 화면만 확인해도 DB가 바뀔 수 있다.
- 일반 시작의 `video_ai.start()`는 recover 후 활성 장면 작업이 있으면 worker를 깨운다. 기존 승인·한도가 유효한 경우 제출/조회 경로가 이어질 수 있다. 결과 불명 재제출 차단은 유지되지만 이것이 외부 통신 0건을 뜻하지는 않는다.
- `video.recover()`는 진행 렌더를 interrupted로 표시하고 `render-tmp/job-*`를 정리한다. `video_ai.recover()`는 일부 상태를 unknown/in_progress로 갱신하고 미참조 `ai-clips`를 정리할 수 있다.
- lifespan에서 제작 scheduler와 publishing calendar를 시작한다. 실제 예약 게시 dispatch는 현재 기본 비활성이지만, 이 사실을 전체 앱 무작업 모드로 해석하면 안 된다.
- Autopilot 진행 작업은 중단/결과 불명 등으로 복구될 수 있고 사건/승인 이력도 갱신될 수 있다. 따라서 정확히 같은 행을 유지해야 하는 **백업 시점**은 앱 실행 전에 확보해야 한다.
- 자동 시작 인수는 일부 AI worker 자동 재개를 제한하지만 모든 migration/복구/예약을 막는 maintenance 모드가 아니다. 임의의 환경변수로 안전하게 읽기 전용 실행할 수 있다고 안내하지 않는다.

운영 전환 차단 조건: 미확인 데이터 루트, 진행 worker/활성 예약, 유료/게시 결과 불명, 안전한 정지 미확인, 검증되지 않은 백업, 코드/DB 복원 조합 불명, 실제 비밀정보가 있는 복사본의 무단 앱 실행.

## 3. 업데이트·백업·롤백 설계 결과

[실행 순서와 체크리스트](../windows_update_backup_rollback.md)에 경로 확인→안전한 중지→고유 사설 복원 지점→해시/SQLite 검사→격리 migration→별도 승인 후 전환→실패 시 복원 순서로 정리했다.

핵심 결정:

1. **전체 데이터+코드의 한 복원 지점**. 이전 SHA, source archive/bundle, 미커밋 patch, DB revision, 설정·암호문·미디어·승인을 묶는다.
2. **정지 시점 raw + canonical DB**. main/WAL/SHM를 원본에서 삭제하지 않고 함께 보존한다. 일관성 확인/정규화는 검증용 복사본에서만 수행한다.
3. 파일 수·크기·SHA-256, integrity/외래키/행 보존 검증이 모두 끝나야 VERIFIED. 저장 공간·권한·부분 실패·원본 변경·백업 변조 시 업데이트/재진입 차단.
4. rollback은 이전 코드와 그 시점 DB/설정/키/미디어의 복원이다. 코드만 이전으로 바꾸지 않으며, 기존 실패 DB의 WAL을 복원 DB와 섞지 않는다.
5. 운영 DB의 Alembic downgrade 금지. 백업 이후 유료 호출·토큰 회전·게시가 있었다면 단순 되돌림도 금지하고 외부 상태를 별도 대조한다. 외부 성공 이력이 사라지는 rollback은 중복 전송 위험이다.
6. 새 운영용 업데이트/배포 도구는 개발하지 않았다. 추가 Python 파일은 `tests/`의 합성 pytest rehearsal이며 임의 운영 경로를 받는 CLI가 없다. 정상 종료 확인·디스크 공간/권한 판정 자체를 자동으로 제공하는 제품 기능이라고 주장하지 않는다.

## 4. Migration 분석과 기존 FAIL 구분

현재 Alembic head는 **0018**이다. `db/session.py:migrate`가 앱 시작 시 head로 upgrade한다.

| 항목 | 분석/판정 |
|---|---|
| 0017→0018 | `image_posts`, `image_post_deliveries` 2개 테이블과 FK/unique 제약을 추가. 기존 테이블/행을 변경하는 migration 문장은 없음 |
| 0016→0017 | 뉴스 표시 상태·작업실 숨김용 `news_list_states`, `workspace_removals` 2개 테이블 추가 |
| 합성 upgrade 검증 | 0016의 기존 **42개 업무 테이블 / 14행**, 0017의 **44개 업무 테이블 / 14행**에 대해 모든 기존 테이블 SQL·행 보존, integrity/외래키 검사 통과. 빈 테이블도 schema 비교 포함. 큰 실제 DB/모든 이전 revision 검증은 아님 |
| 0018 downgrade | 피드 콘텐츠/전달 기록 테이블을 drop. 데이터 보존 롤백으로 승인 불가. 기존 revision들도 drop table/column이 있으므로 일괄 downgrade 금지 |
| 기존 `0017` 기대 FAIL | `test_news_thumbnails.py::test_additive_migration_preserves_synthetic_legacy_tables`는 head를 `0017`로 고정 기대한다. 최신 0018과 불일치하는 **테스트 기대값 노후화**로 확인. 이 assert 실패 이후 보존 검사는 실행되지 않았으므로 그 옛 테스트를 데이터 보존 PASS로 해석하지 않음. 이번에는 별도 합성 보존 검사를 추가했고 옛 테스트·migration은 변경하지 않음 |
| `migrate_data` 제한 | 0001~0015만 허용하고 DB·session.key만 복사하며 일부 예약을 일시중지시킨다. 현행 0018은 실제 격리 테스트에서 거부됨. **현재 전체 백업/이전 도구로 사용 BLOCKED**. 실패 후 원본 행 보존·대상 DB 미생성 확인 |
| 이전 코드 호환성 | 이번 기준 0a59bfb와 검증 커밋은 제품 코드가 같음. 코드 archive 추출/해시와 동일 제품의 복원 후 앱 초기화는 확인. 사용자 PC의 미확인 구버전 binary/의존성과 모든 스키마 조합은 **NOT VERIFIED** |

실증 범위에서 기존 행을 파괴하는 additive upgrade 결함은 발견하지 못했다. 그러나 최신 이전 도구의 적용 범위 부족, 시작 시 상태 변경/정리, destructive downgrade, 백업 후 외부 상태와의 불일치는 실제 운영 전환을 막아야 하는 위험이다. 이것을 UI 테스트 성공으로 해소됐다고 판단하지 않는다.

### 과거 57 FAIL 이력

과거 기록을 삭제하거나 새 PASS로 덮지 않는다. 또한 서로 다른 SHA·선별 범위의 수치를 ‘현재 정확히 57건 실패’라고 재계산하지 않는다.

- 과거 57개 FAIL 재현/분석 기록과 `cc7b319`의 이후 해결 보고는 [기존 보고서](regression_57_resolution_report.md)에 별도 SHA 근거로 존재한다. 그 당시 전체 3827 PASS 기록은 **현재 HEAD의 전체 PASS 증거가 아니다**.
- 최근 Windows bounded 재검증(`f6aedc5` 제품)에서 과거 57개 대응 parameter를 포함한 **59건 중 52 PASS / 7 FAIL**이 기록됐다. GUI 가격/메뉴/헤더/진입 폼 기대값 5건과 요청 token 옵션 계약 2건이다. [원본 실패 목록](evidence/final-windows-ui/py312/historical-failures.json). 토큰 2000 vs 1400/1600 차이는 별도 계약 검토 대상이며 실제 공급사 청구 결함으로 단정하지 않는다.
- 별도 UI 범위 125 PASS / 5 FAIL은 문구 기대 4건과 390px 메뉴 높이 기대 1건이다. [원본](evidence/final-windows-ui/py312/scoped-failures.json). 이것만으로 DB 파괴/rollback 불능을 입증하지는 않는다.
- 대본 동선 초기 실패와 이후 Fake fixture 수정 검증은 [대본 동선 재검증](windows_script_flow_recheck.md)에 별도 기록했다. 이번에 다시 수행하지 않았다.
- 직전 시각 개선 `672bebd`의 Cloud/Windows 각각 **36 PASS / 1 FAIL**은 위 schema 기대값 실패이며 기준 c5ed43f에서도 동일했다. [비교](evidence/visual-asset-followup/comparison.json), [Windows 비교](evidence/visual-asset-followup/windows-comparison.json).

이번 단계는 절차/보존 검증이다. 기존 전체 회귀를 반복하거나 테스트를 삭제·skip해 전체 PASS를 만들지 않았다.

## 5. 격리 검증 결과

코드 `341f062303d83c5a2f430bf0651ac2fe811ba696`에서 실행했다. 제품은 기준 0a59bfb와 동일하다.

| 환경 | pytest | 별도 BAT | 결론 범위 |
|---|---|---|---|
| Cloud Python 3.12.14 | **14 PASS / 0 FAIL / 1 SKIP / 0 ERROR** | 실행하지 않음 | native DPAPI 1건은 Windows 전용으로 명시 skip |
| Windows Python 3.12.10 | **15 PASS / 0 FAIL / 0 SKIP / 0 ERROR** | **PASS** | 실제 Windows runner, 새 TEMP 프로필 |
| Windows Python 3.14.9 | **15 PASS / 0 FAIL / 0 SKIP / 0 ERROR** | **PASS** | 실제 Windows runner, 새 TEMP 프로필 |

[Windows Actions #40065472207 — SUCCESS](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40065472207). Ruff PASS, Windows pip check PASS. 각 pytest 실행에 기존 Starlette/httpx deprecation warning 1건. 다른 workflow 범위의 job skipped는 이 작업의 pytest skip과 구분한다. **전체 제품 회귀 PASS를 뜻하지 않는다.**

재현:

```bash
PYTHONPATH=src:tests:tools .venv/bin/python -m pytest -q -rs -p windows_final_guard \
  tests/test_windows_transition_plan.py \
  tests/test_windows.py::test_install_failure_stops_marker_and_redacts \
  tests/test_windows.py::test_server_socket_conflict_and_release \
  tests/test_windows.py::test_invalid_secret_not_printed \
  -o junit_family=legacy --junitxml=/tmp/newsflow-transition-cloud.xml
```

Windows는 같은 대상 목록과 기존 `tools/ci_windows_launch_smoke.py`를 사용했다. 실제 BAT는 fresh TEMP에서 8765 기동·중복 실행 차단·Ctrl+Break 종료(server_stop)·재시작·DB marker 유지·7개 route HTTP 200을 확인했다. 사용자 설치 경로가 아니다.

테스트별로 입증한 것:

- 합성 뉴스·분석·대본·설정·일시중지 예약·게시 success/unknown/failed 기록을 포함한 DB snapshot/복원.
- FFmpeg로 만든 작은 합성 MP4, PNG, 무음 WAV, session key/opaque 합성 파일의 크기·SHA-256 보존. 실제 음질/콘텐츠 품질 테스트가 아님.
- SQLite WAL에 남은 커밋 행까지 canonical snapshot에 반영. 이 fixture는 읽기 확인을 위한 유휴 연결을 유지했으며 **실행 중 운영 백업을 승인하는 테스트가 아니다**.
- 업데이트 후보에서 트랜잭션 실패를 주입한 후 원래 논리 데이터 확인, 별도 새 복원 디렉터리로 rollback, 두 차례 앱 초기화/TestClient 주요 route 확인. 원본/봉인 백업은 불변.
- 실제 코드 archive의 이전 SHA 복원과 run.bat/main.py 바이트 일치. 사용자 PC의 구버전 코드/venv를 실측 복원한 것은 아님.
- 실행 중으로 판정된 상태, 공간 부족, 권한 오류, 부분 복사, 복사 중 변경, 백업 변조, 기존 백업/복원 위치 덮어쓰기 거부. 공간/권한/부분 실패는 **주입 시나리오**이며 실제 디스크를 가득 채우거나 운영 ACL을 변경하지 않았다.
- Windows current-user native DPAPI로 **synthetic-only vault** 암호문을 만든 뒤 같은 사용자 문맥의 다른 임시 폴더에서 복원·로드. 다른 논리 계정 바인딩 거부. 실제 서비스 token 사용/복호화 없음. 다른 Windows 계정/다른 PC에서의 성공·거부 검증은 별도 NOT VERIFIED.
- 프로그램 설치 실패/민감 오류 비노출·소켓 충돌 검사 재사용.

CI 업로드는 XML과 비밀값 없는 BAT/outcomes JSON으로 **명시적으로 제한**했다. 임시 DB·raw/canonical 백업·MP4/WAV·DPAPI 암호문·Git archive를 Actions artifact에 넣지 않았다. 테스트 프로세스는 `windows_final_guard`로 외부 호출/OAuth 실행을 차단했다. BAT 프로세스는 서비스 키/계정/활성 예약이 없는 새 TEMP 프로필로만 실행했다. 실제 유료 API·OAuth·SNS 실행 0건.

## 6. 상태 판정과 남은 조건

| 상태 | 항목 |
|---|---|
| **PASS** | 현재 코드 구조 분석, 합성 backup/restore·WAL·0016/0017→0018 보존, Windows 3.12/3.14 BAT 시작/정상 종료/중복 차단, 같은 Windows 사용자 합성 DPAPI 복원, 격리 오류 시나리오 |
| **FAIL — 기존 기록 유지** | 과거 57 FAIL 및 이후 SHA별 bounded 실패 기록, 직전 migration 기대값 1 FAIL. 이번에 삭제/수정/전체 PASS 처리 안 함 |
| **BLOCKED — 운영 적용** | 사용자 PC 경로/revision/활성 작업/백업 미확인, 최신 전체 이전에 `migrate_data` 사용, 운영 DB downgrade, 백업 후 외부 결과 미대조 상태의 단순 rollback |
| **NOT VERIFIED** | 사용자 실제 Windows 11 PC·기존 DB 대용량/구버전 조합·키·미디어·배율·음질·실계정·다른 PC/계정 DPAPI·전원 장애/물리 디스크·실제 사용자 ACL·실제 설치 경로 전환 |

**CONDITIONAL**: 절차 설계와 격리 검증 자료는 준비됐다. 사용자 PC에서 경로·현재 코드/DB·작업 상태를 읽기 전용으로 확인하는 다음 단계는 가능하지만, 운영 전환 승인은 아니다. 체크리스트의 백업·복원·재진입 방지 조건을 충족하고 별도 승인을 받아야 실제 업데이트/재시작을 검토할 수 있다.

## 7. 제출 파일·종료

- `docs/windows_update_backup_rollback.md`: 보존·백업·업데이트·롤백·PC 체크리스트.
- `docs/reports/windows11_transition_preflight.md`: 이 분석/위험/검증 보고서.
- `tests/test_windows_transition_plan.py`: 합성 tmp_path 전용 절차 검증. 운영용 utility 아님.
- `.github/workflows/newsflow-cloud-connect-windows.yml`: 수동 transition 범위, Windows matrix/기존 BAT 재사용, artifact allowlist.
- `docs/reports/evidence/windows-transition/`: 원본 결과·비교/파일 manifest. 실제 DB·키·사용자 파일 없음.

운영 PC 접근/변경·유료 API·실제 인증/게시·데이터 이동·main 병합 없음. 기존 데이터·기능·보안/비용/게시 정책과 PR Draft 보존. 자료 제출 후 추가 개발을 중단한다.
