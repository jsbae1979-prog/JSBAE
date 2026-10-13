# Phase 1 아키텍처

## 계층과 실행 흐름

```text
GUI: Jinja2 / local CSS / JS polling
  -> FastAPI routes (입력 검증, 검색, 설정)
  -> CollectionCoordinator (OS file lock, background thread, recovery)
  -> NewsService (per-source transaction, duplicate provenance, scores)
  -> Collector (defusedxml + feedparser; title/summary/link only)
  -> RSSAdapter protocol
     -> PublicRSSAdapter (robots + redirect policy)
        -> PublicTransport (public DNS validation, pinned socket, verified TLS)
     -> FakeRSSAdapter (offline fixtures)
  -> SQLAlchemy -> SQLite (WAL, foreign keys, UTC adapter)
```

애플리케이션 팩토리가 설정·DB·마이그레이션·수집 어댑터를 연결합니다. UI가 외부 서비스를 직접 호출하지 않습니다. 라이프사이클 종료 시 수집 스레드를 종료하고 DB 연결을 닫습니다. 셧다운은 현재 진행 중인 유한 RSS 작업을 기다릴 수 있습니다.

## 데이터 모델

- NewsSource: 공개 피드 URL, 이름, 활성 여부, 등록시각.
- NewsArticle: 제목, RSS가 제공한 원문 링크, 중복 비교용 canonical URL, 대표 출처, 요약, 카테고리, 확인 가능한 발행시각, 수집시각.
- ArticleMention (추가): 같은 제목으로 묶인 다른 출처의 링크·출처명. 중복 제거 이후에도 복수 출처 평가의 근거를 보존합니다.
- CollectionRun: 실행 상태, 시작·종료시각, 신규/중복/성공/실패 수.
- ArticleScore: 0~100점 합계, 평가 가능한 최대 합계, 항목별 nullable 점수·근거·평가 상태, 평가시각.
- AuditLog: 작업·출처 참조, 이벤트, 레벨, 민감정보를 제외한 메시지, 기록시각.
- AppSetting (추가): GUI에서 변경한 요청 타임아웃.
- alembic_version: DB 스키마 revision.

DB에는 UTC를 naive datetime으로 직렬화하지만 타입 어댑터가 UTC-aware 값을 반환합니다. timezone 없는 입력은 거부합니다. 발행시각을 얻지 못하면 NULL입니다. API와 UI는 UTC를 명시합니다.

## 원자성·실패 모델

피드의 항목 전체를 먼저 파싱합니다. 한 출처의 기사/중복 링크/성공 로그를 한 트랜잭션에 저장하고, 예외가 나면 롤백 후 별도 오류 로그를 남깁니다. 이후 다른 출처 수집을 계속합니다. 완료 상태는 `success`, `partial`, `failed`, `empty`; 크래시 후 `interrupted`입니다. 전체 수집을 하나의 트랜잭션으로 묶지 않은 것은 부분 성공을 보존하기 위해서입니다. 대표 기사는 삭제하지 않습니다.

파일 잠금은 요청 처리 전에 확보해 동시 수집을 409로 거부합니다. 파일 잠금 자체는 OS가 크래시 시 해제합니다. 다른 프로세스가 잠금을 소유한 경우 그 실행을 중단 상태로 변경하지 않습니다. 공유 네트워크 파일시스템의 잠금 동작은 지원 범위 밖입니다.

## 점수·중복 정책

URL 중복은 unique canonical URL로 차단하고 알려진 추적 파라미터만 제거합니다. 원본 URL은 별도로 보존합니다. 제목은 Unicode 정규화 후 비교하며 날짜가 확인되면 72시간 범위, 유사도 0.92 이상, 숫자 사실 일치 조건을 사용합니다. 날짜를 모르면 정규화된 정확 일치만 묶습니다. 중복 비교는 현재 O(기사 수 × 신규 항목 수)로 Phase 1의 로컬 규모를 대상으로 합니다.

