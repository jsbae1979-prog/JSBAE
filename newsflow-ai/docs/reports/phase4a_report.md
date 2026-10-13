# NewsFlow AI — Phase 4A SNS Publishing Foundation

## 개발 판정과 승인 경계

Phase 3 승인 HEAD `641167e08583e628602ca27fd07a31b9609a9aac`에서 `feat/newsflow-phase4a`를 분기했습니다. Windows 11/Python 3.12, FastAPI/Jinja/HTML/CSS/JS, 127.0.0.1:8765 및 LOCALAPPDATA/NewsFlowAI를 유지합니다. 실제 SNS 게시·계정 연결·OAuth token exchange·외부 MP4 업로드·공개 URL 제공은 구현/실행하지 않습니다. Phase 4B·main 병합·기존 PR #1/#2/#3 변경은 수행하지 않습니다.

| 항목 | 결과 | 근거/범위 |
|---|---|---|
| Cloud 전체 회귀 | PASS | 218 passed / 1 skipped / 1 warning / 0 failed, 기존 147개 유지+71개 추가 |
| Cloud 실제 GUI POST/보존 | PASS | 실제 Chromium create/edit/validate POST 303, 진짜 Origin, 모바일/재시작 유지 |
| 로컬 MP4 준비 검증 | PASS | 실제 30초 MP4 독립 ffprobe, SHA256, 코덱/해상도/길이와 검토/메타데이터 검사 |
| 실제 SNS 게시·OAuth 호출 | PASS | 금지 경계 검증: 0건; 실제 게시 성공 판정이 아님 |
| Fake 전체 흐름 | PASS | simulated/failed/expired/unknown, 승인 차단·중복/동시 요청·재시작 결과 불명 처리 |
| Google/Meta 공식 스키마·SDK 조사 | PASS | 공급자가 관리하는 최신 공식 GitHub 아티팩트 읽기/구조 확인 |
| YouTube 공식 웹 문서 본문 | PASS | Windows verified HTTPS에서 업로드·텍스트/태그·Shorts·인코딩·AI 공개·OAuth 본문 확보; 아래 확인 범위 참조 |
| 계정별 정책 적용·Instagram 최신 요건 | NOT VERIFIED | 실계정 미연결; Meta 로그인별 문서 접근 제한 및 일부 공식 페이지 내부 요약/본문 불일치 |
| Windows Actions | PASS | 218 passed / 1 skipped / 0 failed; native BAT·Chrome POST·재시작·포트 충돌 확인 |
| 실제 SNS 계정·토큰·업로드 | NOT VERIFIED | 이번 단계 금지; 연결 성공/게시 SUCCESS 없음 |
| 실제 Windows 11 사용자 PC | NOT VERIFIED | 기존 설치/권한/음성/운영 검증 상태 유지 |
| 실제 RSS/AI API | NOT VERIFIED | 기존 미검증 상태 유지 |

## 공식 API 조사: 2026-10-13 UTC

[공식 조사·URL·확인 날짜 및 인증 설계](../publishing_platforms.md), [접근 결과·공식 소스 근거](phase4a_evidence/publishing_official_sources.json).

Google 공식 google-api-python-client의 YouTube v3 discovery revision `20261001`(관련 파일 변경 2026-10-06, commit `19fd51d1d18446206091a21eec763057d032c2b3`)에서 `videos.insert` POST/공식 media upload/resumable 구조, `youtube.upload` scope, VideoStatus.containsSyntheticMedia 및 uploaded/processed/failed/rejected 구분을 확인했습니다. schema 파일 크기 상한 274877906944bytes(256GiB)는 API 상한이며 Shorts 분류/계정 자격 보장이 아닙니다. 공식 v3 스키마 메서드 조사에서 Shorts 전용 업로드 메서드는 없고 videos.insert와 자동 Shorts 분류를 구분합니다.

