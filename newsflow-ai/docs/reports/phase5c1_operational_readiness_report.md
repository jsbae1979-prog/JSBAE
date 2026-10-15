# NewsFlow AI — Phase 5C.1 운영 준비도 완료 보고서

확인일: 2026-10-15 (UTC). 운영 대상 Windows 11 / Python 3.12. 기본 주소 `http://127.0.0.1:8765`, 사용자 데이터 `%LOCALAPPDATA%\NewsFlowAI`. 개발 담당: Claude Code (패키지 A–E 병렬, 통합자 최종 기입). 기준 브랜치 `feat/newsflow-phase5c` @ `ca2812150380012e1bd6867ae5eea3ae0155d487`, 작업 브랜치 `feat/newsflow-phase5c1`, Draft PR (PR 번호 추후).

판정 표기: **PASS** / **FAIL** / **SKIPPED** / **NOT VERIFIED** / **BLOCKED**. 자동 테스트 성공을 실제 사용자 검증 성공으로 보고하지 않습니다. BLOCKED는 앱의 보수적 정책(robots·policy·OAuth 차단)이 의도대로 막은 것이며 결함이 아닙니다. 이 문서의 `(채움 예정)` 셀은 통합자가 Cloud·Windows Actions·사용자 PC 결과로 채웁니다.

## 1. Phase 5C.1 개발 요약

| 패키지 | 항목 | 판정 | 근거와 한계 |
| --- | --- | --- | --- |
| A | 공개 피드 검토 도구 `tools/ci_feed_review.py` · `tools/feed_candidates.json`(22개 후보, 17개 활성) · `/sources` 최근 수집 오류 `[kind]` 표시 (§3) | (채움 예정) | 앱 어댑터 정책 무변경. BBC는 BLOCKED(robots), HN은 BLOCKED(crawl-delay) 예상. Cloud는 외부 네트워크 없음 → 전부 NOT VERIFIED가 정상 |
| B | 예상 토큰·예상 비용(사용자 단가) · 예산 검사 `used + 예상 입력 + 출력 상한` · 승인된 단일 실제 호출 `tools/ai_live_check.py` · 토큰 0 연결 확인 · `voice_failed` 코드 (§4) | (채움 예정) | 단가는 표시용, 게이트는 월 토큰 한도. 유료 호출은 사용자 PC에서 승인 시 1회 |
| C | 한국어 음성 레지스트리 감지(`설치됨 · SAPI 미노출`) · 실행 정책 안내 · 읽기 형태 정규화 `video/speech_text.py` · 미리 듣기 원문/읽기 형태 · 청취 결과 기록 · `tools/ci_korean_voice_probe.py` (§5) | (채움 예정) | 앱은 레지스트리·정책을 바꾸지 않음. 발음 품질은 사람 청취만, 자동화는 PASS를 쓰지 않음 |
| D | 사용자 안내서 `docs/user_guide_realcontent.md` · 검증 체크리스트 `docs/windows_user_verification_checklist.md` · README/START_HERE/기존 문서 갱신 · `tools/ci_docs_link_check.py` (§6) | (채움 예정) | 링크 검사는 오프라인(상대 링크·앵커·https만). 사용자 PC 수행 결과는 체크리스트 §10에 기록 |
| E | Phase 5D Higgsfield 영상 Provider 설계 초안 `docs/design/phase5d_higgsfield_video_provider.md` (§7) | (채움 예정) | 설계만. Higgsfield API/MCP 호출 0건. vendor 사실 전부 NOT VERIFIED |
| — | 워크플로 `.github/workflows/newsflow-phase5c1-windows.yml` (artifact `newsflow-phase5c1-windows-validation`) (§9) | (채움 예정) | 신규 단계: 공개 피드 검토 · 한국어 음성 프로브 · 문서 링크 검사 · 수동 dispatch + secret 시에만 토큰 0 연결 확인. 유료 완성 호출은 CI에서 실행하지 않음 |
| — | Cloud 전체 회귀 (§8) | (채움 예정) | |
| — | 기존 5A/5B/5C 회귀·보안 보존 (§10) | (채움 예정) | 정책 완화·검사 제거 없음 |
| — | 실제 외부 API 호출·비용 (§14) | (채움 예정) | |
| — | 사용자 Windows 11 PC 수동 운영·사람의 청취·시청 평가 | NOT VERIFIED | 자동화는 대체하지 않음 ([체크리스트](../windows_user_verification_checklist.md)) |

## 2. 변경 파일

