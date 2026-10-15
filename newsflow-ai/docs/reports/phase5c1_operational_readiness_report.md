# NewsFlow AI — Phase 5C.1 운영 준비도 완료 보고서

확인일: 2026-10-15, 시각은 한국 시간(KST, UTC+9). 운영 대상 Windows 11 / Python 3.12. 기본 주소 `http://127.0.0.1:8765`, 사용자 데이터 `%LOCALAPPDATA%\NewsFlowAI`. 개발 담당: Claude Code (패키지 A–E 병렬 구현 후 통합·적대적 검토). 기준 브랜치 `feat/newsflow-phase5c` @ `ca2812150380012e1bd6867ae5eea3ae0155d487`, 작업 브랜치 `feat/newsflow-phase5c1`, Draft PR [#11](https://github.com/jsbae1979-prog/JSBAE/pull/11).

판정 표기: **PASS** / **FAIL** / **SKIPPED** / **NOT VERIFIED** / **BLOCKED**. 자동 테스트 성공을 실제 사용자 검증 성공으로 보고하지 않습니다. BLOCKED는 앱의 보수적 정책(robots·policy·OAuth 차단)이 의도대로 막은 것이며 결함이 아닙니다.

## 1. Phase 5C.1 개발 요약

| 패키지 | 항목 | 판정 | 근거와 한계 |
| --- | --- | --- | --- |
| A | 공개 피드 검토 도구 `tools/ci_feed_review.py` · `tools/feed_candidates.json`(22개 후보, 17개 활성) · `/sources` 최근 수집 오류 `[kind]` 표시 (§3) | PASS (Windows 실행 7: 피드 검토 PASS 13 · BLOCKED 3 · NOT VERIFIED 6 · FAIL 0, run.bat 실서버 연결 테스트 조선일보 PASS 기사 100) | 어댑터 정책 무변경. 앱 기본 출처(Google News)는 현행 robots 정책에서 **BLOCKED**. Cloud는 외부 네트워크 없음 → 전부 NOT VERIFIED |
| B | 예상 토큰·예상 비용(사용자 단가) · 예산 검사 `used + 예상 입력 + 출력 상한` · 승인된 단일 실제 호출 `tools/ai_live_check.py` · 토큰 0 연결 확인 · `voice_failed` 코드 (§4) | PASS (구조) · 실제 OpenAI 호출 **NOT VERIFIED** | 단가는 표시용, 게이트는 월 토큰 한도. 유료 호출은 사용자 PC에서 승인 시 1회. Cloud·CI 호출 0건 |
| C | 한국어 음성 레지스트리 감지(`설치됨 · SAPI 미노출`) · 실행 정책 안내 · 읽기 형태 정규화 `video/speech_text.py` · 미리 듣기 원문/읽기 형태 · 청취 결과 기록 · `tools/ci_korean_voice_probe.py` (§5) | PASS (구조) · 실제 한국어 발화 **NOT VERIFIED** | Windows 러너: 한국어 SAPI 음성 0개(레지스트리 sapi 2 · sapi_wow 2 · onecore 3, 한국어 0). 앱은 레지스트리·정책을 바꾸지 않음. 발음 품질은 사람 청취만 |
| D | 사용자 안내서 `docs/user_guide_realcontent.md` · 검증 체크리스트 `docs/windows_user_verification_checklist.md` · README/START_HERE/기존 문서 갱신 · `tools/ci_docs_link_check.py` (§6) | PASS (링크 검사 Windows 125개·Cloud 172개 PASS) · 사용자 PC 수행 **NOT VERIFIED** | 사용자 PC 수행 결과는 체크리스트 §10에 기록 |
| E | Phase 5D Higgsfield 영상 Provider 설계 초안 `docs/design/phase5d_higgsfield_video_provider.md` (§7) | PASS (설계 문서·문서 테스트) | 설계만. Higgsfield API/MCP 호출 0건. vendor 사실 전부 NOT VERIFIED |
| — | 워크플로 `.github/workflows/newsflow-phase5c1-windows.yml` (artifact `newsflow-phase5c1-windows-validation`) (§9) | PASS (최종 실행 7 [38736365785](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38736365785) success) | 신규 단계: 공개 피드 검토 · 한국어 음성 프로브 · 문서 링크 검사 · 수동 dispatch + secret 시에만 토큰 0 연결 확인(이번 실행 SKIPPED). 유료 완성 호출은 CI에서 실행하지 않음 |
| — | Cloud 전체 회귀 (§8) | PASS (1363 passed / 7 skipped / 0 failed, ruff 통과) | 최종 코드 `bcf7322` |
| — | 기존 5A/5B/5C 회귀·보안 보존 (§10) | PASS (Windows 1368 passed / 2 skipped / 0 failed, 5A·5B·5C 도구 전부 PASS) | 정책 완화·검사 제거·테스트 삭제/skip 없음 |
| — | 실제 외부 API 호출·비용 (§14) | 외부 AI 0건 · 비용 0 · 공개 RSS 요청은 Windows CI에서만 | |
| — | CI 도구 결함 2건 발견·수정 (§15) | PASS (실행 7에서 확인) | 실서버 RSS 연결 테스트가 앱이 미리 넣어 둔 Google News를 시험하던 결함(`e0fe5e6`), 5A 브라우저 도구의 작업 화면 이동 경합(`bcf7322`). 제품 코드 변경 없음 |
| — | 사용자 Windows 11 PC 수동 운영·사람의 청취·시청 평가 | NOT VERIFIED | 자동화는 대체하지 않음 ([체크리스트](../windows_user_verification_checklist.md)) |

## 2. 변경 파일

기능·테스트·문서 커밋 6개(A·B·C·D·E·F) + 수정 8개(로그 화이트리스트·링크 경로·검토 결과 코드·검토 결과 문서·실서버 RSS 진단·인터프리터 탐침(다음 커밋에서 제거)·실서버 RSS 도구 수정·작업 화면 이동 경합 수정) + 보고서·증거 1개, 상세는 §16. 신규 모듈: `src/newsflow/intelligence/estimate.py`, `src/newsflow/video/speech_text.py`; 신규 도구: `tools/ci_feed_review.py`, `tools/feed_candidates.json`, `tools/ai_live_check.py`, `tools/ci_korean_voice_probe.py`, `tools/ci_docs_link_check.py`; 신규 테스트 11개 파일(`test_ai_estimate`, `test_ai_live_check_tool`, `test_ci_tools_offline`, `test_collection_errors`, `test_feed_review_tool`, `test_live_ai`(opt-in), `test_phase5d_design_doc`, `test_speech_text`, `test_user_guide_links`, `test_voice_detection`, `test_voice_failed`); 신규 문서 5개(`user_guide_realcontent.md`, `windows_user_verification_checklist.md`, `korean_tts_listening_checklist.md`, `design/phase5d_higgsfield_video_provider.md`, 이 보고서); 워크플로 `newsflow-phase5c1-windows.yml`. 수정: `intelligence/{provider,service,settings}.py`, `news/service.py`, `video/{tts.py,windows_tts.ps1}`, `easy_setup.py`, `autopilot/{backend,service}.py`, GUI 라우트·템플릿(ai_settings·autopilot·intelligence·voices·setup·video·base), CI 도구(`ci_validation`, `ci_realcontent_validation`, `ci_autopilot_validation`), 기존 테스트 5개 파일(`test_easy_setup`·`test_korean_speech`·`test_provider_errors`·`test_video`·`test_voices_gui`, 추가만 하고 삭제한 줄 0), README·START_HERE·docs, `AGENTS.md`, `pyproject.toml`(0.5.1b1). 전체 목록은 [changed-files.txt](phase5c1_evidence/changed-files.txt).

```text
/sources(최근 수집 오류 [kind])   /ai-settings(예상 토큰·단가)   /voices(레지스트리 감지·읽기 형태·청취 기록)
        │                              │                               │
  ci_feed_review ──► PublicRSSAdapter  intelligence/estimate ──► settings.check_budget   video/speech_text ──► WindowsTTS._speak
  (정책 무변경)      Collector/NewsService  (used+prompt+cap)   ai_live_check(1회)        tts.korean_voice_report(읽기 전용)
```

## 3. A · 실제 RSS 검증

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 후보 파일과 검토 도구 | `tools/feed_candidates.json` 22개(17개 활성, `official_rss_page` 대부분 `unknown`, Reuters/AP 제외) · `python tools/ci_feed_review.py --mode windows --output <폴더>` → `feed-review.json`. 런타임 의존성만 사용(사용자 PC 실행 가능) | PASS |
| 정책 무변경 | `rss_adapter.py`·`collector.py`·`dedup.py` 무수정: robots(first-match·fail-closed·Crawl-delay/Request-rate 차단)·SSRF/DNS 고정·TLS·리디렉션 3회·2 MiB·identity 인코딩·엄격 발행시각 | PASS |
| 증거 최소화 | 개수·발행사·링크 도메인·피드당 제목 3개(80자)만, 요약·본문 없음, `terms_confirmed_by_human: false` | PASS |
| 판정 분류 | PASS(연결 테스트 + 수집 2회 연속 성공) / BLOCKED(robots·policy) / NOT VERIFIED(dns·timeout·https·http·parse·empty·예산·사전 점검·비활성) / FAIL(앱 내부 결함) | PASS (오프라인 테스트 32건, 느린 수집은 NOT VERIFIED(client_timeout)로 분류하고 남은 후보를 건너뜀) |
| `/sources` 오류 표시 | `최근 수집 오류: [kind] 고정 메시지`. 고정 메시지 목록 밖의 FeedError 텍스트는 `[kind] RSS 수집 또는 저장에 실패했습니다.`로 가림(기존 `test_gui` 비밀값 미기록 테스트 유지) | PASS |
| Cloud 결과 | DNS 사전 점검 `FAIL(dns)`(외부 네트워크 없음) → 22개 전부 NOT VERIFIED(network_preflight 17 · not_enabled 5), 요청 0건 ([feed-review.json](phase5c1_evidence/cloud/feed-review.json)) | NOT VERIFIED (환경) |
| Windows Actions 결과 | 최종 실행 7: 17개 시도 · **PASS 13 · BLOCKED 3 · NOT VERIFIED 6(비활성 5 + 2 MiB 초과 1) · FAIL 0**, 79초 (아래 표) | PASS |
| run.bat 실서버 연결 테스트 | 최종 실행 7: 앱이 미리 넣어 둔 Google News(번호 1)가 아닌, 도구가 등록한 출처(번호 2)를 시험 → **조선일보 PASS, 기사 100 · 발행시각 100 · 요약 충분 56**. 같은 순간 도구 프로세스의 검사도 PASS(robots.txt 479 B, 해시 `62f17051…`) | PASS |
| 여러 실행의 안정성 | 실행 2·3·4·7 피드 검토: FAIL 0회. 조선일보·BBC 뉴스·한겨레 등 12개는 4회 모두 PASS. UN 뉴스는 PASS 2회, 압축 응답(identity 요청에도 `Content-Encoding`)으로 NOT VERIFIED 2회. GitHub 블로그는 4회 모두 2 MiB 초과 | PASS (기록) |

Windows 실측(최종 실행 7, 피드 검토 시작 2026-10-15 21:50 KST, PASS 피드는 모두 2회 수집 성공·두 번째 수집 신규 0):

| 후보 | 결과 | 기사 | 발행시각 있음 | 비고 |
| --- | --- | --- | --- | --- |
| hani-all, khan-total, mk-headline | PASS | 30 / 50 / 50 | 0 / 0 / 0 | 시간대 없는 발행시각 → 정책대로 '시각 미상' |
| hankyung-all | PASS | 50 | 50 | 제목 유사도로 1건 병합(출처 링크 보존) |
| chosun-all | PASS | 100 | 100 | 1건 병합(저장 99) |
| bbc-korean | PASS | 21 | 21 | |
| nyt-home, guardian-world, npr-news, nasa-news, un-news | PASS | 24 / 45 / 10 / 10 / 30 | 전부 | |
| bbc-news | PASS | 33 | 33 | 1건 중복(저장 32). 실행 2·3·4에서도 PASS |
| dw-en-rdf | PASS | 136 | 0 | RDF `dc:date` → 정책대로 '시각 미상' |
| google-news-kr-top, google-news-kr-business | BLOCKED (robots) | 0 | — | `robots.txt` 200, `*` 그룹 첫 일치 규칙 `Disallow: /` → 현행 Python 3.12 first-match 정책에서 차단. 앱 기본 출처(비활성)는 사용 불가, 정책 미완화 |
| hn-front | BLOCKED (robots) | 0 | — | 대조군. 첫 일치 규칙 `Disallow: /r`, crawl-delay 30 |
| github-blog | NOT VERIFIED (network) | 0 | — | 대조군. `RSS 응답이 최대 2 MiB를 초과했습니다.` (정책) |
| korea-kr-policy, yna-news, donga-total, jtbc-newsflash, etnews-all | NOT VERIFIED (not_enabled) | — | — | 신뢰도 낮음·사람 확인 전 비활성 |

후보의 '공식 여부'와 이용 약관은 사람이 확인하기 전까지 NOT VERIFIED입니다. 기사 본문은 수집하지 않았습니다.

## 4. B · 외부 AI 검증 준비

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 예상 토큰 표시 | `/ai-settings` `#ai-estimate`: `실제 콘텐츠 1건(30초 기준) = 외부 AI 호출 2회 · 예상 최대 약 N 토큰 (입력 약 P + 출력 최대 O) · 이번 달 남은 R 토큰 · 예상 비용 C 또는 단가 미입력` · 시작 화면 `#start-ai-estimate` · 작업 화면 `#ai-estimate`(뉴스 고르기) · `#ai-actual`(대본 후 실제 사용) · AI Studio `#studio-estimate` | PASS (Cloud 스크린샷 [ai-settings.png](phase5c1_evidence/cloud/ai-settings.png): 30초 기준 예상 최대 약 4921 토큰 = 입력 약 1921 + 출력 최대 3000) |
| 추정 방식 | 제공자에게 보내는 문자열(`provider.user_message`)과 동일한 바이트를 기준으로 한글 1.2자/토큰·ASCII 4자/토큰·기타 2자/토큰·안전계수 1.15의 보수적 추정. 실제 호출 후 예상 대비 비율을 증거에 기록 | PASS (구조) · 실측 보정 NOT VERIFIED |
| 출력 상한 | 30초 1400 · 45초 1800 · 60초 2200, 분석 1600 (`Options` 200~3000 범위 안, 기사 1건 최대 분석 응답이 잘리지 않도록 검토 후 900→1600) · 응답이 상한에서 잘리면(`finish_reason: length`) `ai_bad_response`로 중단하고 재시도하지 않음 · Autopilot이 저장된 모델·제한시간 사용 | PASS |
| 예산 검사 | `used + 예상 입력 + 출력 상한 > 한도` → `ai_budget` 호출 전 중단, 메시지에 숫자 포함 | PASS |
| 단가·예상 비용 | AppSetting `ai_price_input_per_1m` / `ai_price_output_per_1m` / `ai_price_currency`(USD/KRW) · 면책 문장 고정 · 단가는 게이트 아님 · 재시작 증거에 포함 · 단가 폼 CSRF 필드 렌더링(검토에서 발견, 테스트가 렌더링된 폼의 필드로 제출) | PASS |
| 게이트 강화 | 제공자 `offline` 저장 시 `ai_consent`, 읽을 수 없는 저장 키 `ai_key_missing`(키 문자열 미노출) | PASS |
| 승인된 단일 호출 도구 | `NEWSFLOW_AI_LIVE_TEST=1` + `tools/ai_live_check.py --article-id <번호> --max-tokens 1400 --output ai-live` → 앱 종료 확인(server·migration 잠금) → 게이트 확인 → 실제 기사 확인(체험 뉴스 거부) → 예상치 요약 → `동의` → 분석은 오프라인, 대본 생성 1회 → `ai-live-check.json`(키·본문·대본 없음) → PASS/FAIL/BLOCKED | PASS (오프라인 테스트 7건: env_flag·gate_closed·article_not_real·budget·not_confirmed·app_running 차단, 호출 1회, 전송 전 거부는 외부 호출 0건, 증거는 환경변수 키와 DPAPI 저장 키 모두 미포함) |
| 토큰 0 연결 확인 | `--connection-check --model gpt-4o-mini` (`NEWSFLOW_AI_API_KEY` 환경변수) · CI는 수동 dispatch + secret 시에만 단일 단계에 secret 매핑, 그 외 SKIPPED 기록 | PASS (Windows 실행에서 SKIPPED 기록) |
| opt-in pytest | `tests/test_live_ai.py` 기본 SKIPPED (Cloud 7 skipped·Windows 2 skipped에 포함) | PASS |
| `voice_failed` 코드 | 렌더러 실패 접두사 `음성 생성 실패`→`voice_failed`, `음성 길이 실패`→`speech_too_long`(기존에는 모든 렌더 실패가 `speech_too_long`으로 표시되던 문제 수정) · 해결 안내·`음성 설정 →` 링크 | PASS |
| 실제 OpenAI 호출 | Cloud·CI 0건(키 없음, 게이트 닫힘). 사용자 PC 승인 호출은 체크리스트 §4.6 | NOT VERIFIED |

## 5. C · 한국어 TTS 검증 준비

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 설치 안내 문장 통일 | `Windows 설정 → 시간 및 언어 → 언어 및 지역 → 한국어 → 언어 옵션에서 음성(텍스트 음성 변환)을 설치한 뒤 NewsFlow를 종료하고 run.bat를 다시 실행하세요.` (voices·마법사 5단계·진단·START_HERE) | PASS |
| 상태 감지 | `설치됨` / `없음` / `확인 불가` / `설치됨 · SAPI 미노출`: `-RegistryVoices`(읽기 전용 Get-ItemProperty, HKLM SAPI·WOW6432Node·HKCU·Speech_OneCore, ≤200개, LCID 0x412) → `korean_voice_report()`; 레지스트리 실패는 SAPI 기준 상태를 바꾸지 않음; 선택·저장은 SAPI 목록만 허용 | PASS (오프라인 테스트) · Windows 러너: SAPI 2 · WOW 2 · OneCore 3, 한국어 0 → `not_installed` |
| 실행 정책 안내 | rc≠0일 때만 stderr에서 `UnauthorizedAccess`/`running scripts is disabled` 분류 → `TTSPolicyError`·`#voice-policy-guide`; stderr는 저장·표시하지 않음; `-ExecutionPolicy Bypass` 추가 없음 | PASS |
| 읽기 형태 정규화 | `video/speech_text.py`: NFKC·점 약어·날짜·일시·시각·%·통화·단위·큰 수(만/억/조)·범위·영문 약어(발음형 예외) · `WindowsTTS._speak` 한 곳에만 적용(원문 400자 검사 유지, 변환 후 1000자 상한) · 자막·대본·예상 길이·검토 사항 불변 | PASS (규칙별 테스트, 멱등성·한글 보존) |
| 미리 듣기 | 원문·읽기 형태 표시, 고정 문장 `안녕하세요. 뉴스플로 음성 미리 듣기입니다. 2026-10-15 14:30 기준 KOSPI는 3.5% 올랐고, AI 기업 매출은 $1,250,000입니다.` → `2026년 10월 15일 14시 30분 기준 코스피는 3.5퍼센트 올랐고, 에이아이 기업 매출은 125만 달러입니다.`, 상한 30초 | PASS ([voices.png](phase5c1_evidence/cloud/voices.png)) |
| 장면 내레이션만 발화 | hook/summary/closing 미발화(문서에 명시) | PASS |
| 청취 결과 기록 | `POST /voices/listening` → `voice-listening/listening-<id>.json`(최근 50건) + AppSetting `voice_listening_last` · `사람 청취 결과: PASS/FAIL/NOT VERIFIED` · 청취자 없음·항목 누락·부정확 항목 있는 PASS는 422 · 자동화는 PASS를 쓰지 않음 | PASS (GUI 테스트) |
| CI 프로브 | `tools/ci_korean_voice_probe.py`: 음성 목록·레지스트리 hive 수·한국어 이름·속도(-3/0/+3)·쉼(0/600)별 길이·숫자/날짜/영문 샘플 WAV, 비Windows는 NOT VERIFIED, 비한국어 음성 미사용, 품질 판정 없음 | PASS (Windows: 한국어 음성 0 → NOT VERIFIED) |
| 실제 한국어 발화·발음 | Windows 러너 한국어 음성 0개 · 사용자 PC 청취(체크리스트 §5, 청취 확인표) | NOT VERIFIED |

## 6. D · Windows 사용자 검증 절차

| 산출물 | 내용 | 판정 |
| --- | --- | --- |
| [사용자 안내서](../user_guide_realcontent.md) | 설치·실행·7단계·RSS·외부 AI·음성·제작·대본 검토·보관·데이터 위치·복구·하지 않는 일(13개 절, BAT 콘솔 메시지 원문 인용) | PASS (작성) |
| [검증 체크리스트](../windows_user_verification_checklist.md) | §0–§11, 기본 NOT VERIFIED, 30/45/60 MP4 표(영상·음성·자막·출처·대기함), 증거 제출 안내 | PASS (작성) |
| [청취 확인표](../korean_tts_listening_checklist.md) | 사람 청취 항목 8개·종합 판정, 자동 PASS 금지 | PASS (작성) |
| README · START_HERE · autopilot.md · realcontent.md · architecture.md · windows_user_checklist.md · windows_validation.md | Phase 5C.1 반영, 오래된 문장(브랜치·0001~0009·키 안내) 수정, 'BBC 불안정' 문장을 실측(매번 PASS)으로 정정, 체크리스트의 robots 차단 예시를 Google News로 교체, 상단 pill `PHASE 5C.1` | PASS |
| 문서 링크 검사 | `tools/ci_docs_link_check.py` · `tests/test_user_guide_links.py`: 상대 링크·앵커·https만. Cloud 172개 PASS(이 보고서의 증거 링크 포함), Windows 125개 PASS | PASS |
| 사용자 PC 수행 결과 | 체크리스트 §10 표 — 이번 단계에서 받은 행 없음 | NOT VERIFIED |

## 7. E · Phase 5D 설계

| 항목 | 내용 | 판정 |
| --- | --- | --- |
| 설계 문서 | [docs/design/phase5d_higgsfield_video_provider.md](../design/phase5d_higgsfield_video_provider.md) 16개 절: `VideoProvider` Protocol(Fake/Higgsfield), 장면별 B-roll 제출·폴링·bounded 다운로드·ffprobe 검증·Pillow 오버레이·상수 FFmpeg 필터·카드 대체, 승인·월 한도·DPAPI 키·체험 금지·작업별 비용 확인 게이트, 비동기 상태 기계, 예약 migration 0010, 테스트 계획, vendor 확인 목록 | PASS |
| 구현 여부 | 구현 없음. FFmpeg 카드 제작 기본 유지 | PASS |
| 외부 호출 | Higgsfield API/MCP 호출 0건 (catalog/balance 조회 포함) | PASS |
| vendor 사실 | 엔드포인트·상태·모델·가격·약관 전부 NOT VERIFIED (문서 표 16행) | NOT VERIFIED |
| 문서 테스트 | `tests/test_phase5d_design_doc.py` 26건 | PASS |

## 8. Cloud 전체 테스트 결과

최종 코드 `bcf7322`에서 `python -m pytest -q -rs` (Python 3.12.3, Linux, `NEWSFLOW_FONT_PATH`=핀 고정 Noto Sans KR): **1363 passed / 7 skipped / 0 failed** ([cloud-pytest.txt](phase5c1_evidence/cloud-pytest.txt), [cloud-pytest.xml](phase5c1_evidence/cloud-pytest.xml)). 같은 파일에 `ruff check src tests tools` 통과 기록. skipped 7 = opt-in live RSS 1 + opt-in live AI 1 + Windows 전용 DPAPI/소켓 5. 경고 1건은 기존 서드파티 `starlette.testclient` 사용 중단 안내입니다.

같은 명령을 글꼴 경로 없이 먼저 실행했을 때 기존 테스트 `test_easy_setup::test_korean_subtitles_wrap_and_overflow_is_rejected` 1건이 `한국어 글꼴을 찾지 못했습니다`로 실패했습니다. Cloud Linux에 한국어 글꼴이 없어서이며, 앱의 의도된 안전 동작입니다. 이전 Cloud 실행과 Windows 워크플로처럼 핀 고정 글꼴을 지정해 다시 실행한 결과가 위 숫자입니다. 코드는 바꾸지 않았습니다.

기준(5C HEAD `ca28121`) 995 passed / 6 skipped → 이번 단계 테스트 항목 369개 추가(신규 테스트 파일 11개, 기존 5개 파일은 추가만). 기존 테스트 삭제·skip 없음.

Cloud 도구 실행(결과는 `phase5c1_evidence/cloud/`; 제품 코드는 `62e912d` 이후 바뀌지 않았고 이후 커밋은 CI 도구·테스트·문서만 바꿨습니다):

| 도구 | 판정 | 요약 |
| --- | --- | --- |
| `ci_realcontent_validation --mode cloud` | PASS (NOT VERIFIED 항목 명시) | 출처 등록·연결 테스트 기사 3·수집, AI 승인은 한도 필수 422, 음성 설치 안내, `closing` 수정 revision 2, 실제 콘텐츠 30/45/60 대본 확인→최종 확인→대기함, 재시작 보존, 외부 요청 0·JS 오류 0, 외부 AI 0회 ([realcontent-result.json](phase5c1_evidence/cloud/realcontent-result.json)). Chromium H.264 미지원으로 브라우저 재생은 NOT VERIFIED |
| `ci_video_validation` | PASS | 3초 H.264/AAC 1080×1920, 한국어 자막 래스터 ([video-result.json](phase5c1_evidence/cloud/video-result.json)) |
| `ci_feed_review --mode cloud` | NOT VERIFIED (환경) | DNS 사전 점검 실패, 22개 NOT VERIFIED, 요청 0건 ([feed-review.json](phase5c1_evidence/cloud/feed-review.json)) |
| `ci_korean_voice_probe` | NOT VERIFIED (비Windows) | 읽기 형태 `2026년 10월 15일, 에이아이 기술로 … 125만 달러였습니다.` 확인 ([voice-probe.json](phase5c1_evidence/cloud/voice-probe.json)) |
| `ci_docs_link_check` | PASS | 172개, 깨진 링크 0 (이 보고서의 증거 링크 포함) ([docs-links.json](phase5c1_evidence/cloud/docs-links.json)) |
| `ci_easysetup_validation --mode cloud` | NOT VERIFIED (환경) | 검토 전 코드에서 마법사 7단계·설정 오류·레이아웃까지 진행 후 MP4 재생 대기에서 35분간 멈춰 중단. Chromium H.264 제약이며 Windows 실행에서 PASS |
| 5A `ci_autopilot_validation`·`ci_validation` Cloud 모드 | NOT VERIFIED (환경) | 같은 H.264 제약(video error 4, `canPlayType` 빈 값)으로 재생 단계에서 중단. `bcf7322`에서 다시 실행해 작업 화면 이동 2회가 통과한 뒤 같은 재생 단계에서 멈추는 것을 확인. Windows 실행이 기준 ([autopilot-result-chromium-h264.json](phase5c1_evidence/cloud/autopilot-result-chromium-h264.json), [legacy-result-chromium-h264.json](phase5c1_evidence/cloud/legacy-result-chromium-h264.json)) |

## 9. Windows 전체 테스트 결과

워크플로 `newsflow-phase5c1-windows.yml`. **최종 실행 7 [38736365785](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38736365785)** (커밋 `bcf7322`, windows-latest 2025Server, Python 3.12.10, Google Chrome, FFmpeg 7.1.1, 2026-10-15 21:39~21:52 KST): **success**, 12분 28초. 증거: [windows-actions-evidence.json](phase5c1_evidence/windows/windows-actions-evidence.json) (check annotation 사본 40건). artifact `newsflow-phase5c1-windows-validation`(id 11974018726, 7,464,634 B, sha256 `6ab6a2cc…`, 2026-10-22 21:52 KST 만료). 아티팩트 ZIP은 Cloud 프록시가 Azure blob 호스트를 거부(403)해 내려받지 못했습니다 — [github-access.json](phase5c1_evidence/github-access.json).

| 단계 | 판정 | 요약 |
| --- | --- | --- |
| `pytest -q -rs` | PASS | **1368 passed / 2 skipped(opt-in live RSS·live AI) / 0 failed** (1370개) |
| 실제 짧은 MP4·ffprobe·로컬 TTS | PASS | 무음 3초 MP4, 설치된 영어 SAPI 음성 → WAV → MP4, 한국어 자막 래스터 |
| Windows DPAPI 합성 vault·production vault | PASS | 실제 current-user DPAPI, 합성 자료만 |
| 실제 BAT·재시작·OAuth GUI 차단 | PASS | run.bat, 포트 충돌, Chrome POST, OAuth 위조 시작 차단, `OFFLINE/BLOCKED` |
| Easy UI(5A) | PASS | easy-30s `2d9cbc73…`·guided-30s `c1c207e8…` Chrome 재생, 재시작 보존, 취소, 320px·200% 레이아웃 |
| 초기 설정(5B) | PASS | setup.bat 2회, 마법사 7단계, setup-30s `3699803a…`·45s `c1dd0abd…`·60s `f4696717…` 재생 |
| 실제 콘텐츠 흐름(5C) | PASS | 대본 확인→최종 확인→대기함 30/45/60, real-30s `443d93b3…`·45s `10cbbd49…`·60s `208c0ce0…` 재생, 재시작 보존, 외부 요청 0, JS 오류 0, DB: 실제 작업 3건 `real/offline/completed`, `ai_usage` 0, `ai_price_settings` {} |
| **run.bat 실서버 공개 RSS 연결 테스트** (`--live-rss` 조선일보) | **PASS** | 도구가 등록한 출처(번호 2) 시험, 기사 100 · 발행시각 100 · 요약 충분 56. 연결 테스트는 기사를 저장하지 않음 |
| **공개 피드 검토** (`feed-review.json`) | PASS | 17개 시도 · PASS 13 · BLOCKED 3 · NOT VERIFIED 6 · FAIL 0, 79초, DNS 사전 점검 OK |
| **한국어 음성 프로브** (`voice/`) | NOT VERIFIED | 한국어 SAPI 음성 0개(`not_installed`), 레지스트리 sapi 2·sapi_wow 2·onecore 3·한국어 0, 샘플 WAV 없음, 읽기 형태 `2026년 10월 15일, 에이아이 기술로 … 125만 달러였습니다.` 확인 |
| **문서 링크 검사** (`docs/docs-links.json`) | PASS | 125개, 깨진 링크 0, http 외부 링크 0 |
| 토큰 0 OpenAI 연결 확인 | SKIPPED | 수동 dispatch·secret 없음(`NEWSFLOW_AI_KEY_PRESENT: false`), `ai-live-check.json`에 SKIPPED 기록 |
| 한국어 SAPI 발화 품질 | NOT VERIFIED | 러너는 사람이 듣지 않음 |

실행 이력(모두 2026-10-15 KST):

| 실행 | 커밋 | 결과 | 내용 |
| --- | --- | --- | --- |
| 1 [38717489264](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38717489264) | `9b1f80a` | FAIL | 신규 단위 테스트 `test_docs_link_check_detects_missing_targets_and_anchors`가 Windows 경로 구분자(`docs\guide.md`)로 실패(1327 passed / 1 failed). 도구가 POSIX 상대 경로를 보고하도록 수정(`a42d937`) |
| 2 [38718358049](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38718358049) | `a42d937` | success | 1328/2/0. 피드 검토 PASS 13. 실서버 연결 테스트는 robots 차단으로 기록(아래 도구 결함) — [증거](phase5c1_evidence/windows/windows-actions-evidence-run2.json) |
| 3 [38727688507](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38727688507) | `3fd4247` | success | 검토 결과 반영 후 1363/2/0. 피드 검토 PASS 12(UN 뉴스 압축 응답). 실서버 연결 테스트 robots 차단 — [증거](phase5c1_evidence/windows/windows-actions-evidence-run3.json) |
| 4 [38730720236](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38730720236) | `8c3cd45` | success | 진단 추가: 도구 프로세스 검사는 실서버 테스트 전후 PASS, 실서버 재시험만 robots 차단 → 원인 추적의 단서 — [증거](phase5c1_evidence/windows/windows-actions-evidence-run4.json) |
| 5 [38733446214](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38733446214) | `ec26360` | cancelled | 원인을 코드에서 찾아 수정 커밋을 올리면서 워크플로 동시 실행 설정으로 취소 |
| 6 [38734161182](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38734161182) | `e0fe5e6` | FAIL | pytest·BAT 단계 PASS 후 5A 브라우저 단계 실패: 실행 중인 작업 화면이 스스로 새로고침하면서 Playwright 이동을 세 번 모두 중단. 도구가 `about:blank`로 먼저 나간 뒤 이동하도록 수정(`bcf7322`) — [증거](phase5c1_evidence/windows/windows-run6-failure.json) |
| 7 [38736365785](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38736365785) | `bcf7322` | **success** | 최종. 위 표 |

모든 실패는 CI 도구 결함이었고 제품 기능·보안 검사·기존 테스트는 바꾸지 않았습니다. 테스트를 건너뛰거나 지우지 않았습니다.

## 10. 기존 Phase 5A/5B/5C 회귀

Windows 실행의 5A(간편·단계별 30초 MP4, 320px·200% 레이아웃, 취소·재시작), 5B(setup.bat 2회·7단계·30/45/60초 MP4), 5C(출처 등록·연결 테스트·수집·AI 승인 422·음성 안내·`closing` 수정·실제 콘텐츠 30/45/60·재시작 보존·DB 불변식) 단계가 최종 실행 7에서 모두 PASS이며 MP4 SHA256(easy-30s `2d9cbc73…`, guided-30s `c1c207e8…`, real-30s/45s/60s)은 Phase 5C 최종 실행과 동일합니다. OAuth 안전 상태 `OFFLINE/BLOCKED`, 실제 토큰·게시 호출 0. 정책 완화·검사 제거·테스트 삭제/skip 없음(§8). Cloud 5A/5B 브라우저 도구는 Chromium H.264 제약으로 NOT VERIFIED(환경).

## 11. 데이터베이스 마이그레이션 및 재시작 보존

- **Migration head `0009` 유지, 새 마이그레이션 없음.** Phase 5C.1 상태는 AppSetting 키만 추가합니다: `ai_price_input_per_1m`, `ai_price_output_per_1m`, `ai_price_currency`, `voice_listening_last`. 청취 기록 본문은 `voice-listening/*.json` 파일입니다.
- 재시작 보존: Cloud·Windows 실제 콘텐츠 검증에서 재시작 전후 `autopilot_jobs`·`content_drafts`·`news_source_checks`·`ai_usage`·`ai_price_settings` 동일 → PASS. 단가·청취 기록의 재시작 보존은 단위 테스트(새 `create_app`으로 재읽기)로 PASS.
- `migrate_data` 0009 지원 유지(테스트 동일).

## 12. API 비용·승인·실패 처리

- 게이트: 제공자 openai + 날짜 있는 승인 + 월 토큰 한도(>0, 미소진) + 키. 실행 시점마다 재평가. 체험 제작 외부 AI 금지.
- 예산: `used + 예상 입력 + 출력 상한`. 단가는 표시용이며 호출을 막지 않음.
- 실패 코드: `ai_consent` · `ai_budget` · `ai_key_missing` · `ai_auth_failed` · `ai_rate_limited`(Retry-After ≤15초 1회) · `ai_timeout`(재시도 없음) · `ai_unavailable`(1회) · `ai_bad_response` · `ai_not_ready`; 음성 `voice_unavailable` · `speech_too_long` · `voice_failed`. 모두 오프라인 테스트로 PASS.
- 승인된 단일 호출: 사용자 PC에서만, `동의` 입력, 1회. 이번 단계 수행 결과: **SKIPPED**(키·승인 환경 없음). 사용자 PC 수행 시 `ai-live-check.json`의 사용 토큰·예상 대비 비율을 체크리스트 §4.6에 기록합니다.

## 13. GUI 및 영상 제작 흐름

Cloud Chromium 스크린샷(`phase5c1_evidence/cloud/`): `ai-settings.png`(예상 토큰·단가 폼·면책), `voices.png`(읽기 형태·청취 결과 기록), `sources-tested.png`·`sources-collected.png`, `real-script-review.png`·`real-final-review.png`, `queue.png`. 기본 메뉴 6개 유지, 실제 콘텐츠의 대본·최종 영상 필수 멈춤 유지, 외부 요청 0건·JS 오류 0건. 스크린샷은 `3fd4247`에서 다시 찍었고 상단 pill은 `PHASE 5C.1`입니다. 그 뒤 커밋은 CI 도구·테스트·문서만 바꿔 화면은 최종 코드와 같습니다. 시청 품질·사용성 평가는 NOT VERIFIED.

## 14. 실제 외부 API 호출 여부와 비용

- 외부 AI API: Cloud 0건 · Windows CI 0건(연결 확인 단계 SKIPPED) · 사용자 PC 승인 호출 0건. 비용 0.
- 공개 RSS: Windows CI에서만 요청했습니다. 실행마다 피드 검토가 활성 후보 17개에 robots.txt와 피드를 요청했고 PASS 피드는 2회 수집했습니다(실행 2·3·4·7). 실서버 연결 테스트는 실행 2·3·4에서 결함 때문에 Google News robots.txt만 요청했고, 실행 4는 진단으로 조선일보를 3번 더 확인했습니다. 실행 7은 조선일보를 실서버로 1번, 도구 프로세스로 1번 확인했습니다. 기사 본문 0, 요약은 임시 검토 DB에만 있고 증거에 넣지 않았습니다. Cloud에서는 요청 0건입니다.
- OAuth·SNS 호출 0건. **Higgsfield API/MCP 호출 0건.**

## 15. 미구현·미검증 사항과 설계 조정

- **NOT VERIFIED**: 실제 OpenAI 호출 결과·추정 보정 비율, 공개 피드 후보의 공식 여부·이용 약관(`terms_confirmed_by_human: false`), 사용자 PC 네트워크에서의 수집, 한국어 SAPI 발화·발음 품질, 특정 음성 이름(예: "Microsoft Heami Desktop")·Windows 11 24H2 동작, MP4 시청 품질, 사용자 Windows 11 PC 수동 운영(체크리스트 §10 전체), Phase 5D vendor 사실 전부, Cloud Chromium H.264 재생.
- **BLOCKED(정책)**: 앱 기본 출처 Google News 한국 RSS와 Hacker News는 현행 robots 정책에서 수집 불가. 정책을 완화하지 않았으며, 안내서는 PASS 목록의 출처를 권합니다.
- **미구현(범위 밖)**: 실제 SNS 게시·OAuth 활성화·예약 스케줄러·무인 운영·기사 본문 수집·외부 유료 TTS·Higgsfield 호출·요금 결제/보증·Korean 음성 자동 설치.
- **설계 조정**: ① 예상 비용은 vendor 요금표 대신 사용자 입력 단가로만 계산하고 표시 전용으로 두었습니다(게이트는 월 토큰 한도). ② Autopilot의 외부 호출 2회(분석+대본)는 유지하고 '호출 2회'로 표시했습니다(1회로 줄이는 변경은 다음 단계 제안). ③ 청취 기록은 마이그레이션 대신 JSON 파일과 200자 요약 설정으로 저장했습니다. ④ CI의 AI 단계는 토큰 0 연결 확인만, 그것도 수동 dispatch + 저장소 secret에서만 실행되도록 했고 유료 완성 호출은 사용자 PC 도구에만 두었습니다. ⑤ 수집 오류 로그는 `[kind]` 접두사를 붙이되 고정 메시지 목록 밖의 텍스트는 계속 가립니다(기존 비밀값 미기록 테스트 유지).
- **적대적 검토와 조치**: 통합 후 다중 에이전트 검토를 실행했습니다. 검증 에이전트 단계는 실행 자원 부족으로 끝나지 않아, 보고된 지적을 코드로 직접 재현·확인해 분류했습니다. 확인된 지적은 모두 `62e912d`(코드·테스트)와 `3fd4247`(문서)에서 수정했습니다.
  - 단가 폼에 CSRF 필드가 없어 브라우저 저장이 403으로 실패 → 필드 렌더링, 렌더링된 폼으로 제출하는 테스트 추가.
  - 출력 상한에서 잘린 유료 응답이 정상 응답처럼 처리될 수 있음 → `finish_reason: length`를 `ai_bad_response`로 중단, 분석 상한 900→1600.
  - 작업 화면 사용량이 재시도 후 마지막 실행만 합산 → 작업의 모든 분석·대본 실행을 합산(재시도 3회 210 토큰 테스트).
  - `ai_live_check` 증거 검사가 환경변수 키만 대조, 전송 전 거부도 외부 호출 1회로 기록 → DPAPI 저장 키도 대조, 전송 전 거부는 0회.
  - 읽기 형태 정규화가 0으로 시작하는 숫자(종목 코드·전화번호·우편번호)를 큰 수로 읽고, `$100만`을 잘못 읽음 → 원문 유지·`100만 달러`, KIA·KAIST·POSCO·MERS·AIDS·SARS·K-POP 단어 읽기.
  - 청취 기록 PASS 규칙이 체크리스트와 달랐고 이름에 요약 구분자를 허용 → 모든 항목 `정확`일 때만 PASS, 구분자 거부.
  - 느린 수집이 다음 후보를 연쇄 `CollectionBusy`로 만듦 → `client_timeout` NOT VERIFIED·남은 후보 건너뜀, 실서버 증거는 서버 행을 최대 90초 대기.
  - 문서: Google News BLOCKED 반영(이때 함께 적은 'BBC 불안정'은 아래 도구 결함 1 때문이었고 `e0fe5e6`에서 정정), venv 명령 경로, `Read-Host` 키 입력 예, 음성 목록 범위, 청취 PASS 규칙, 분석 상한, Phase 5D 시작 폼 설명.
- **CI 도구 결함 1 · 실서버 RSS 연결 테스트(발견·수정)**: Windows 실행 2·3에서 run.bat 실서버 연결 테스트(`--live-rss`)는 robots 차단이었는데, 1분 뒤 피드 검토는 같은 피드(BBC 뉴스, 조선일보)를 PASS로 판정했습니다. 실행 4에 진단을 추가했더니 같은 프로세스의 검사는 실서버 테스트 전후 모두 PASS(robots.txt 479 B, 같은 해시, 허용)였고 실서버 재시험만 다시 robots 차단이었습니다(`8c3cd45`). 원인은 제품이 아니라 CI 도구였습니다. 앱은 첫 실행 때 사용 안 함 상태의 `Google News · 한국` 출처를 넣어 두는데, 도구가 `/sources`에서 **첫 번째** 연결 테스트 폼과 **첫 번째** 결과 행을 읽어 Google News(robots `Disallow: /`)를 시험하고 있었습니다. Phase 5C의 같은 단계(BBC robots 차단)도 같은 원인입니다. 도구가 자신이 등록한 출처의 번호로 시험·조회하도록 고치고 두 출처를 넣은 회귀 테스트를 추가했습니다(`e0fe5e6`). 잘못된 가설(인터프리터 차이)을 확인하려고 넣었던 탐침은 제거했습니다(`ec26360` → `e0fe5e6`). 앱의 robots·SSRF·TLS 정책과 제품 코드는 바꾸지 않았습니다. 'BBC 불안정'이라고 적었던 README·안내서·후보 파일·체크리스트 문장도 바로잡았습니다. 최종 실행 7에서 실서버 연결 테스트는 조선일보 PASS(기사 100)입니다.
- **CI 도구 결함 2 · 5A 브라우저 도구의 작업 화면 이동 경합(발견·수정)**: 실행 6에서 실행 중인 작업 화면이 1.5초마다 상태를 확인하다 바뀌면 스스로 새로고침하는데, 그 새로고침이 Playwright의 같은 주소 이동을 재시도 세 번 모두 중단시켰습니다. 기존 재시도로는 막을 수 없는 경합이었습니다. `open_job`이 `about:blank`로 먼저 나가 기존 문서와 타이머를 없앤 뒤 이동하도록 고치고 오프라인 테스트를 추가했습니다(`bcf7322`). 제품 화면 코드는 바꾸지 않았습니다.
  - **유지한 결정**: Phase 5C.1 워크플로의 `paths` 필터는 `docs/**`를 포함하지 않습니다. 보고서·증거만 바꾸는 커밋이 Windows 실행을 다시 시작하지 않도록 한 기존 단계의 관례이며, 문서 링크는 Cloud 전체 pytest(`test_user_guide_links`)와 Windows 실행의 링크 검사 단계가 검사합니다.

## 16. Draft PR·최종 SHA·Windows Actions URL

- Draft PR: [jsbae1979-prog/JSBAE#11](https://github.com/jsbae1979-prog/JSBAE/pull/11) (head `feat/newsflow-phase5c1` → base `feat/newsflow-phase5c`).
- 커밋: A `0af5fc9` · B `db578b4` · E `f9603e6` · F `88c5723` · C `3271661` · 로그 화이트리스트 수정 `cf84b80` · D `9b1f80a` · 링크 검사 경로 수정 `a42d937` · 검토 결과 코드 수정 `62e912d` · 검토 결과 문서 수정 `3fd4247` · 실서버 RSS 진단 `8c3cd45` · 인터프리터 탐침(다음 커밋에서 제거) `ec26360` · 실서버 RSS 연결 테스트 도구 수정 `e0fe5e6` · 5A 브라우저 도구 작업 화면 이동 경합 수정 `bcf7322`.
- **최종 검증 SHA `bcf7322955afdc29ee263eb3e5f89cf9a2184202`**, Windows 실행 7 [38736365785](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38736365785) **success**. 이후 커밋은 보고서·증거만 추가하며 워크플로 `paths` 필터에 해당하지 않아 Windows 실행을 다시 시작하지 않습니다.
- 기존 PR #1~#10과 `main`은 변경하지 않음. 커밋 재작성·강제 푸시 없음.

## 17. 증거 목록

| 증거 | 위치 | 비고 |
| --- | --- | --- |
| Cloud pytest·ruff 결과 | [cloud-pytest.txt](phase5c1_evidence/cloud-pytest.txt), [cloud-pytest.xml](phase5c1_evidence/cloud-pytest.xml) | `bcf7322`, 1363 / 7 / 0, ruff 통과 |
| Cloud 공개 피드 검토 | [cloud/feed-review.json](phase5c1_evidence/cloud/feed-review.json) | 전부 NOT VERIFIED(네트워크) |
| Cloud 문서 링크 검사 | [cloud/docs-links.json](phase5c1_evidence/cloud/docs-links.json) | 172개 PASS |
| Cloud 실제 콘텐츠 검증 | [cloud/realcontent-result.json](phase5c1_evidence/cloud/realcontent-result.json), 스크린샷 7장, `real-30s/45s/60s.mp4` | 재생은 NOT VERIFIED(Chromium) |
| Cloud 영상 도구·음성 프로브·5A 도구 | [video-result.json](phase5c1_evidence/cloud/video-result.json), [voice-probe.json](phase5c1_evidence/cloud/voice-probe.json), [autopilot-result-chromium-h264.json](phase5c1_evidence/cloud/autopilot-result-chromium-h264.json), [legacy-result-chromium-h264.json](phase5c1_evidence/cloud/legacy-result-chromium-h264.json) | 음성 프로브 NOT VERIFIED(비Windows); 5A·5B 도구는 H.264 제약으로 중단 |
| Windows 최종 실행 annotation 사본 | [windows/windows-actions-evidence.json](phase5c1_evidence/windows/windows-actions-evidence.json) | 실행 7, 40건 |
| Windows 이전 실행 | [run2](phase5c1_evidence/windows/windows-actions-evidence-run2.json), [run3](phase5c1_evidence/windows/windows-actions-evidence-run3.json), [run4](phase5c1_evidence/windows/windows-actions-evidence-run4.json), [run6 실패](phase5c1_evidence/windows/windows-run6-failure.json) | 피드별 결과 목록 포함 |
| Windows 아티팩트 접근 | [github-access.json](phase5c1_evidence/github-access.json) | ZIP 다운로드 BLOCKED(프록시) |
| 변경 파일 목록 | [changed-files.txt](phase5c1_evidence/changed-files.txt) | `git diff --name-status ca28121..bcf7322` |
| 사용자 PC 체크리스트 §10 | — | 받은 행 없음 → NOT VERIFIED |
| manifest.sha256 | `phase5c1_evidence/manifest.sha256` | 증거 파일 해시 |