Cloud에서는 12개 공식 웹 문서 CONNECT가 기존 프록시403으로 차단됐습니다. 기존 Windows Runner에서 인증 없는 공개 문서 GET을 재시도하여 YouTube 본문을 확보했습니다. 확인한 텍스트 제한은 제목100자·꺾쇠 제외, 설명5,000 UTF-8바이트·꺾쇠 제외, API tags500자(쉼표 및 공백 태그의 인용부호 포함)입니다. 앱은 공백 없는 해시태그를 사용하는 실제 준비 payload 기준으로 바이트/태그 예산을 검사하도록 보완했습니다.

공식 Shorts 본문은 일반 채널에서 2024-10-15 이후 업로드된 정방형/세로·3분 이하 영상의 분류, 음악/공식 아티스트 채널의 별도 날짜 조건, 1분 초과 영상의 활성 저작권 claim에 따른 차단을 설명합니다. 이는 업로드 API와 구분되며 실제 분류·수익화·저작권 승인 성공을 검증한 결과는 아닙니다. MP4/H.264/AAC 권장 인코딩, 사실적으로 생성/의미 있게 변형한 AI 콘텐츠의 공개 의무, 시스템 브라우저/local redirect/PKCE 기반 desktop OAuth 안내도 본문에서 확인했습니다. 실제 OAuth는 구현/실행하지 않습니다.

quota 본문은 기본 videos.insert100 calls/day 및 Video Uploads bucket1 unit/call을 명시합니다. 같은 페이지의 자동 요약은 과거1600을 표시했고 videos 리소스의 요약과 videos.insert 본문도 미검증 프로젝트 공개 제한 설명이 달랐습니다. 자동 요약을 정책 본문으로 확정하지 않았습니다. 대상 프로젝트의 quota·공개 가능 여부·감사/앱 검수 적용은 NOT VERIFIED이며 Phase4B에서 확인해야 합니다.

Meta 공식 facebook-python-business-sdk(관련 iguser.py 변경 2026-08-25/공식 근거 commit은 조사 문서 참조)에서 POST media/media_publish(creation_id), content_publishing_limit(config/quota_usage), video_url/upload_type/is_ai_generated 필드를 확인했습니다. SDK 필드 존재는 로그인 경로별 지원/권한·전문 계정 자격·연결 Page·게시 한도 수치·AI 표시 적용 범위를 증명하지 않습니다. Instagram Login과 Facebook Login 경로 및 권한을 혼용하지 않고, 최신 경로별 확인을 4B 선행 조건으로 남겼습니다. 공개 URL만 유일한 전달 방식이라고 단정하지 않습니다. SDK의 upload_type/resumable 대안도 공식 경로별 재조사 전 구현하지 않습니다. 로컬 MP4를 외부 서버나 공개 URL로 제공하지 않습니다.

출처: https://developers.google.com/youtube/v3/docs/videos/insert , https://developers.facebook.com/docs/instagram-platform/content-publishing/ 및 공급자 공식 GitHub URL을 조사 문서에 포함했습니다. 웹 문서 접근 실패를 API 금지/정책 실패로 해석하지 않았고 DNS/프록시/TLS 설정·허용 목록을 변경하지 않았습니다.

## 구현 구조 및 GUI

Publishing Studio → PublishingService/MediaInspector → PublishValidation/Evidence → PublishJobRepository/Fake Publisher 구조입니다. Publisher Protocol, InstagramAdapter, YouTubeAdapter, FakePublisher를 추가했습니다. 실제 adapter는 메모리의 payload 준비 명세만 제공하고 publish/connect는 approved=True/환경변수/API 준비 메타데이터와 무관하게 ExternalPublishingDisabled로 거부합니다. HTTP/OAuth transport와 실제 실행 라우트 자체가 없습니다.