(채움 예정 — `git diff --stat ca28121...HEAD`, 신규/수정 모듈 목록. 기대 신규: `src/newsflow/intelligence/estimate.py`, `src/newsflow/video/speech_text.py`, `tools/ci_feed_review.py`, `tools/feed_candidates.json`, `tools/ai_live_check.py`, `tools/ci_korean_voice_probe.py`, `tools/ci_docs_link_check.py`, `tests/test_ai_estimate.py`, `tests/test_ai_live_check_tool.py`, `tests/test_ci_tools_offline.py`, `tests/test_collection_errors.py`, `tests/test_feed_review_tool.py`, `tests/test_live_ai.py`(opt-in), `tests/test_phase5d_design_doc.py`, `tests/test_user_guide_links.py`, `tests/test_voice_failed.py`, `docs/user_guide_realcontent.md`, `docs/windows_user_verification_checklist.md`, `docs/korean_tts_listening_checklist.md`, `docs/design/phase5d_higgsfield_video_provider.md`, 워크플로 `newsflow-phase5c1-windows.yml`.)

```text
/sources(최근 수집 오류 [kind])   /ai-settings(예상 토큰·단가)   /voices(레지스트리 감지·읽기 형태·청취 기록)
        │                              │                               │
  ci_feed_review ──► PublicRSSAdapter  intelligence/estimate ──► settings.check_budget   video/speech_text ──► WindowsTTS
  (정책 무변경)      Collector/NewsService  (used+prompt+cap)   ai_live_check(1회)        tts.korean_voice_report(읽기 전용)
```

## 3. A · 실제 RSS 검증

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 후보 파일과 검토 도구 | `tools/feed_candidates.json` 22개(17개 활성, `official_rss_page` 대부분 `unknown`, Reuters/AP 제외) · `python tools/ci_feed_review.py --mode windows --output <폴더>` → `feed-review.json` | (채움 예정) |
| 정책 무변경 | robots(first-match·fail-closed·Crawl-delay/Request-rate 차단)·SSRF/DNS 고정·TLS·리디렉션 3회·2 MiB·identity 인코딩·엄격 발행시각 | (채움 예정) |
| 증거 최소화 | 개수·발행사·링크 도메인·피드당 제목 3개(80자)만, 요약·본문 없음, `terms_confirmed_by_human: false` | (채움 예정) |
| 판정 분류 | PASS(연결 테스트 + 수집 2회 연속 성공) / BLOCKED(robots·policy) / NOT VERIFIED(dns·timeout·https·http·parse·empty·예산·사전 점검·비활성) / FAIL(앱 내부 결함) | (채움 예정) |
| `/sources` 오류 표시 | `최근 수집 오류: [kind] …` | (채움 예정) |
| Cloud 결과 | (채움 예정 — 외부 네트워크 없음, 전부 NOT VERIFIED 기대) | (채움 예정) |
| Windows Actions 결과 | (채움 예정 — 후보별 PASS/BLOCKED/NOT VERIFIED 개수, FAIL 0 기대; BBC BLOCKED(robots), HN BLOCKED(crawl-delay)) | (채움 예정) |

## 4. B · 외부 AI 검증 준비

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 예상 토큰 표시 | `/ai-settings` `#ai-estimate`: `실제 콘텐츠 1건(30초 기준) = 외부 AI 호출 2회 · 예상 최대 약 N 토큰 (입력 약 P + 출력 최대 O) · 이번 달 남은 R 토큰 · 예상 비용 C 또는 단가 미입력` · 시작 화면 `#start-ai-estimate` · 작업 화면 `#ai-estimate`(뉴스 고르기) · `#ai-actual`(대본 후) | (채움 예정) |
| 출력 상한 | 30초 1400 · 45초 1800 · 60초 2200, 분석 900 | (채움 예정) |
| 예산 검사 | `used + 예상 입력 + 출력 상한 > 한도` → `ai_budget` 호출 전 중단 | (채움 예정) |
| 단가·예상 비용 | AppSetting `ai_price_input_per_1m` / `ai_price_output_per_1m` / `ai_price_currency`(USD/KRW) · 면책 문장 고정 · 단가는 게이트 아님 | (채움 예정) |
| 게이트 강화 | 제공자 `offline` 저장 시 `ai_consent`, 읽을 수 없는 저장 키 `ai_key_missing` | (채움 예정) |
| 승인된 단일 호출 도구 | `NEWSFLOW_AI_LIVE_TEST=1` + `tools/ai_live_check.py --article-id <번호> --max-tokens 1400 --output ai-live` → `동의` → 정확히 1회 → `ai-live-check.json`(키·본문·대본 없음) → PASS/FAIL/BLOCKED | (채움 예정) |
| 토큰 0 연결 확인 | `--connection-check --model gpt-4o-mini` (`NEWSFLOW_AI_API_KEY` 환경변수) · CI는 수동 dispatch + secret 시에만, 그 외 SKIPPED 기록 | (채움 예정) |
| opt-in pytest | `tests/test_live_ai.py` 기본 SKIPPED | (채움 예정) |
| `voice_failed` 코드 | 메시지·해결 안내·`음성 설정 →` 링크 | (채움 예정) |
| 실제 OpenAI 호출 | (채움 예정 — Cloud/CI 0건; 사용자 PC 승인 호출 결과는 체크리스트 §4.6) | NOT VERIFIED |

