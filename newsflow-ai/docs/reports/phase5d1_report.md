# NewsFlow AI — Phase 5D.1 완료 검증 보고서

보고 시각: 2026-10-16 10:12 KST (UTC+9). **구현·Cloud/Windows 회귀·GUI 검증 완료**. 개발 범위는 기존 자산 인수와 Higgsfield 유료 생성 안전성 보완이다. 실제 유료 API·OAuth·SNS 실행은 **0건**, 비용 **0**이다.

## 1. 인계 및 Git 기준

- [Codex 인계 검증](codex_handover_report.md): 기존 구현·문서 대조, 기준 회귀, 확인된 불일치와 환경 한계를 기록했다.
- Base: `feat/newsflow-phase5d` / `3951a231e8a5a03a113498d8223a25cc8a6d3b38`. 직전 검증 코드 `698508e4e85d7f16caebabdeaecf50cb8469e490`와 실행 코드가 같음을 확인했다.
- 새 브랜치: `feat/newsflow-phase5d1`. 구현·검증 코드: **`986355879681bdcc159163f413b2afed6c79b602`**.
- 신규 [Draft PR #13](https://github.com/jsbae1979-prog/JSBAE/pull/13), base `feat/newsflow-phase5d`. 기존 PR #1~#12 및 main 보존, 병합·force push·커밋 재작성 없음.
- 최종 보고서 커밋은 위 코드 이후 **문서·검증 산출물만** 추가한다. 그 커밋을 새로운 Windows 실행으로 표시하지 않는다. 정확한 최종 SHA는 PR HEAD와 최종 답변에 제출한다.
- migration 0001~0011 및 DB 모델 변경 없음. 기존 사용자 데이터·유료 클립 구조 유지. 다른 프로젝트 변경 없음. 신규 workflow는 이 브랜치 push에만 반응한다.

## 2. 발견·수정한 결함

| 결함과 근거 | 수정·검증 | 판정 |
| --- | --- | --- |
| 인계 기준 회귀가 재현한 기존 동작: Protocol은 재전송 금지라고 설명하지만 `_submit_one`은 408/429를 최대 3회 다시 대기시켰다. 기존 회귀도 4회 제출을 기대했다. | 제출 408/429를 unknown으로 분류; 서비스의 RateLimited 힌트도 보낸 요청이면 unknown. 반복 tick·재시작에도 최초 POST 1회만 수행, 비용 유지. | PASS (합성) |
| 업그레이드 전 저장된 waiting/requeues가 다시 제출되거나 승인 변경으로 not_sent 처리될 위험 | recover와 작업자의 보내기 전 검사에서 unknown 격리. 신규 POST 0, 기존 비용 예약 유지. | PASS |
| 비용 합산에서 잘못된 금액이 빠져 새 지출이 허용될 위험 | 금액·상태·통화의 ledger 검증 실패 시 승인·제출 차단. 잘못된 값은 오류에 출력하지 않음. | PASS |
| 현재 공식 Kling 2.6 / Wan 2.6 스키마와 기존 4필드 요청 불일치 | 후보에서 제외, provider에서 키 조회·네트워크 전에 차단. 등록 데이터·기존 클립 삭제 없음. | PASS (문서·단위 검사) |
| 새 사전 점검의 초기 구현은 HTML POST 응답 뒤 공통 JS가 GET으로 이동하여 화면을 열지 못함 | 실제 Chromium에서 재현. 기존 폼 규약대로 POST 303 → 읽기 전용 GET으로 수정. CSRF/Origin 정책 유지, 실제 브라우저 경로 통과. | PASS |

기존 2207개 케이스는 유지하고 **23개 추가**, 총 2230개다. 기존 자동 재전송을 기대하던 테스트 2개와 HTTP 408/429 기대값 2개를 안전한 동작으로 갱신했다. 테스트 삭제·근거 없는 skip 추가 없음. JUnit 비교 시 기존 Easy UI의 UUID 매개변수 이름도 매 실행 달라지지만 같은 테스트다.

## 3. 구현 구조

`AIVideoCoordinator → VideoProvider → HiggsfieldProvider/FakeVideoProvider` 구조를 유지했다. 뉴스·대본·스토리보드·TTS·FFmpeg·Autopilot·Publishing을 다시 구현하지 않았다.

- **제출**: 승인·모델·예상 비용·작업별/월 한도·DB 예약·CAS/파일 잠금 확인 후 단일 POST. 보낸 뒤 결과 불명은 자동 재생성하지 않는다.
- **복구**: request_id가 있으면 기존 조회·다운로드 경로를 사용한다. 번호 없는 제출 중/이전 재전송 대기는 unknown. 받은 클립과 검토 해시·다시 받기 정책은 기존 설계 §7.1을 보존한다.
- **로컬 사전 점검**: 설정의 “비용 없이 사전 점검”. 키 형식, 승인·한도, 등록 모델 스키마, 비용 기록, FFmpeg/ffprobe를 검사한다. Provider를 만들거나 요청·예약을 하지 않는다. 결과에 실제 인증/청구 NOT VERIFIED를 명시한다.
- **모델 검사**: 2026-10-16 공식 스키마와 맞는 6개 경로의 정수 길이·해상도를 검사한다. 나머지 사용자 모델은 기존 확인 정책을 유지하며 사전 점검에서 NOT VERIFIED다.
- **비용**: 사용자가 입력한 단가에 따른 예약·보낸 요청 기록이다. 실제 청구서/잔액과 연결되지 않았으며 실패·취소·unknown도 보수적으로 포함한다. 공급사 환불을 추정해 차감하지 않는다.

## 4. 공식 API 재검증

[공식 문서 조사 보고서](phase5d1_higgsfield_verification.md)에 항목별 URL·확인 날짜·모델 표·약관 제약을 기록했다. [공개 문서 GET 증거](evidence/phase5d1/official-docs-access.json)에는 HTTP 결과와 SHA256이 있다.

인증 ID:secret, 계정 단위 Idempotency-Key, 모델별 요청 형식, 최소 7일 결과 보관, 계정별 동시성, failed/nsfw 및 처리 전 취소의 크레딧 환불 설명은 **문서 확인 PASS**다. 실제 가격·할인·계정 권한·청구·환불·보관·생성 품질은 **NOT VERIFIED**다. API 문서의 크레딧 1년과 일반 약관의 추가 구매 90일은 적용 범위를 확정할 수 없어 NOT VERIFIED로 남겼다. 웹 구독료나 문서 예제 가격을 API 단가로 쓰지 않았고 인증된 estimate API도 호출하지 않았다. 문서가 동일 키 재전송을 안내하더라도 이번 앱은 제출 자동 재전송을 허용하지 않는다.

## 5. Cloud 전체 회귀와 GUI

검증 코드 `986355879681bdcc159163f413b2afed6c79b602`, Python 3.12.14. requirements-dev.lock의 설치 버전 일치, pip check·ruff PASS. pinned Korean font를 설정한 뒤 검사했다.

```text
NEWSFLOW_FONT_PATH=/tmp/newsflow-phase5d1/korean.ttf NEWSFLOW_LIVE_TEST=0 NEWSFLOW_AI_LIVE_TEST=0 \
.venv/bin/python -m pytest -q -rs --junitxml=/tmp/newsflow-phase5d1/cloud-final.xml
2223 passed, 7 skipped, 1 warning, 0 failed (224.28s)
```

[pytest 결과](evidence/phase5d1/cloud/pytest.txt), [JUnit](evidence/phase5d1/cloud/pytest.xml), [요약](evidence/phase5d1/cloud/summary.json). Skip 7 = 기존 live AI/RSS opt-in 2 + native Windows 5. 기존 Starlette/httpx deprecation 1건이며 새 실패/skip은 없다. 초기 글꼴 미설정 실행의 추가 skip은 기준 PASS로 사용하지 않았다.

실제 로컬 FastAPI 서버 + `/usr/bin/chromium` + 실제 FFmpeg + 주입한 Fake provider를 사용했다:

```text
NEWSFLOW_FONT_PATH=/tmp/newsflow-phase5d1/korean.ttf .venv/bin/python tools/ci_ai_video_validation.py \
  --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase5d1/cloud-gui
```

[브라우저 결과](evidence/phase5d1/cloud/ai-video-validation.json): 사전 점검 POST/Origin·기본 off·한도/중복 거부·프롬프트 정책·Fake 생성·클립 보존·서버 재시작 후 기존 요청 조회·관계 검토·합성·보관함·위조 Origin 403·CSP·브라우저 외부 요청 0 **PASS**. 첫 실패 화면의 잔여 파일에 관한 [증거 설명](evidence/phase5d1/cloud/evidence-notes.txt)을 함께 보존했다.

[합성 MP4](evidence/phase5d1/cloud/ai-final.mp4): **H.264/AAC, 1080×1920, 30.021029초**, 1,959,319 bytes, SHA256 `d7124709b10a17ed090ef4af05ca294c7b4543f055ffb4ba9b8f8e2275872e44`. 브라우저 재생 시간 진행 확인 PASS. AI 장면에 고정 AI 표시, 카드 장면에는 없음. **실제 Higgsfield 생성 영상이 아니며**, 사람의 음성/영상 품질 평가는 NOT VERIFIED다.

| 화면 | 증거 |
| --- | --- |
| 로컬 사전 점검 | [스크린샷](evidence/phase5d1/cloud/ai-preflight.png) — 키·승인 미설정에 대한 FAIL은 정상 차단 안내 |
| 설정 | [스크린샷](evidence/phase5d1/cloud/ai-settings.png) |
| 비용 확인·한도 | [스크린샷](evidence/phase5d1/cloud/ai-plan-cost.png) |
| 생성 완료·클립 보존 | [스크린샷](evidence/phase5d1/cloud/ai-plan-ready.png) |
| 최종 영상 | [작업](evidence/phase5d1/cloud/ai-job-page.png), [보관함](evidence/phase5d1/cloud/ai-library.png), [AI 표시 프레임](evidence/phase5d1/cloud/ai-final-frame-ai-scene.png) |

## 6. Windows Actions

[실행 38832096264](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38832096264), 코드 SHA `986355879681bdcc159163f413b2afed6c79b602`, 전용 `newsflow-phase5d1-windows.yml`.

**PASS — SUCCESS**, 2026-10-16 **09:53:53~10:08:28 KST**. windows-latest는 Windows Server 2025, Python 3.12.10, 실제 Google Chrome/FFmpeg 7.1.1이다. 사용자 Windows 11 PC와 구분한다.

| 검증 | 결과 | 증거 |
| --- | --- | --- |
| 전체 pytest | **2227 passed / 3 skipped / 1 warning / 0 failed**, 총 2230개, 329.83초 | [JUnit](evidence/phase5d1/windows/pytest.xml), [로그 발췌](evidence/phase5d1/windows/pytest-summary.txt) |
| 실제 BAT·서버 종료/재시작·DB 보존·포트 충돌 | PASS | [결과](evidence/phase5d1/windows/result.json) |
| DPAPI 및 production vault 합성 암호화·다른 프로세스/사용자·회전·변조 거부 | PASS, 실제 서비스 토큰 0 | [vault](evidence/phase5d1/windows/credential-vault.json), [production vault](evidence/phase5d1/windows/production-credential-vault.json) |
| AI 영상 Fake·새 사전 점검 POST·한도/중복 거부·재시작·클립 보존·Chrome 재생 | PASS | [결과](evidence/phase5d1/windows/ai-video/ai-video-validation.json), [화면](evidence/phase5d1/windows/ai-video/ai-preflight.png) |
| 자동 제작·수정·로컬 대기함·취소·320px/200% CSS 배율 | PASS (사용성 연구/실제 브라우저 확대 평가는 별도) | [Autopilot](evidence/phase5d1/windows/autopilot/autopilot-result.json) |
| setup.bat·마법사 실패/재시작 복구·30/45/60초 세로 MP4 | PASS, 무음 검토 영상 | [Easy Setup](evidence/phase5d1/windows/easysetup/easysetup-result.json) |
| 기존 실제 콘텐츠 경로·필수 검토·30/45/60초 브라우저 재생 | PASS, RSS fixture / Offline AI 사용 | [콘텐츠 흐름](evidence/phase5d1/windows/realcontent/realcontent-result.json) |
| 공개 RSS 별도 연결 검사 | 조선일보 기사 100개 접속·파싱 PASS. **이 연결 검사는 실제 기사를 DB에 저장하지 않음** | 위 결과의 live_public_rss |
| 공개 피드 검토 | 22개 중 17개 시도, PASS 14 / robots BLOCKED 3 / 비활성 NOT VERIFIED 5 / FAIL 0 | [피드 결과](evidence/phase5d1/windows/feed-review/feed-review.json) |
| 한국어 SAPI | **NOT VERIFIED**, 설치된 한국어 음성 0개. 영어 SAPI WAV/MP4 생성은 PASS | [음성 프로브](evidence/phase5d1/windows/voice/voice-probe.json), [샘플](evidence/phase5d1/windows/video-result.json) |
| 실제 OAuth/SNS/유료 AI | 호출 0, 차단 유지 | result.json, [CI 실행 경계](evidence/phase5d1/windows/ai-live/phase5d1-boundary.json) |

[Actions 단계·시간·집계](evidence/phase5d1/windows/windows-actions.json), [check annotations](evidence/phase5d1/windows/check-annotations.json). 모든 단계 성공, check warning/failure annotation 0개, Node.js 20 중단 경고 없음. **pytest에는 Starlette/httpx deprecation 1건이 실제 존재한다**(Cloud에서도 재현). 경고 0으로 보고하지 않는다. Skip 3 = live AI/RSS opt-in 2 + Windows에서는 실제 DPAPI를 사용하므로 해당하지 않는 non-Windows fallback 검사 1.

Windows [AI 합성 MP4](evidence/phase5d1/windows/ai-video/ai-final.mp4)는 30.021029초, SHA256 `114be7f7ab28255f4f84ae0104441fb98eb9947658ec86872067e5c94d6b8fdc`, Chrome 재생 PASS. 실제 생성 품질과 한국어 청취는 NOT VERIFIED. 표의 PASS는 자동화한 동작 범위만 뜻한다. 공개 RSS 성공도 해당 피드·시점의 결과이며 사용자 PC/전체 RSS/실제 수집 저장 성공으로 확대하지 않는다.

## 7. 보안·비용·외부 호출 근거

- Higgsfield/OpenAI 실제 API, Higgsfield MCP, OAuth 로그인·교환, SNS 업로드·게시 **0건**, 발생 비용 **0**. 실제 credential을 발급·저장·사용하지 않았다.
- provider 단위 검사는 주입한 requester/메모리 socket을 사용한다. 새 protocol 검사는 408/429/500/503/단절/잘못된 응답에도 mock POST 1회만 관찰한다. 브라우저 fixture 서버는 `--fake-video-provider`이며 실제 공급사 경로를 사용하지 않는다.
- CI에는 실제 키 secret 매핑·live AI 단계가 없고 두 AI 키 환경변수는 빈 값이다. live pytest opt-in은 꺼져 있다. 공개 문서 GET, 패키지/글꼴 다운로드 및 기존 별도 공개 RSS 점검은 유료 AI 호출과 구분한다.
- CSRF/Origin/CSP/SSRF/TLS, DNS 고정·안전 다운로드·ffprobe 형식 제한, DPAPI 및 OAuth/SNS hard block은 완화하지 않았다. 새 점검은 키/공급사 예외 원문을 반환하지 않는다.
- unknown 비용 유지, 승인/작업별·월 한도, 단일 제출, legacy 재전송 격리, 계정 키 비노출, 기존 유료 클립 유지의 합성 회귀 PASS. 공급사의 실제 중복 청구 방지를 보장한다고 주장하지 않는다.

## 8. 변경 파일

- `video/ai/service.py`, `higgsfield.py`, `settings.py`: 제출/복구·비용 기록·후보 검사.
- 신규 `video/ai/model_contracts.py`, `preflight.py`: 날짜 있는 스키마 계약과 로컬 점검.
- `gui/video_ai_routes.py`, `templates/video_ai_settings.html`, 신규 `video_ai_preflight.html`: 점검 동선.
- `test_ai_video_provider.py`, `test_ai_video_service.py`, 신규 `test_phase5d1_safety.py`: 기존 기대값 안전성 수정 + 23개 새 케이스.
- `tools/ci_ai_video_validation.py`, 신규 `.github/workflows/newsflow-phase5d1-windows.yml`: 실제 GUI POST 및 Windows 전체 회귀. 기존 workflow 변경 없음.
- README·AGENTS·현재 구현 설계·사용 안내, 인계/공식 조사/완료 보고서, Windows 점검표, 검증 산출물. 과거 완료 보고서는 당시 기록으로 보존.

## 9. 미검증·남은 위험과 다음 단계

**NOT VERIFIED**: 실제 Higgsfield 인증·모델·가격·잔액·환불·중복 청구 방지·CDN/보관·품질, 실제 OpenAI, 실제 OAuth/SNS, 사용자 Windows 11 PC 최초 설치/운영, 한국어 음성의 사람 청취 및 완성 영상의 사람 평가. Windows Actions는 사용자 PC 검증을 대체하지 않는다.

날짜 있는 모델 스키마는 공급사 변경을 자동 감지하지 않는다. 사용자가 확인한 미등록 모델은 별도 문서 확인이 필요하다. 비용 한도는 입력 단가 기반이므로 실제 공급사 청구 상한을 보장하지 않는다. 결과 불명 해제 후 사용자가 내용/모델을 바꾸어 새로 승인하면 새로운 요청이며 추가 청구 가능성이 있다. 기존 정책대로 비용을 유지하고 사용자 확인을 요구한다.

다음 승인 전 [Windows 최초 실행 사전 점검](../windows_higgsfield_preflight_checklist.md)으로 기존 데이터 보존·로컬 도구·모델 옵션/단가·한도·키 형식을 확인한다. 실제 유료 검증은 모델·횟수·최대 비용·전송 내용에 대한 별도 사용자 승인이 있어야 한다. 자동 스케줄러, 실제 OAuth, SNS 게시, 다음 개발 단계와 main 병합은 진행하지 않는다. 완료 후 ACCEPTED / CONDITIONAL / REJECTED 판정을 기다린다.

Cloud 재사용 설치/시작 안내는 환경 설정 **초안으로 저장**했다. 글꼴 경로 준비와 현재 브랜치·Fake 검증 명령을 반영하고 네트워크/secret 정책은 변경하지 않았다. 이 저장은 적용/게시가 아니며 환경 설정에서 검토·저장 후 Publish가 필요하다. 새 작업 복원은 NOT VERIFIED다.

## 10. 제출 자료와 종료

[보고서·검증 증거 ZIP](phase5d1_report.zip)에 이 보고서, 인계/공식 조사, Windows 점검표, Cloud/Windows JSON·JUnit·스크린샷·합성 MP4를 담았다. 전체 CI artifact의 선별 사본이며 사용자 DB·키 파일은 포함하지 않는다. [파일 해시 목록](evidence/phase5d1/manifest.sha256)으로 증거를 확인할 수 있다. Draft PR과 Actions는 위 링크에서 확인한다.

개발 범위의 검증을 완료하여 제출한다. 실제 유료 서비스 준비 완료나 운영 품질 승인으로 간주하지 않는다. **추가 개발을 중단하고 사용자 판정을 기다린다.**