RSS 근거 없는 항목은 nullable 상태로 저장합니다. 출처 이름은 RSS source 메타데이터 또는 등록 피드 이름을 이용하므로 실제 독립 언론 여부를 완전히 검증하지 못합니다. 분류·중요도·영상 적합성·국내 연관성은 명시된 키워드 기반 휴리스틱입니다. 점수는 수집 종료 시 평가하며 탐색 화면에서 실제 조회수로 표현하지 않습니다.

## 보안 경계

기본 GUI는 127.0.0.1:8765. 외부 공개 바인딩은 설정 검증에서 거부합니다. 상태 변경은 CSRF 서명 토큰과 cookie 일치, Origin과 Host 검증이 필요합니다. CSP로 외부 스크립트와 프레임 삽입을 차단합니다. 로컬 사용자의 악성 프로세스까지 방어하는 인증체계는 아닙니다.

외부 요청은 등록/리디렉션 URL 문법 검사 → 모든 DNS IP 검사 → 검증된 IP 직접 연결 → 원래 호스트명을 이용한 TLS 인증서 검증 순서입니다. DNS rebinding 시 두 번째 조회를 하지 않습니다. 사설·예약·멀티캐스트 주소와 기본 포트 외 연결을 금지합니다. DNS 조회는 요청자가 제한시간 이후 빠져나올 수 있도록 daemon resolver를 사용합니다. OS DNS 작업 자체를 강제로 취소하는 것은 지원하지 않습니다. 제한 환경에서 보호를 우회해 실패를 성공으로 바꾸지 않습니다.

robots.txt 확인 실패는 보수적으로 수집을 중단합니다. 리디렉션 목적지마다 정책을 다시 확인합니다. RSS 피드 이용 권한은 운영자가 확인하도록 GUI에서 동의를 요구합니다. 별도의 robots request-rate/crawl-delay 대기는 구현하지 않아 해당 출처는 실패 처리합니다.

## 구조 변경 이유

요구한 기본 폴더 구조를 유지하되 기사 상세 템플릿, 보안·실제 네트워크 테스트, XML fixtures, requirements-dev.lock를 추가했습니다. 마이그레이션은 설치 패키지에서도 접근 가능하도록 `newsflow/db/migrations/` 안에 두었습니다. DB 모델은 중복 provenance와 설정 영속성을 위해 두 테이블을 추가했습니다.


## Phase 2 · AI News Intelligence

AI Studio 라우트 → IntelligenceService → Provider Protocol(Offline/Fake/OpenAI) → 엄격한 Pydantic 분석/대본 스키마 → SQLAlchemy 트랜잭션의 구조입니다. 외부 API는 고정 OpenAI HTTPS 엔드포인트에만 전송하고 기본 TLS 인증서 검사와 리디렉션 거부를 적용합니다. 사용자가 명시적으로 Provider를 선택하고 해당 실행의 전송/비용 동의를 해야 호출합니다. 템플릿이나 자동 RSS 수집은 AI를 호출하지 않습니다.

0002는 IntelligenceRun(상태·Provider·모델/옵션·불변 기사 근거·분석 결과·오류·UTC 시각), ContentDraft(생성 실행 참조·길이·내용·불변 출처·revision·검토 필요 상태·UTC 시각)를 추가합니다. 기존 0001 마이그레이션은 수정하지 않습니다. 초안 수정은 revision 조건부 UPDATE로 충돌을 감지하고 원문 링크/근거를 변경하지 않습니다. 실행 도중 종료되면 다음 기동에서 interrupted로 기록하고 외부 호출을 자동 재시도하지 않습니다.