## 5. C · 한국어 TTS 검증 준비

| 요구 | 구현 | 판정 |
| --- | --- | --- |
| 설치 안내 문장 통일 | `Windows 설정 → 시간 및 언어 → 언어 및 지역 → 한국어 → 언어 옵션에서 음성(텍스트 음성 변환)을 설치한 뒤 NewsFlow를 종료하고 run.bat를 다시 실행하세요.` (voices·마법사 5단계·진단) | (채움 예정) |
| 상태 감지 | `설치됨` / `없음` / `확인 불가` / `설치됨 · SAPI 미노출`(레지스트리 읽기 전용, OneCore 전용 이름 안내, 앱은 레지스트리 미수정) | (채움 예정) |
| 실행 정책 안내 | `Get-ExecutionPolicy -List` / `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`는 사용자 결정, 앱은 정책 미변경 | (채움 예정) |
| 읽기 형태 정규화 | `video/speech_text.py`: 날짜·시각·퍼센트·통화·단위·큰 수·범위·영문 약어, 음성 전달 문장에만 적용(자막·대본 원문 유지), 한글 불변 | (채움 예정) |
| 미리 듣기 | 원문·읽기 형태 표시, 고정 문장(날짜·시각·퍼센트·KOSPI·AI·달러), `voice-preview/preview-<id>.wav` | (채움 예정) |
| 장면 내레이션만 발화 | hook/summary/closing 미발화 | (채움 예정) |
| 청취 결과 기록 | `voice-listening/listening-<id>.json`(최근 50건) + AppSetting `voice_listening_last` · `사람 청취 결과: PASS/FAIL/NOT VERIFIED` · 부정확 항목 있으면 PASS 거부 · 자동화는 PASS를 쓰지 않음 | (채움 예정) |
| CI 프로브 | `tools/ci_korean_voice_probe.py`: 음성 목록·레지스트리·속도/쉼별 길이·고정 샘플 WAV, 비Windows는 NOT VERIFIED, 품질 판정 없음 | (채움 예정) |
| 실제 한국어 발화·발음 | Windows 러너 한국어 음성 수 (채움 예정) · 사용자 PC 청취 (체크리스트 §5) | NOT VERIFIED |

## 6. D · Windows 사용자 검증 절차

| 산출물 | 내용 | 판정 |
| --- | --- | --- |
| [사용자 안내서](../user_guide_realcontent.md) | 설치·실행·7단계·RSS·외부 AI·음성·제작·대본 검토·보관·데이터 위치·복구·하지 않는 일 | (채움 예정) |
| [검증 체크리스트](../windows_user_verification_checklist.md) | §0–§11, 기본 NOT VERIFIED, 30/45/60 MP4 표, 증거 제출 안내 | (채움 예정) |
| [청취 확인표](../korean_tts_listening_checklist.md) | 사람 청취 항목 8개·종합 판정 | (채움 예정) |
| README · START_HERE · autopilot.md · realcontent.md · architecture.md · windows_user_checklist.md · windows_validation.md | Phase 5C.1 반영, 오래된 문장 수정, 링크 | (채움 예정) |
| 문서 링크 검사 | `tools/ci_docs_link_check.py` · `tests/test_user_guide_links.py` (상대 링크·앵커·https) | (채움 예정) |
| 사용자 PC 수행 결과 | 체크리스트 §10 표 (채움 예정 — 받은 행만 전사, 나머지 NOT VERIFIED) | NOT VERIFIED |

## 7. E · Phase 5D 설계