GUI는 완성 영상 선택, 플랫폼/제목/설명/태그 편집, 출처/내용/권리 확인, AI 표시 검토, 검증 결과, 초안 저장/조회/수정, 로컬 계정 이름/유형 상태, 이력/오류 및 향후 승인 대기 의미를 제공합니다. Video Studio 완료 영상과 연결합니다. 계정 저장은 인증이 아닌 로컬 메타데이터이며 모든 연결 상태는 not_connected입니다. 연결·토큰 입력·실제/Fake 게시 실행 버튼은 없습니다. 모든 실제 준비 상태는 blocked이며 로컬 검사 PASS와 사용자 최종 승인/실계정 실행을 구분합니다.

다음 항목을 저장/검사합니다: MP4 존재/빈 파일/경로/symlink/크기/SHA256/독립 ffprobe, codec/shape/duration/fps, 제목/설명/태그, 출처 링크·권리·내용 검토, AI 표시 판단, 대상 플랫폼/계정, 권한/API/공식 정책 준비, 영상 단위 중복 식별자. 보안상 ffprobe는 shell=False/제한시간/file,pipe protocol whitelist/mov demuxer/비밀정보를 제외한 환경으로 실행해 악성 playlist가 외부 URL을 읽지 못하게 합니다. 외부 예외·probe stdout/stderr는 로그/HTML에 표시하지 않습니다.

앱의 보수적인 준비 프로파일: 최대2GiB, H.264/AAC/1080×1920/30·45·60초, 제목100자, caption 예산 Instagram2200자·YouTube5000자(제목/설명/태그 포함), 태그30개. 이 앱 예산에 추가로 확인된 YouTube 설명5,000 UTF-8바이트·꺾쇠 금지 및 API tags500자(쉼표 포함)를 적용합니다. Instagram의 문자/태그 예산을 최신 공식 한도로 주장하지 않습니다. 실제 계정 정책 적용·자격·URL 방식 미확인이 unverified/fail blocker이므로 게시 가능으로 승격하지 않습니다. 원본 렌더 해시가 없는 기존 MP4는 초안 생성 시점부터 해시 기준을 세우며, 그 이전 변조나 사실·저작권 검증을 hash가 보장하지 않습니다. ffprobe는 컨테이너/스트림 메타데이터를 검사하며 모든 프레임·오디오의 전체 디코드 검증은 구현하지 않았습니다. 실제 브라우저에서 선택된 합성 30초 MP4의 프레임 디코드를 확인한 범위와 구분합니다.

AI 선택은 unreviewed/not_required/disclose이며 사용자가 현실적인 합성/변조 여부를 검토해야 합니다. YouTube containsSyntheticMedia, Meta is_ai_generated는 공식 필드 매핑 후보이고 플랫폼/로그인별 적용 정책 확인을 대신하지 않습니다. 단순 AI 대본/텍스트 카드/TTS 생성 자체로 표시 의무를 임의 확정하지 않습니다.

## DB/중복/불명 상태 및 영속 근거

0004 additive migration: PublishDraft, PlatformAccount, PublishValidation, PublishJob, PublishAttempt, PublishEvidence. 기존 0001~0003 파일은 변경하지 않고 기사·점수·대본·영상·설정을 보존합니다. 이전 도구는 revision0004를 지원합니다. 사용자 DB·영상·비밀값은 Git 제외이며 업데이트 전 백업이 필요합니다.

수정은 revision 조건부 UPDATE, 검증은 revision CAS로 동시 수정 중 stale 결과를 rollback합니다. 출처·초안 시점 media hash와 validation revision을 보존합니다. Fake 호출은 명시적 승인/최신 로컬 검사·재해시 확인 후 조건부 writer reservation과 UNIQUE(플랫폼/계정/media SHA256) key를 먼저 저장합니다. 승인 없는 호출, 실제 adapter, 만료/회수 메타데이터는 차단합니다. 같은 영상/대상은 제목 수정·재시작·결과 불명/실패 이후에도 adapter를 다시 호출하지 않습니다. 요청 revision·validation ID·대상 account_id·metadata snapshot을 evidence에 기록합니다.