분석은 현재 선택한 최대 10개 기사에 대해 제목 유사도 0.65 후보 그룹을 제공하고 기존 ArticleScore와 ArticleMention을 보존합니다. 그룹은 Phase 1 중복 제거와 별개이며 날짜·수치가 다른 기사도 후보일 수 있으므로 동일 사건으로 확정하지 않습니다. 비교는 출처별 제목/요약과 AI의 근거 설명을 함께 표시하고, 신뢰도 미평가·사실 미확인을 서버가 고정합니다.

외부 호출은 동기 FastAPI 작업 스레드에서 유한 요청으로 실행합니다. 폼은 실행 중 버튼을 비활성화하고 완료 또는 오류를 표시합니다. 별도 작업 큐/주기 실행/자동 재시도는 없습니다. 기사 본문은 가져오지 않고 입력 근거와 출력 크기를 제한합니다. API 키는 환경변수로만 읽으며 DB/템플릿/오류 메시지에 넣지 않습니다. Schema 유효성은 사실 검증을 의미하지 않고, 장면 길이 합계는 계획된 길이입니다. 자동 출처 탐색·외부 팩트체크·TTS/영상/SNS 게시·승인 워크플로는 미구현입니다. 사람 검토 상태에서 자동 승인/게시로 전환하는 경로가 없습니다.

## Phase 3 · Video Production

Video Studio routes → VideoCoordinator(OS file lock + process guard + one background worker) → RenderEngine protocol → FFmpegAdapter/FakeRenderAdapter → TTSProvider(Offline/Fake/Windows SAPI) 구조입니다. 사용자의 보호된 POST와 대본/출처·소재 권한 확인으로만 실행합니다. 유료/외부 TTS, SNS/OAuth, 자동 게시 경로는 없습니다.

Migration 0003은 VideoProject(초안 revision/snapshot/출처/길이), Scene(순서/밀리초 타이밍/내레이션/자막/허용 로컬 소재 파일명), AudioTrack(Provider/voice/status), SubtitleTrack(글자 크기/안전 위치/타임 cue), RenderJob(status/progress/고유 output_name/검증 metadata/UTC 시각)를 추가합니다. 모델·마이그레이션은 기존 데이터 구조를 변경하지 않습니다. 렌더 중 대본을 수정해도 고정 snapshot을 사용합니다.

Pillow는 제목·한국어 자막·출처를 1080×1920 카드로 그립니다. 로컬 이미지는 허용 폴더·PNG/JPEG signature·파일/픽셀 크기를 검증하고 임시 PNG로 복사합니다. FFmpeg 필터에 사용자 문자열을 삽입하지 않습니다. 각 장면의 오디오는 Windows WAV 또는 명확한 Offline 무음입니다. 짧으면 apad, 배정 시간보다 길면 실패 처리합니다. 장면별 H.264/yuv420p/AAC MP4를 생성하고 안전한 생성 파일명만 포함하는 concat manifest 및 file/pipe protocol 제한으로 합칩니다. 기본 컷 전환입니다.

FFmpeg/ffprobe 버전과 반환 코드를 확인하고 ffprobe로 MP4/H.264/yuv420p/1080×1920/길이 오차 0.25초 이하/AAC를 검사한 뒤 결과를 독점 생성(xb)으로 저장합니다. 사용자 영상은 덮어쓰지 않습니다. 모든 외부 프로세스는 shell=False, 인수 배열, 제한시간과 비밀변수를 제외한 자식 환경을 사용합니다. 임의 text를 PowerShell code로 넣지 않고 고정 packaged script가 UTF-8 JSON을 데이터로 읽어 SAPI를 호출합니다. 실행 정책·TLS 검증을 완화하지 않습니다.

