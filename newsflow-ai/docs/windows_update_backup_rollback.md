# Windows 11 전환·백업·롤백 절차 — 실행 승인 전 설계

대상 코드 `0a59bfb41eec6b243e4470f67cd53c1e7cd07e52`, PR #35. 이 문서는 **운영 설치/업데이트 승인이나 자동 실행 스크립트가 아니다.** 실제 설치 경로·데이터 경로·현재 SHA·Windows 계정은 사용자 PC에서 확인해야 한다. Cloud에서는 원본 사용자 데이터를 확인하지 않았다.

## A. 경로와 현재 버전 확인 — 앱을 새로 실행하지 않음

1. 사용자가 실제로 실행하는 바로가기/BAT의 프로젝트 폴더를 확인한다. 과거 `C:\Codex\NewsFlowAI`를 운영 경로로 가정하지 않는다.
2. 해당 Git 저장소의 branch·HEAD·tracked diff·untracked 목록을 읽기 전용으로 확인한다. 로컬 OAuth 수정 등 미커밋 파일이 있으면 원본·binary patch·SHA-256을 별도 사설 백업한다. `reset --hard`, `clean`, 자동 stash/checkout 금지. Git 없는 설치본이면 파일 manifest와 배포본 출처부터 확보한다.
3. **실제 실행 프로세스/실행 방식의** 데이터 경로를 확인한다. `NEWSFLOW_DATA_DIR`가 지정되면 그 경로, 없으면 실행 환경의 `%LOCALAPPDATA%\NewsFlowAI`다. 자동 시작 작업은 명시적 data-dir을 사용할 수 있다. 현재 PowerShell의 환경이 기존 프로세스와 같다고 가정하지 않는다. LocalCache·Microsoft Store Python 경로가 실제로 확인되면 그 경로를 보존한다. 중복 DB가 발견되면 어느 것이 운영 DB인지 판정할 때까지 중단한다.
4. 키 값이나 토큰을 출력하지 않는다. Secret Store/환경변수 사용 여부만 기록한다. 설정 파일을 GitHub에 첨부하지 않는다. 운영 DB 내용을 외부로 보내지 않는다.
5. 현재 Python 실행 파일/버전, FFmpeg·ffprobe 실행 파일/버전, 한국어 음성·글꼴, Supertonic 모델 경로, 프로젝트 밖 참조 자료 위치를 기록한다.

읽기 전용 명령 예시(경로 입력 후 검토용, 실행·변경 명령 아님):

```powershell
$projectRoot = Read-Host '실제 newsflow-ai 프로젝트 폴더'
git -C $projectRoot status --short
git -C $projectRoot branch --show-current
git -C $projectRoot rev-parse HEAD
git -C $projectRoot diff --stat
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
Get-Command py,python,ffmpeg,ffprobe -ErrorAction SilentlyContinue |
  Select-Object Name,Source
```

프로세스·작업 스케줄러의 전체 명령줄, 환경변수 전체, OAuth JSON을 보고서/채팅에 붙여 넣지 않는다. 포트가 비어 있다는 것만으로 백그라운드 worker가 없다고 판정하지 않는다.

## B. 실행 상태 확인과 안전한 중지 — 별도 사용자 승인 후

1. 활성 제작 예약·OS 자동 시작 작업·미완료 수집/분석/음성/렌더/AI 장면/게시 작업을 확인한다. 작업별 ID·현재 단계·결과 불명 여부를 **로컬 사설 기록**으로 남긴다.
2. 실행 중인 운영 앱이 있다면 추가 작업을 시작하지 않는다. 진행 작업의 완료/안전한 취소를 사용자가 결정한다. 유료 제출 중이거나 게시 결과가 불명인 상태에서 무작정 종료/재실행하지 않는다.
3. 재진입을 막기 위한 예약·OS 작업 일시 중지는 **별도 승인한 항목만** 기존 UI/Windows 도구로 수행한다. 현재 요청은 실제 OS 작업 변경을 허용하지 않는다. 해당 설정 변경 전후도 기록하고 원래 설정을 보존한다.
4. 기존 콘솔의 Ctrl+C로 종료한 후 `server_stop`, 서버/자식 worker 종료, 포트 해제, 열린 파일 핸들을 확인한다. 강제 taskkill로 일관성을 얻었다고 주장하지 않는다. 정상 종료가 안 되면 백업·업데이트를 중단하고 원인을 별도 조사한다.
5. `server-*.lock`, `migration.lock`, `render.lock`, `autopilot.lock`, `scheduler.lock`, collection/credential 관련 lock 파일은 존재만으로 실행 상태를 뜻하지 않는다. 살아 있는 소유자가 있으면 중단한다. lock 파일을 삭제해 실행을 강제하지 않는다.