| 항목 | 내용 | 판정 |
| --- | --- | --- |
| 설계 문서 | [docs/design/phase5d_higgsfield_video_provider.md](../design/phase5d_higgsfield_video_provider.md): `VideoProvider` Protocol(Fake/Higgsfield), 장면별 B-roll 제출·폴링·bounded 다운로드·ffprobe 검증·Pillow 오버레이·상수 FFmpeg 필터·카드 대체, 승인·월 한도·DPAPI 키·체험 금지·작업별 비용 확인 게이트, 예약 migration 0010 | (채움 예정) |
| 구현 여부 | 구현 없음. FFmpeg 카드 제작 기본 유지 | (채움 예정) |
| 외부 호출 | Higgsfield API/MCP 호출 0건 (catalog/balance 조회 포함) | (채움 예정) |
| vendor 사실 | 엔드포인트·상태·모델·가격·약관 전부 NOT VERIFIED | NOT VERIFIED |
| 문서 테스트 | `tests/test_phase5d_design_doc.py` | (채움 예정) |

## 8. Cloud 전체 테스트 결과

`python -m pytest -q -rs` (Python 3.12, Linux, `NEWSFLOW_FONT_PATH`=핀 고정 Noto Sans KR): **(채움 예정) passed / (채움 예정) skipped / (채움 예정) failed**. 증거: (채움 예정 — `cloud-pytest.txt`, `cloud-pytest.xml`). ruff: (채움 예정).

기준(5C HEAD `ca28121`) 995 passed / 6 skipped → 신규 테스트 (채움 예정)개. 기존 테스트 삭제·skip: (채움 예정 — 없음 기대).

Cloud 도구 실행: `ci_feed_review --mode cloud` (채움 예정 — 전부 NOT VERIFIED 기대), `ci_korean_voice_probe` (채움 예정 — NOT VERIFIED), `ci_docs_link_check` (채움 예정 — PASS, 검사 링크 수), `ai_live_check --connection-check` (채움 예정 — BLOCKED env_flag/key_missing).

## 9. Windows 전체 테스트 결과

워크플로 `newsflow-phase5c1-windows.yml`, artifact `newsflow-phase5c1-windows-validation`. 최종 실행 (채움 예정 — URL, 커밋, 러너, FFmpeg 버전).

| 단계 | 판정 | 요약 |
| --- | --- | --- |
| `pytest -q -rs` | (채움 예정) | |
| 실제 짧은 MP4·ffprobe·로컬 TTS | (채움 예정) | |
| Windows DPAPI 합성 vault·production vault | (채움 예정) | |
| 실제 BAT·재시작·OAuth GUI 차단 | (채움 예정) | |
| Easy UI(5A)·초기 설정(5B)·실제 콘텐츠 흐름(5C) | (채움 예정) | |
| **공개 피드 검토** (`feed-review.json`) | (채움 예정) | PASS/BLOCKED/NOT VERIFIED/FAIL 개수 |
| **한국어 음성 프로브** (`voice/`) | (채움 예정) | 한국어 음성 수, 레지스트리 hive 개수, 샘플 WAV 유무 |
| **문서 링크 검사** (`docs/docs-links.json`) | (채움 예정) | |
| 토큰 0 OpenAI 연결 확인 | (채움 예정) | 수동 dispatch + secret 없으면 SKIPPED |
| 한국어 SAPI 발화 품질 | NOT VERIFIED | 러너는 사람이 듣지 않음 |

이전 실행의 실패와 조치: (채움 예정).

## 10. 기존 Phase 5A/5B/5C 회귀

(채움 예정 — 5A 간편/단계별, 5B 마법사·setup.bat, 5C 실제 콘텐츠·RSS·AI 게이트·음성·30/45/60 MP4 결과가 기준과 동일한지. 정책 완화·검사 제거·테스트 삭제/skip 없음 확인.)

## 11. 데이터베이스 마이그레이션 및 재시작 보존

- **Migration head `0009` 유지, 새 마이그레이션 없음.** Phase 5C.1 상태는 AppSetting 키만 추가합니다: `ai_price_input_per_1m`, `ai_price_output_per_1m`, `ai_price_currency`, `voice_listening_last`. 청취 기록 본문은 `voice-listening/*.json` 파일입니다.
- 재시작 보존: (채움 예정 — Cloud/Windows 재시작 전후 `autopilot_jobs`·`content_drafts`·`news_source_checks`·`ai_usage`·AppSetting 동일 확인.)
- `migrate_data` 0009 지원 유지: (채움 예정).

## 12. API 비용·승인·실패 처리