UI는 GET JSON으로 상태를 조회하고 완료 시 성공한 로컬 MP4만 FileResponse로 preview/download(Range 지원)합니다. 경로는 사용자 입력이 아닌 DB의 고유 basename만 사용합니다. 실패 원인은 안전한 단계/오류 종류/정수 종료 코드만 저장하며 stdout/stderr와 API 키는 로그에 넣지 않습니다. Fake는 simulated 상태와 playable=false로 실제 MP4와 구분합니다. 종료 시 cancel 신호/프로세스 kill/worker join으로 중단하며, 강제 종료 후 OS lock이 해제되면 running을 interrupted로 바꾸고 자동 재실행하지 않습니다. 원본 파일은 보존하고 앱 소유 임시 작업 폴더만 정리합니다.

자료 폴더는 기존 사용자 root 안의 outputs/videos, render-tmp, assets입니다. 0001/0002의 기존 데이터/저장 위치는 유지합니다. 로그는 DB 작업 이력과 기존 로컬 실행 로그를 이용하며 raw FFmpeg stderr를 저장하지 않는 것이 민감정보 제거 정책입니다. 로컬 단일 사용자 도구로, 악성 동일 사용자 프로세스의 데이터 폴더 변조까지 방어하는 서비스 인증 구조는 아닙니다.

## Phase 4A · SNS Publishing Foundation

Publishing Studio routes → PublishingService (로컬 파일·독립 ffprobe·SHA256·사용자 검토·revision CAS) → additive 0004/PublishDraft·PlatformAccount·PublishValidation·PublishJob·PublishAttempt·PublishEvidence입니다. 실제 Publisher/OAuth 연결·콜백·게시 경로는 존재하지 않습니다. Instagram/YouTube adapter의 prepare는 메모리의 명세 후보만 작성하고 publish/connect는 승인 여부와 무관하게 거부합니다. 실제 외부 HTTP transport를 만들지 않았습니다.

파일은 성공한 RenderJob의 고유 output basename으로만 접근하고 symlink/이동/빈 파일/2GiB 초과를 거부합니다. ffprobe는 file,pipe protocol whitelist와 mov demuxer, 제한시간·정제된 자식 환경으로 실행해 악성 playlist의 외부 요청을 차단합니다. 초안 시점 해시와 독립 스트림 검사를 비교하고 검증 전/후 변경을 감지합니다. 검증 저장은 draft revision 조건부 UPDATE로 stale 결과를 거부합니다. 모든 실제 준비 상태는 blocked이며 계정/API/공식 정책 확인 전 ready/success로 승격할 수 없습니다.

Fake 시뮬레이션은 최신 로컬 검증 및 명시적 승인만으로 테스트하고 실제 어댑터를 허용하지 않습니다. 플랫폼/대상 계정/media hash UNIQUE identity와 conditional revision UPDATE로 먼저 writer reservation/job/attempt를 저장한 뒤 adapter를 한 번 호출합니다. 수정 후에도 같은 영상의 같은 대상은 재실행하지 않습니다. 실패/만료/결과 불명·예외/불완전 실행은 unknown 등으로 관리하고 성공으로 추정하지 않으며 자동 재시도하지 않습니다. repository의 명시적 recovery가 불완전 Fake를 unknown으로 표시할 수 있지만 GUI에 시뮬레이션 실행/복구 경로는 없습니다. 요청 revision/검증 ID/메타데이터 snapshot을 evidence에 보존해 향후 수정과 구분합니다.

토큰값 DB 컬럼이나 HTML 입력이 없습니다. credential_ref는 향후 비밀 저장소의 opaque 식별자용이며 지금은 NULL입니다. TokenBundle은 SecretStr/ValidationError 입력 마스킹이고 FakeCredentialVault는 휘발성/만료·취소 검증만 지원합니다. 실제 Windows 암호화/OS vault와 OAuth code exchange는 Phase 4B 승인 후 구현해야 하며 UnavailableCredentialVault로 차단합니다. 공식 웹 접근 불가 항목과 공식 GitHub 스키마/SDK에서 확인한 사실, 앱 준비 정책을 구분합니다. API 연구 URL은 evidence에 저장만 하며 renderer/publisher가 자동 fetch하지 않습니다.