**중단 기준:** 프로세스/실제 데이터 경로 불명, 자동 시작 재진입 가능, 유료/게시 결과 불명, 쓰기 작업 진행, 안전한 종료 미확인.

## C. 하나의 복원 지점으로 백업

백업 위치는 위에서 확인한 설치·데이터 경로와 **서로 중첩되지 않는**, 사용자가 승인한 사설 NTFS 위치를 선택한다. 날짜(UTC 또는 KST 명시)+GUID로 새 디렉터리를 만들고 기존 디렉터리가 있으면 실패시킨다. 공용/동기화 업로드 폴더를 기본값으로 사용하지 않는다. 예시 이름은 `NewsFlowAI-restorepoint-<시각>-<GUID>`이며 실제 드라이브는 미확정이다.

권장 복원 지점 구성:

```text
restorepoint-<시각>-<GUID>/
  code/                 이전 SHA·Git bundle/추적 소스·미커밋 patch·확인한 미추적 자료
  data/raw/             실제 데이터 루트 전체의 정지 시점 복사본
  data/canonical.db     raw 복사본에서 생성·검증한 SQLite 독립 스냅샷
  external-media/       별도 경로 자료와 원래 경로 매핑(있는 경우)
  runtime/              Python/의존성/도구 버전·실행 방식·ACL 복원 지침(비밀값 제외)
  manifest.json         파일 상대 경로·크기·SHA-256, 코드 SHA·DB revision·파일 수/총 bytes
  VERIFIED              모든 확인 완료 후에만 기록하는 완료 표식
```

이 구조는 **절차 설계**이며 운영용 백업 도구를 개발한 것이 아니다. CI에는 합성 자료로만 이 절차를 재현하는 pytest helper가 있다. 그 helper를 운영 데이터에 사용하지 않는다.

백업 순서:

1. 여유 공간을 실제 파일 크기로 계산한다. raw 전체+canonical DB+검증 작업 복사본+업데이트/복원 staging+안전 여유가 각각의 대상 볼륨에 있어야 한다. 추측으로 몇 GB면 충분하다고 하지 않는다.
2. 원본을 정지 상태로 유지하며 **전체 데이터 루트**를 복사한다. DB만 추출하거나 outputs만 복사하지 않는다. 알려지지 않은 사용자 하위 폴더도 누락하지 않는다. symlink/junction/reparse point는 무조건 따라가지 말고 대상·권한·별도 백업 필요성을 확인한다. 접근 거부·이름 충돌·링크·복사 도중 변경이 있으면 중단한다.
3. `newsflow.db`, `newsflow.db-wal`, `newsflow.db-shm`, 존재하는 journal 등은 같은 정지 시점의 한 세트로 raw에 보존한다. WAL을 임의 삭제하거나 main DB만 복사하지 않는다. **실행 중인 DB 파일의 단순 복사는 금지**한다.
4. 원본과 raw의 파일 수·상대 경로·크기·SHA-256을 비교한다. 복사 전후 원본 목록/해시도 같아야 한다. 복사 프로그램 종료 코드만으로 성공 판정하지 않는다. ACL/소유자 보존은 내용 해시와 별도 검토한다. `shutil.copy2`나 일반 파일 복사가 Windows ACL까지 보존한다고 가정하지 않는다.
5. raw는 봉인한다. 별도 **검증용 복사본**에서 SQLite로 WAL을 반영한 `.backup`/Python `sqlite3.Connection.backup` 독립 DB를 만든다. 원본이나 봉인 raw에 checkpoint/마이그레이션/앱 시작을 실행하지 않는다.
6. canonical DB의 `PRAGMA integrity_check` = `ok`, `foreign_key_check` = 빈 결과, revision·테이블별 행 수/내용 지문을 확인한다. 원본 WAL의 커밋 행이 포함되는지 검증한다. raw와 canonical의 DB 파일 해시는 달라도 논리 데이터가 같을 수 있으므로 두 종류의 해시를 별도로 기록한다.
7. 코드 SHA와 DB revision, 설정·credential reference·암호문·미디어·승인 기록을 함께 묶는다. 이전 코드의 Git bundle은 선행 객체 없이 복원 가능한지 검증한다. 과거 venv를 새 Python에 복사하지 말고 이전 Python/의존성 재구축 자료를 보존한다. `.git` 인증 설정이나 OS 자격 증명을 무차별 수집하지 않는다.
8. 새 임시 위치로 복원 연습 후에만 `VERIFIED` 표시를 기록한다. 실패·부분 복사는 성공 표식을 만들지 않고 로컬에서 격리한다. 백업 실패이면 업데이트 금지. 다음 시도는 새 GUID 경로를 사용하며 이전 백업을 덮어쓰지 않는다.