Fake 결과는 simulated/failed/expired/unknown이며 SUCCESS/실제 게시 완료로 기록하지 않습니다. 신뢰할 수 없는 Fake 결과나 예외는 unknown, 메시지/외부 reference는 그대로 저장하지 않습니다. repository의 명시적 recovery는 미완료 simulating을 unknown으로 분류하며 자동 재시도하지 않습니다. GUI는 simulation을 시작하거나 recovery를 실행하지 않습니다. 이는 Fake 재시작 모델 검증이며 실제 플랫폼 조회/reconciliation은 4B 미구현 항목입니다.

## OAuth/인증 및 보안

PASS: 기존 CSRF/signed cookie/Origin:null 거부/Host/SSRF/TLS/robots/CSP/no-referrer/HTML escape 유지. 새 POST도 동일 보호. 실제 adapter/OAuth/vault는 무조건 차단. 토큰값 DB 컬럼·입력 폼·로그 없음. 로컬 입력에서 알려진 env 비밀값/인증 패턴을 거부합니다. TokenBundle SecretStr repr/JSON 및 validation error 입력 마스킹, Fake vault는 테스트용 메모리/사본/UTC 만료·회수만 제공합니다. opaque credential_ref는 계획된 비밀 저장소 참조용이며 GUI/API에서 표시하지 않습니다.

NOT VERIFIED/미구현: 실제 Windows Credential Manager/DPAPI 보관, OAuth client registration/browser code flow/state·PKCE·정확한 loopback callback/code exchange/refresh·취소·계정 권한·서비스 정책. 실제 저장소는 UnavailableCredentialVault이고 토큰을 읽거나 저장하지 않습니다. 최소권한 후보 youtube.upload는 공식 근거가 있고 Instagram scope·계정 자격은 최신 공식 문서 확인을 기다립니다. 외부 모델 키나 실제 token을 GitHub Actions에 등록하지 않았습니다.

## Cloud 테스트와 실제 호출 0건 증거

명령 `python -m pytest -q -rs`: 218 passed /1 skipped /1 warning /0 failed. 기존147+신규71. skip은 기존 opt-in live RSS, warning은 기존 Starlette/httpx TestClient deprecation이며 숨기지 않았습니다. 모델/파일·규격/메타데이터/권한/검토/Fake/승인 차단/중복 동시 예약/결과 불명/재시작/credential redaction/만료·회수/GUI CSRF·escaping/0003→0004 보존/stale 검증 rollback 및 YouTube 한국어/해시태그 포함5,000바이트·쉼표 포함500자 경계를 테스트했습니다. [pytest](phase4a_evidence/cloud_pytest.txt).

실제 FastAPI/Chromium 명령 `python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase4a-cloud`: PASS. 초기 구현 `161addb`의 실제30초 MP4·기존 화면을 유지하고 새 GUI save/edit/validate POST303/Origin, 반복검증, 모바일, 재시작 유지 확인. 이후 YouTube 바이트/태그 검사 보완은 최종 Cloud pytest와 Windows 실제 브라우저에서 검증합니다. [구조화된 결과](phase4a_evidence/cloud_result.json), [Publishing Studio](phase4a_evidence/publishing_studio.png), [모바일](phase4a_evidence/mobile.png).

0건 근거는 다음을 결합합니다: (1) 실제 publisher/connect/vault의 무조건 차단 및 HTTP transport/실행 라우트 부재, (2) 승인/설정 위조/토큰 입력으로 해제되지 않는 오프라인 테스트, (3) 실제 GUI DB에 publish_drafts1/publish_validations2/publish_jobs0/publish_attempts0, (4) safety 상태 real_publish_calls0/real_oauth_calls0/external_execution_enabled=false, (5) 브라우저 외부 요청 origins[] 및 재시작 후 동일 상태. safety 숫자만으로 전체 앱의 모든 네트워크를 측정한다고 주장하지 않습니다. 공개 문서/GitHub 읽기·의존성 설치와 실제 SNS OAuth/게시 요청을 구분합니다. 조사·테스트에 실제 계정·키·SNS 로그인을 사용하지 않았습니다.