- 게이트: 제공자 openai + 날짜 있는 승인 + 월 토큰 한도(>0, 미소진) + 키. 실행 시점마다 재평가. 체험 제작 외부 AI 금지.
- 예산: `used + 예상 입력 + 출력 상한`. 단가는 표시용이며 호출을 막지 않음.
- 실패 코드: `ai_consent` · `ai_budget` · `ai_key_missing` · `ai_auth_failed` · `ai_rate_limited`(Retry-After ≤15초 1회) · `ai_timeout`(재시도 없음) · `ai_unavailable`(1회) · `ai_bad_response` · `ai_not_ready`; 음성 `voice_unavailable` · `speech_too_long` · `voice_failed`.
- 승인된 단일 호출: 사용자 PC에서만, `동의` 입력, 1회. 결과: (채움 예정 — 사용자 PC에서 수행했으면 PASS/FAIL/BLOCKED와 사용 토큰·예상 대비 비율, 아니면 SKIPPED).

## 13. GUI 및 영상 제작 흐름

(채움 예정 — Cloud Chromium 스크린샷 목록: `ai-settings-estimate.png`, `sources-error-kind.png`, `voices-spoken-form.png`, `voices-listening.png`, `start-estimate.png`, `job-ai-actual.png` 등. 기본 메뉴 6개 유지, 실제 콘텐츠의 대본·최종 영상 필수 멈춤 유지, 외부 요청 0건·JS 오류 0건.)

## 14. 실제 외부 API 호출 여부와 비용

- 외부 AI API: Cloud (채움 예정 — 0건 기대) · Windows CI (채움 예정 — 0건, 또는 수동 dispatch 시 토큰 0 연결 확인 1건) · 사용자 PC 승인 호출 (채움 예정 — 0 또는 1건, 사용 토큰).
- 공개 RSS: Windows CI에서 후보 피드에 실제 HTTPS 요청 (채움 예정 — 피드 수·요청 수), 기사 본문 0.
- OAuth·SNS 호출 0건. **Higgsfield API/MCP 호출 0건.** 비용: (채움 예정 — 승인 호출이 없으면 0).

## 15. 미구현·미검증 사항

- **NOT VERIFIED**: 실제 OpenAI 호출 결과(사용자 승인 1회 외), 공개 피드 후보의 공식 여부·이용 약관(`terms_confirmed_by_human: false`), 한국어 SAPI 발화·발음 품질, 특정 음성 이름(예: "Microsoft Heami Desktop")·Windows 11 24H2 동작, MP4 시청 품질, 사용자 Windows 11 PC 수동 운영(체크리스트 §10 전체), Phase 5D vendor 사실 전부.
- **미구현(범위 밖)**: 실제 SNS 게시·OAuth 활성화·예약 스케줄러·무인 운영·기사 본문 수집·외부 유료 TTS·Higgsfield 호출·요금 결제/보증.
- **설계 조정**: (채움 예정 — 각 패키지가 기존 구조와 충돌한 요구를 어떻게 조정했는지.)

## 16. Draft PR·최종 SHA·Windows Actions URL

- Draft PR: (PR 번호 추후) (head `feat/newsflow-phase5c1` → base `feat/newsflow-phase5c`).
- 커밋: (채움 예정 — 패키지별 커밋 SHA, **최종 검증 SHA** (채움 예정)).
- Windows Actions: (채움 예정 — 실행 URL, artifact `newsflow-phase5c1-windows-validation`).
- 기존 PR #1~#10과 `main`은 변경하지 않음. 커밋 재작성·강제 푸시 없음: (채움 예정).

## 17. 증거 목록

| 증거 | 위치 | 비고 |
| --- | --- | --- |
| Cloud pytest 결과 | (채움 예정) `phase5c1_evidence/cloud-pytest.txt` | |
| Cloud 공개 피드 검토 | (채움 예정) `phase5c1_evidence/cloud/feed-review.json` | 전부 NOT VERIFIED 기대 |
| Cloud 문서 링크 검사 | (채움 예정) `phase5c1_evidence/cloud/docs/docs-links.json` | |
| Cloud 음성 프로브 | (채움 예정) `phase5c1_evidence/cloud/voice/` | NOT VERIFIED |
| Cloud 스크린샷 | (채움 예정) | |
| Windows Actions annotation 사본 | (채움 예정) `phase5c1_evidence/windows-actions-evidence.json` | |
| Windows 공개 피드 검토 | (채움 예정) artifact `feed-review/feed-review.json` | |
| Windows 음성 프로브 | (채움 예정) artifact `voice/` | |
| Windows 토큰 0 연결 확인 | (채움 예정) artifact `ai-live/ai-live-check.json` | SKIPPED 기본 |
| 사용자 PC 체크리스트 §10 | (채움 예정) | 받지 못한 항목은 NOT VERIFIED |
| manifest.sha256 | (채움 예정) | |