**비밀정보:** DPAPI 암호문과 DB credential reference는 한 세트다. 같은 Windows 사용자/SID·프로필의 DPAPI master key 접근이 필요하다. 다른 PC/계정, 재설치/암호 재설정 이후 복호화 가능성을 보장하지 않는다. 환경변수/별도 Secret Store의 키는 데이터 폴더 복사에 포함되지 않을 수 있다. 별도 승인된 비밀정보 보관/재등록 계획만 세우고 평문 export·로그·Actions 업로드는 하지 않는다. Meta 인증 중계 서버의 App Secret은 PC 백업 대상이라고 가정하지 않는다.

## D. 업데이트 전 격리 검증과 전환 게이트

1. 현재 SHA·미커밋 변경·DB revision과 승인된 대상 SHA를 대조한다. 이 작업에서 승인된 것은 검증 준비뿐이다. 이후 실제 반영할 SHA는 다시 확인한다. main 병합·기존 로컬 변경 덮어쓰기 금지.
2. `VERIFIED` 복원 지점과 복원 가능성을 확인한다. 원본/백업 데이터는 유지하고 새 코드 폴더·별도 venv를 준비한다. 소스·템플릿·CSS/JS·필요한 의존성만 업데이트 대상으로 한다. `.env`, 로컬 모델, 사용자 업로드/설정/키는 소스로 덮지 않는다.
3. Python 3.12/3.14만 사용한다. 기존 BAT는 `.venv`가 있으면 그대로 사용하며 버전 불일치 시 실패한다. 설치 fingerprint 변경 시 패키지 설치가 발생할 수 있다. 사용자 승인 없이 Python 교체/네트워크 설치/FFmpeg 경로 변경을 진행하지 않는다. `pip check`와 FFmpeg/ffprobe 경로·버전 확인이 실패하면 중단한다.
4. 실제 DB는 먼저 사설 복사본에서 **migration만** 검증한다. 코드/DB 조합, revision, 기존 테이블·행·외래키·미디어 해시를 비교한다. 이 복사본을 앱으로 여는 것은 다른 문제다. 저장된 키·예약·진행 작업이 있는 운영 복사본은 자동으로 실행하지 않는다.
5. GUI/시작 검증은 새 합성 프로필로 먼저 한다. 실제 키 포함 복사본을 테스트 앱에서 로드하거나, 동일 예약/게시를 두 프로필에서 실행하면 안 된다. 필요하면 별도 승인된 격리/외부 통신 차단을 준비하되 TLS/SSRF/CSRF를 완화하지 않는다.
6. 원래 운영 경로로 돌아갈 때도 **별도 사용자 재시작 승인**이 필요하다. 아직 살아 있는 프로세스/다른 버전/8765 점유가 없어야 한다. 포트 충돌 시 다른 포트로 자동 전환하지 않는다.
7. 현재 코드 시작은 `migrate(head)`와 credential·수집·AI·영상·게시 상태 복구를 수행한다. 일반 시작은 AI 영상 worker를 깨울 수 있고, 제작 예약 실행기와 게시 일정 관리기도 시작한다. `automatic_start`는 전체 읽기 전용/무작업 모드가 아니다. 모든 자동 재개를 차단하는 공통 maintenance 옵션은 없다.
8. 승인 후 실행 시 `127.0.0.1:8765/health`, 홈·기사·대본·내 영상·설정·게시 준비를 **조회만** 확인한다. 기존 기록/미디어·계정 참조·검토/승인 상태와 예상된 복구 변경을 대조한다. 새 제작·OAuth·업로드/게시 승인은 별개다.
9. 실패·데이터 누락·예상 밖 복구·새 네트워크 동작이 있으면 전환 중단. 자동 재실행/재제출 금지. 운영 앱을 반복해서 켜 migration/복구를 재시도하지 않는다.