## Windows Actions 최종 검증

[최종 Windows 실행 38485460702](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38485460702), 검증 HEAD `7d5b7052f9afe82dbc83dead1df5ebd3eeb9b87b`: 전체 workflow/job **SUCCESS**, 219개 중 **218 passed / 1 skipped / 0 failed / 0 errors**. [pytest 요약](phase4a_evidence/windows_pytest.json), [실행/step 기록](phase4a_evidence/windows_run.json). JUnit 요약에는 warnings 수가 없어 Windows warning 수는 NOT VERIFIED이며 0이라고 주장하지 않습니다.

PASS: windows-latest/Python3.12에서 실제 run.bat 및 LOCALAPPDATA 기본 경로, 서버 health/기동·종료, 중복 실행·포트 충돌 차단, SQLite 저장·재시작·조회, 실제 Chromium 기반 Google Chrome의 Origin/CSRF 유지 POST, Publishing 초안 생성·수정·검증, 모바일·재시작 유지. [실제 실행 결과](phase4a_evidence/windows_result.json). 최종 GUI DB는 초안1/검증2/게시 작업0/시도0이며 실제 SNS/OAuth 호출0 및 외부 브라우저 요청 origins[]입니다.

PASS: 기존 FFmpeg 3초 MP4/ffprobe, 한국어 자막 raster, SAPI 음성→WAV→MP4, 30초 GUI MP4 프레임 디코드·미리보기·다운로드 회귀. [영상/TTS 요약](phase4a_evidence/windows_video.json). NOT VERIFIED: 사용자 Windows11 PC, 수동 Ctrl+C 종료, 한국어 발음·음성/전체30·45·60초 콘텐츠 품질. CI의 종료는 taskkill process tree이며 수동 종료를 대신 검증했다고 표시하지 않습니다.

공식 문서는 공개 HTTPS GET만 사용했으며 인증·게시·영상 외부 제공·네트워크 설정 변경 없이 Google7개 및 Meta 정책 블로그1개의 본문 발췌를 확보했습니다. Instagram 개발 문서4개는 허용된 공개 문서 범위 밖으로의 redirect를 거부하여 NOT VERIFIED입니다. TLS 검증·호스트/경로 제한을 완화하지 않았습니다. 수집한 본문 발췌(최대6,000자/page) 전부를 7개의 압축 chunk에서 SHA256 확인 후 복원했으며 발췌 축소는 없습니다. [문서 발췌/접근 상태](phase4a_evidence/windows_official_docs.json). 자동화 도구의 HTTPS200/content PASS는 본문 확보 의미이며 정책 결론은 사람이 읽은 범위만 위 조사에 명시했습니다.

초기 Windows run38483110119 및 공식문서 수집 추가 run38484335257도 209 passed /1 skipped /0 failed로 성공했습니다. 최종 기능 커밋에서는 추가9개 경계검증까지 포함한 218개를 검증했고, 이후 변경은 보고서/근거/README/다운로드 ZIP 문서뿐입니다.

## 변경 파일

- publishing/{adapters,auth,media,service,repository,__init__}.py: 계약·차단·Fake·credential 구조·media 검사·초안/검증/작업 근거.
- db/models.py, db/migrations/versions/0004_publishing.py: 6개 새 모델 및 schema; migrate_data.py: 새 revision지원.
- gui/publishing_routes.py, templates/{publishing,base,video}.html, static/css/app.css, main.py: 새 GUI 및 연결/보안 라우트.
- tests/test_publishing.py(71개), 기존 test_database/test_intelligence.py revision기대값: 기존 테스트 제거/skip 없음.
- tools/ci_validation.py, tools/ci_official_research.py, .github/workflows/newsflow-phase4a-windows.yml: Phase4A 전용 실제 GUI/DB/브라우저 외부 요청 0건·Windows 회귀·인증 없는 공개 공식 문서 읽기. 이전 workflow 변경 없음.
- AGENTS.md, README.md, pyproject.toml(0.4.0a1, 추가 의존성 없음), docs/architecture.md, docs/publishing_platforms.md, 본 보고서/evidence: 승인경계·실행/설계/출처/검증 문서.

