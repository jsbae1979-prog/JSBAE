# NewsFlow AI — Phase 3 Video Production 완료 보고서

## 개발 범위와 판정

Phase 2 승인 커밋 f9f9f0fc6bdad3478a2f53871ecbbab4d813c97b에서 `feat/newsflow-phase3`를 분기했습니다. 운영은 Windows 11/Python 3.12, GUI 127.0.0.1:8765, 사용자 데이터 LOCALAPPDATA/NewsFlowAI를 유지합니다. main 및 기존 PR #1/#2는 수정·병합하지 않습니다. Phase 4·SNS 계정 연결·자동 게시·Docker/WSL/Linux 배포는 구현하지 않습니다.

| 검증 항목 | 결과 | 근거와 한계 |
|---|---|---|
| Cloud 전체 pytest | PASS | 147 passed / 1 skipped / 1 warning / 0 failed |
| 기존 Phase 2 회귀 | PASS | 기존 107개 테스트 유지; schema 기대 revision만 0003으로 갱신 |
| 신규 영상/음성/경로/보안 테스트 | PASS | 40개 추가; Fake는 실제 영상과 구분 |
| 실제 FFmpeg 3초 MP4 | PASS | H.264/yuv420p/1080×1920/AAC/2ch, ffprobe duration 3.021029초, 62,335 bytes |
| 한국어 샘플 프레임 | PASS | 실제 MP4에서 추출하여 한국어 제목/자막/출처/여백 확인; 전체 영상 품질 판정 아님 |
| Cloud Chromium/30초 MP4 | PASS | 실제 제작 POST·프레임 디코딩·미리보기·다운로드·재기동 파일 유지·모바일 |
| Windows Actions | PASS | 최종 실행 38479483734 success; 147 passed / 1 skipped / 0 failures / 0 errors |
| 실제 사용자 Windows 11 PC | NOT VERIFIED | 설치·권한·조직 정책·수동 종료·장기 운영 미검증 |
| Windows SAPI 음성 생성 | PASS | 설치 음성으로 비무음 WAV 및 5초 AAC MP4 샘플 생성, 청취 품질 판정 아님 |
| Windows TTS 음성 품질 | NOT VERIFIED | 실제 청취 및 한국어 발음 품질은 별도 검수 |
| 30/45/60초 최종 콘텐츠 품질 | NOT VERIFIED | 샘플/코덱/시간 검증은 사람의 전체 음성·내용·영상 검수를 대신하지 않음 |
| 실제 RSS 및 AI API | NOT VERIFIED | 기존 미검증 유지; 외부/유료 TTS API 구현 및 호출 없음 |

## 구현 기능 및 영상 제작 아키텍처

Video Studio → VideoCoordinator → RenderEngine protocol(FFmpeg/Fake) → TTSProvider(Offline/Fake/Windows SAPI) → Pillow 카드/FFmpeg → ffprobe → 독점 생성 출력 → DB 완료 상태 순서입니다.

- 저장 대본 선택/AI Studio 연결, 30·45·60초 선택, 음성/자막 크기·위치/장면 확인, 허가된 로컬 이미지 선택, 명시적 제작 POST, 진행률·오류·이력, 성공 MP4 미리보기/열기/다운로드/저장 경로 표시.
- Scene별 타이밍은 밀리초로 저장하고 선택 영상 길이로 비례 재배정합니다. 합계·연속성·양의 길이·자막 안전 영역을 검증합니다. 내레이션 WAV가 장면보다 길면 실패하며 내용을 자르지 않고 짧은 음성은 무음으로 채웁니다.
- 1080×1920, 9:16, 30fps, MP4/H.264/yuv420p/AAC를 생성합니다. 컷 장면 전환, 한국어 자막 burn-in, 제목·미확인 표시·대표 출처를 카드에 그립니다. 대표 출처 표시는 최대 3개 후보/2줄이며 전체 출처와 원문 링크는 DB·GUI에서 보존합니다.
- PNG/JPEG 로컬 소재(20MB·1600만 픽셀 이하)는 사용자가 assets에 복사하고 이용 권한을 확인해야 합니다. 외부 소재 없이 텍스트·배경·도형 기본 영상이 가능합니다. 원격 이미지/뉴스 영상 다운로드 없음.
- Fake는 `simulated`/playable=false로 저장하고 미리보기/다운로드를 거부합니다. Fake unit test를 실제 MP4 PASS로 표시하지 않습니다.