**기존 `python -m newsflow.migrate_data`는 이 전환의 전체 백업/복원 도구로 사용하지 않는다.** 지원 revision이 0001~0015이고 DB·session.key만 복사하며 일부 예약 상태를 변경한다. 현재 0016~0018을 거부하고 미디어·API 키·OAuth vault 전체를 옮기지 않는다. 이 제한을 우회하거나 도구를 수정하지 않았다.

## E. 실패 시 롤백

1. 실패한 새 앱과 자식 worker를 안전하게 종료하고 자동 재진입을 차단한다. 실패 후 DB·로그·산출물은 별도 사설 보존한다. 원인 판단 전에 삭제하지 않는다.
2. 백업 이후 외부 유료 요청/업로드/토큰 회전이 있었다면 **즉시 단순 롤백 금지**. 과거 DB로 돌아가면 성공 이력이 사라져 중복 생성·게시되거나, 회수된 토큰/과거 승인을 되살릴 수 있다. 결과 불명은 공급사 확인/별도 사용자 판단이 필요하며 자동 재시도하지 않는다.
3. 백업 manifest와 canonical DB 해시를 다시 확인한다. 새 빈 복원 staging에 raw 전체를 복사한다. 별도 canonical DB를 사용할 경우 staging의 main/WAL/SHM 세트를 교체하여 **기존 실패 DB의 WAL과 절대 섞지 않는다**. 이 처리는 새 staging에서만 수행하며 원본·봉인 백업을 수정하지 않는다.
4. 같은 복원 지점의 이전 코드·그 코드에 맞는 Python/의존성·DB·설정·암호문·미디어를 함께 준비한다. 앱을 켜기 전에 integrity/foreign key/파일 해시·계정 reference·게시 성공/실패/불명/승인 기록을 확인한다.
5. **Alembic downgrade로 운영 롤백하지 않는다.** 0018의 downgrade는 `image_post_deliveries`, `image_posts`를 삭제하고, 다른 revision도 테이블/열을 삭제한다. 데이터 보존 롤백은 검증된 업데이트 전 스냅샷 복원이다. 코드만 되돌리거나 구버전이 신규 스키마를 읽을 것이라 가정하지 않는다.
6. 복원 staging이 부분 실패하면 성공 표시/재시작 금지. 기존 대상에 merge copy하지 않는다. 다음 시도는 새 빈 위치에서 시작한다. 원래 운영 경로 복원·실행 전환은 사용자 승인 후에만 하며 기존 실패본을 보존한다.
7. 복원 후에도 DPAPI는 같은 계정에서 확인해야 한다. 실토큰 만료·회수·공급사 상태는 로컬 파일 해시로 증명되지 않는다. 실제 재인증/재발급은 별도 승인 범위다.

## F. 사용자 PC 점검 체크리스트

현재 단계에서는 모든 PC 항목이 **NOT VERIFIED**다. 아래 체크가 완료되기 전 운영 전환하지 않는다.

- [ ] 실제 프로젝트 경로, branch/HEAD, 미커밋 파일·미추적 사용자 자료 확인·보존
- [ ] 실제 실행 환경의 데이터 루트/LocalCache 여부, 중복 DB/외부 미디어/모델 경로 확인
- [ ] Windows 사용자/SID·DPAPI 프로필, 환경변수/Secret Store 제공 방식 확인(값 출력 금지)
- [ ] Python 3.12 또는 3.14, venv 버전, 의존성, FFmpeg/ffprobe, 글꼴·한국어 음성 확인
- [ ] 제작 예약·자동 시작·AI 장면·OAuth 작업·게시 대기/성공/불명 상태 파악
- [ ] 안전한 중지·포트/worker 해제·재진입 차단 승인과 확인
- [ ] 충분한 공간·사설 백업 권한·고유 빈 백업 위치 확인
- [ ] 코드+DB+설정+키+미디어를 한 복원 지점으로 백업, 개수/크기/해시 일치
- [ ] WAL 포함 canonical DB·integrity/외래키 검사, 새 임시 위치 복원 연습
- [ ] 사용자 실제 revision→대상 revision migration 영향 확인(운영 DB 미변경)
- [ ] 합성 프로필 앱 실행·화면·종료 확인, 실제 키 복사본 자동 실행 금지
- [ ] 별도 전환 승인 후 기존 경로·8765에서 시작, 보존 상태 조회만 확인
- [ ] 이상 발생 시 재실행/재제출 대신 중단·증거 보존·롤백 조건 검토

이 문서와 합성 CI의 PASS는 운영 배포·실제 계정 연결·게시 승인이 아니다.