## 미구현/미검증 및 Phase 4B 선행 조건

실제 OAuth·보안 저장소·refresh token·Instagram URL/resumable·YouTube upload sessions·플랫폼 상태 조회·실제 콘텐츠 승인·계정 자격/앱검수/quota·웹훅·전송 timeout 후 재조회·실제 Shorts 분류·AI 표시의 계정 적용/아동 대상/저작권 승인·게시·자동화는 미구현/미검증입니다. Shorts의 공식 분류 조건과 YouTube AI 공개 원칙을 읽은 사실은 실제 적용 검증과 구분합니다. 기존 실제 RSS/AI/Windows PC/전체 영상 품질도 NOT VERIFIED입니다.

4B 진입 전 사용자 Phase4A 승인과 별도 실계정 연동/전송 승인, 최신 canonical 정책·로그인경로·최소 scope·계정 자격/검수/quota 확인, Windows 보안 저장소 및 state/PKCE/callback 설계 검증, 승인할 계정/콘텐츠/AI·아동·저작권 판단, 허가된 Instagram 전달 방식(임의 공개/업로드 금지), YouTube 공식 업로드와 Shorts 분류 구분, private 테스트/결과 조회·중복 방지·UNKNOWN reconciliation/비용 계획을 확정해야 합니다. 이번 단계에서 이를 승인하거나 실행하지 않습니다.

## Git/Draft PR 및 최종 중단

기준 `641167e08583e628602ca27fd07a31b9609a9aac`, 별도 `feat/newsflow-phase4a`. [Draft PR #4](https://github.com/jsbae1979-prog/JSBAE/pull/4)의 base는 `feat/newsflow-phase3`이며 OPEN/DRAFT입니다.

- 기능 커밋: `161addb9689240065f393d5d1dfe8c46e43715b8`.
- Windows 공식 문서 수집 커밋: `879a81a7e1c091a0c4f707f565240adf6cff12ac`.
- YouTube 공식 바이트/태그 예산 및 압축 조사 근거 보완: `7d5b7052f9afe82dbc83dead1df5ebd3eeb9b87b`.
- 최종 검증 근거/보고서는 문서 커밋으로 추가하며 PR의 Commits에서 최종 HEAD를 확인할 수 있습니다.
- GitHub 읽기 확인: PR #1 HEAD `bd9df6d240c137542121343ff137a5e94042b676`, #2 `f9f9f0fc6bdad3478a2f53871ecbbab4d813c97b`, #3 `641167e08583e628602ca27fd07a31b9609a9aac`, main `aa2f056d78ceed24874d0b4c50c6033f7168bf4d` 유지. 기존 PR 모두 미병합입니다.
- 변경 범위는 `newsflow-ai/`와 새 Phase4A workflow 하나입니다. 기존 migration 0001~0003과 다른 프로젝트 변경은 없습니다.

완료 보고서와 검증 결과를 제출한 뒤 개발을 중단하고 사용자 승인 전 Phase4B를 진행하지 않습니다. 실제 SNS 연결·게시·main 병합은 수행하지 않았습니다.

## 보고서 다운로드

[보고서 및 검증 근거 ZIP](https://github.com/jsbae1979-prog/JSBAE/raw/refs/heads/feat/newsflow-phase4a/newsflow-ai/docs/reports/phase4a_report.zip)을 제공합니다. GitHub 로그인이 필요한 저장소에서는 로그인한 브라우저에서 내려받으세요. ZIP에는 docs/reports/phase4a_report.md, 공식 조사 및 근거 JSON/pytest/화면 자료를 포함합니다.