## DB 모델 및 파일 관리

0003 additive migration이 VideoProject(대본 revision/snapshot/출처), Scene(순서/시간/텍스트/소재), AudioTrack(Provider/voice/status), SubtitleTrack(크기/위치/cues), RenderJob(상태/진행률/고유 파일명/안전 metadata/오류/UTC)을 추가합니다. 기존 0001/0002 migration·기사·출처·점수·대본을 변경하지 않습니다. 이전 도구는 0001/0002/0003을 지원합니다. 업데이트 전 서버 종료와 데이터 백업이 필요합니다.

완성 MP4 기본 위치 `%LOCALAPPDATA%\NewsFlowAI\outputs\videos`; 로컬 소재 assets; 중간 파일 render-tmp/job-ID-random입니다. 출력 이름은 UUID이며 `xb` 독점 생성으로 기존 영상 덮어쓰기 금지, 경로 이동·symlink 차단, 디스크 여유 확인, 실패 시 새로 생성한 파일/임시 파일 정리를 수행합니다. 정상 완료는 임시 정리와 출력 검증 이후에 기록합니다. 같은 데이터 폴더의 thread guard/OS FileLock으로 단일 렌더를 제한합니다.

종료 시 cancel/FFmpeg kill/worker join으로 작업을 interrupted 처리하고, 강제 종료 후 재시작은 running을 interrupted로 바꾸며 자동 재실행하지 않습니다. 다른 프로세스의 활성 작업은 중단으로 변경하지 않습니다. 앱 소유 임시 폴더만 정리합니다. 강제 종료 시 완료 표시 전 고유 출력 고아 파일이 남을 수 있으나 GUI에서 성공 파일로 제공하지 않습니다. 정리 권한 오류 시 안전한 안내를 남기고 수동 확인이 필요합니다.

## FFmpeg/TTS 검증

FFmpeg/ffprobe 실행 파일 존재·버전·종료 코드와 제한시간을 검사합니다. 모든 실행은 `shell=False`/인수 배열이고 stdin은 사용하지 않습니다. 사용자 대본·자막은 명령/필터에 넣지 않고 이미지 픽셀로 변환합니다. concat은 생성된 단순 파일명만 사용하며 file/pipe 프로토콜만 허용합니다. ffprobe로 MP4/H.264/yuv420p/1080×1920/AAC 및 길이 오차 ≤0.25초를 검사합니다. API 키/토큰/비밀변수는 자식 프로세스 환경에서 제외합니다. raw stdout/stderr와 외부 예외 본문을 저장하지 않고 단계·정수 종료 코드만 오류 이력에 남깁니다.

Offline은 명시적으로 무음 PCM을 생성해 AAC 스트림으로 포함하며 발화로 주장하지 않습니다. Fake TTS는 호출/시간/WAV/오류를 검증합니다. Windows는 고정 packaged PowerShell script가 UTF-8 JSON을 데이터로 읽어 System.Speech/SAPI 설치 음성을 WAV로 합성합니다. `-Command`, 사용자 코드 삽입, ExecutionPolicy 완화, 외부 API 호출이 없습니다. OneCore 음성 모두를 노출하는 adapter는 아니며 설치된 SAPI 음성을 사용합니다. 로컬 Windows 음성이 없으면 Offline은 계속 사용할 수 있습니다. 청취·한국어 발음·프로젝트 전체 음성 품질은 NOT VERIFIED입니다.

Cloud 실제 명령: `.venv/bin/python tools/ci_video_validation.py --output /tmp/newsflow-phase3-final-mp4`. FFmpeg 7.1.5-0. 합성 로컬 이미지+한국어 카드 3장, 장면 각 1초, 무음 AAC. [구조화된 결과](phase3_evidence/cloud_video_result.json), [샘플 MP4](phase3_evidence/sample-3s.mp4), [실제 추출 프레임](phase3_evidence/sample_frame.png). 샘플 합성 소재의 사용 권한은 테스트 생성 코드에 있습니다. TTF 파일은 Git에 포함하지 않았습니다. CI의 Noto Sans KR은 공식 Google Fonts 고정 commit 및 SHA256 검사를 사용하며 SIL OFL 라이선스입니다. 설치 글꼴·직접 제작한 이미지 외 저작권 미확인 자산을 사용하지 않습니다.

## GUI 및 테스트 결과

`python -m pytest -q -rs`: 147 passed / 1 skipped / 1 warning / 0 failed. 기존 107개를 유지하고 신규 40개를 추가했습니다. 기존 DB migration 기대값 두 곳만 최신 revision으로 변경했고 기존 테스트를 삭제/skip하거나 timeout을 완화하지 않았습니다. skip은 기존 opt-in live RSS이며 warning은 기존 Starlette TestClient/httpx deprecation입니다. [Cloud pytest 원문](phase3_evidence/cloud_pytest.txt).

새 테스트는 프로젝트/scene/audio/subtitle 생성·시간·출처 snapshot·30/45/60 Fake 계획, Fake TTS, 렌더 오류·비밀값 미기록·디스크 부족·덮어쓰기 방지·로컬 소재 경로/권한/signature·같은/다른 coordinator 동시 제한·재시작 중단 복구·종료 중단·임시 정리 후 완료·GUI POST/CSRF/Origin:null 거부·Fake 미리보기 차단·FFmpeg argv/버전/종료/취소/probe·자막 안전 영역·Windows TTS argv·비밀변수 제외·잠금 권한 복구를 검증합니다.

중간 테스트에서 손상된 WAV의 EOFError가 정제되지 않는 FAIL 1건을 발견해 오류 경계에 포함했고 전체 회귀로 재검증했습니다. 실제 브라우저 검증을 강화하다 Playwright의 문자열 평가가 기존 CSP의 unsafe-eval 금지에 차단되는 FAIL을 확인했습니다. CSP를 변경하지 않고 DevTools의 video 속성 조회/호스트 측 polling으로 검증 코드를 고쳤습니다. 최종 실제 브라우저 결과는 아래에 기록합니다.

## 보안/저작권/미구현·미검증

PASS: 기존 CSRF/Origin/Host/SSRF/TLS/robots/HTML escape/CSP/no-referrer 유지. 신규 POST도 동일 보호. API 키 HTML/DB/로그/렌더 자식 프로세스 비노출. 로컬 파일·이미지 decoder·명령 인수·파일명·동시 실행·중단·원자적 상태 전이를 검사합니다. 허가된 소재/명시적 검토와 실행만 허용하며 영상 제작을 게시 승인으로 간주하지 않습니다. 영상에 미확인 보도/사람 검토 필요를 표시합니다.

미구현: 외부 유료 TTS·음성 복제·배경 음악·클립 영상 파일 합성·자동 소재 다운로드·음성별 타임스탬프 word highlighting·ASS/SRT export·전환 효과 편집·EXE Installer·자동 SNS 게시·Instagram/YouTube 연결·스케줄러·Phase 4. 장면별 burn-in 자막과 컷 전환, PNG/JPEG·기본 그래픽 영상에 범위를 한정했습니다.

NOT VERIFIED: 실제 RSS/AI API, 사용자 Windows 11 PC의 FFmpeg 설치/ACL/보안 제품/PowerShell 정책/Ctrl+C, 한국어 SAPI 발음, 45/60초 실제 렌더/모든 대본/소재 조합, 30/45/60초 전체 영상의 사람이 보는 최종 내용·영상·음성·저작권 품질. 짧은 샘플이나 자동 ffprobe 검증은 이를 대신하지 않습니다.

## 변경 파일

- src/newsflow/video/{engine,service,tts,__init__}.py 및 windows_tts.ps1: 엔진/어댑터/작업/음성/로컬 스크립트.
- db/models.py 및 db/migrations/versions/0003_video.py: 다섯 영상 모델 및 추가 schema.
- gui/video_routes.py, gui/templates/{video,base,ai}.html, static/{css/app.css,js/app.js}, main.py: Video Studio·연결·진행·미디어·shutdown/recovery.
- migrate_data.py, tests/{test_database,test_intelligence,test_video}.py: revision 지원/기대값·기존 회귀 유지·신규 40개 테스트.
- tools/{ci_validation,ci_video_validation,ci_prepare_font}.py: 실제 30초 GUI/3초 MP4/Windows TTS/검증된 한국어 CI 글꼴.
- .github/workflows/newsflow-phase3-windows.yml: Phase 3 브랜치 전용 Windows Python 3.12/FFmpeg/TTS/pytest/BAT/Chromium; 기존 workflow 수정 없음.
- .gitignore, .env.example, AGENTS.md, pyproject.toml, requirements-dev.lock, README.md, docs/architecture.md, 본 보고서/evidence: 저장 경계·승인 범위·Pillow 12.3.0 및 packaged PS1·Windows 운영/검증 문서.

## Git/Draft PR/Phase 4

기준 f9f9f0f, feat/newsflow-phase3. 새 Draft PR은 feat/newsflow-phase2를 base로 하여 영상 기능만 검토합니다. PR 번호는 GitHub 실제 부여 번호를 보고합니다. 기능 커밋 `577a9e3bbdf6090b126ab28d380451e9b3d3c643`, Windows Chrome/미디어 진단 보완 `f49cca70cbeed81f9bcda5ae11c5a06ed70dbbc4`. [Draft PR #3](https://github.com/jsbae1979-prog/JSBAE/pull/3)는 OPEN/DRAFT, base feat/newsflow-phase2, head feat/newsflow-phase3입니다. 기존 PR #1/#2는 수정·병합하지 않습니다. 최종 증거·문서 갱신은 별도 docs 커밋이며 `git log -1 -- docs/reports/phase3_report.md`로 해당 커밋을 확인할 수 있습니다. 기존 PR #1/#2, main, 다른 프로젝트는 변경하지 않습니다.

**Phase 4 진입: 사용자 승인 전 불가.** Phase 3의 개발 검증 후 실제 Windows PC/한국어 음성/전체 30·45·60초 품질·사실/소재 권한을 검수하고 사용자의 Phase 3 승인 및 별도 Phase 4 게시 정책을 확정해야 합니다. 보고서와 Draft PR 제출 후 개발을 중단하며 main 병합·SNS 계정 연결·게시를 수행하지 않습니다.


### Cloud 실제 서버/브라우저 실행

`.venv/bin/python tools/ci_validation.py --mode cloud --browser-executable /usr/bin/chromium --output /tmp/newsflow-phase3-verified-cloud` 최종 PASS. 기존 RSS/AI Studio POST, 실제 30초 FFmpeg 제작 POST 303/정상 Origin, progress 100/status success, Chromium readyState 4·media error null/1080×1920·1초 위치 프레임 디코딩, MP4 다운로드, 390px 모바일 overflow 없음, 서버 재기동 후 job success 및 파일 조회를 검증했습니다. `.video` 미리보기는 검증된 실제 MP4이며 Fake가 아닙니다. 음성은 명확한 Offline 무음이고 최종 콘텐츠 품질·실제 한국어 음성 청취·사용자 Windows PC 검증을 의미하지 않습니다. [실제 실행 결과](phase3_evidence/cloud_result.json), [Video Studio 화면](phase3_evidence/video_studio.png), [모바일](phase3_evidence/mobile.png).


### Windows Actions 최종 실제 실행

[실행 38479483734](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38479483734), 검증 SHA f49cca7, job 115578274999, workflow/job conclusion success입니다. [Windows pytest](phase3_evidence/windows_pytest.json): 148 tests / 147 passed / 1 skipped / 0 failures / 0 errors. Windows 경고 수는 JUnit 집계에 포함되지 않아 NOT VERIFIED입니다.

[Windows 실제 MP4/TTS 결과](phase3_evidence/windows_video_result.json): FFmpeg 7.1.1-essentials_build-www.gyan.dev, 실제 3초 샘플 H.264/1080×1920/AAC/2ch/3.021029초/56,520 bytes PASS. 설치된 SAPI 음성으로 1.51초 비무음 PCM 발화를 생성하여 5.021029초 H.264/AAC MP4(46,855 bytes)로 렌더했습니다. SAPI 샘플은 영어 “News flow.”이며 한국어 발음/사람 청취 품질은 NOT VERIFIED입니다.

[Windows 실제 BAT/GUI 결과](phase3_evidence/windows_result.json): run.bat 실제 실행, 기본 LOCALAPPDATA, 서버 기동/종료/재기동, 합성 기사 저장/조회, 중복/포트 충돌, 기존 GUI/AI Studio, Video Studio 제작 POST/완성 30초 MP4/미리보기/다운로드/재기동 파일 유지/모바일 overflow 없음 PASS. Windows는 설치된 Google Chrome(Chromium 기반)을 사용했습니다. 실제 Origin http://127.0.0.1:8765, video dimensions 1080×1920, H.264/AAC canPlayType probably, readyState 4, media error null, 프레임 디코딩 PASS. Windows 종료는 taskkill 프로세스 트리이며 사용자 PC의 Ctrl+C 검증이 아닙니다.

최초 [실행 38478536088](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38478536088)는 렌더·SAPI·147개 회귀·BAT·영상 작업 success까지 통과했으나 번들 Chromium의 미리보기 단계에서 AssertionError로 전체 FAIL이었습니다. [최초 GUI 실패 결과](phase3_evidence/windows_initial_result.json)를 보존했습니다. 당시 원문 로그는 Cloud에서 조회하지 못했고 미디어 상태의 세부 진단이 부족하여 최초 실패의 정확한 내부 디코더 원인을 확정하지 않습니다. H.264/AAC를 지원하는 설치 Chrome 채널을 명시적으로 선택하고 dimensions/readyState/error/support 진단을 추가한 뒤 동일 해상도·프레임·POST·품질 구분 검사를 유지하여 최종 실행이 PASS했습니다. 검사 제거/skip/continue-on-error/보안 정책 완화는 없습니다.

CI의 준비 단계는 임시 Windows Runner에 FFmpeg 및 검증된 Noto Sans KR 글꼴, 설치 Chrome을 준비합니다. 사용자 PC/Cloud 네트워크·권한·비용 설정을 변경하지 않았습니다. raw Actions 로그와 artifact 파일 다운로드는 NOT VERIFIED이며 결과는 실제 GitHub check annotation 및 workflow/job conclusion으로 확인했습니다. Node 20 action의 Node 24 전환 안내는 기능 실패와 구분합니다. Cloud 기능/브라우저 증거는 577a9e3의 동일 운영 코드, Windows 최종 증거는 CI 채널·진단만 보완한 f49cca7입니다.

**최종 개발 검증: PASS (명시된 미검증 항목 제외). Phase 3 사용자 승인 대기.** Phase 4 진입과 실제 게시 승인을 의미하지 않습니다. 보고서·검증 증거·Draft PR 제출 후 개발을 중단합니다.
