> 2026-10-29 상태 보충: 아래 본문은 이전 비실행 계약의 이력이다. 기존 ZIP은 그대로
> 비활성 상태다. 새 `windows_live.py`는 명시적인 합성 검증 후보 전용 Start/Stop 구현이며,
> 첫 실제 BAT 시도는 새 설정 파일과 기존 inventory 경로 계약의 불일치로 **BLOCKED**다.
> 제품 기동·정상 Stop·재실행 인수는 완료되지 않았다. 자세한 신규 결과는
> `docs/reports/bat-startstop-validation-20261029/BAT_STARTSTOP_REPORT.md`를 참조한다.

# 독립 Python 런타임 패키지 설계

이 디렉터리는 실행하지 않은 개발 계약이다. 실제 Python/FFmpeg 바이너리나
NewsFlow 앱·샘플을 복사하지 않았으며 전달용 ZIP도 생성하지 않았다.

```text
NewsFlowAI/
  Start_NewsFlowAI.bat      # 현재는 거절하는 dispatcher 템플릿
  Stop_NewsFlowAI.bat
  Update_NewsFlowAI.bat
  app/
    layout.json            # 서명된 릴리스 inventory에 결속할 파일 목록
    runtime/
      python.exe           # 공식 Windows AMD64 Python 3.14.7; 현재 미포함
      python314.dll
      python314.zip        # 표준 라이브러리 및 해당 런타임 구성
      ...                  # VC/runtime DLL 등 실제 의존성 전체 확인 필요
    product/newsflow/      # 기존 서비스·DB migration·정적 리소스
    frontend/dist/         # 이미 빌드한 React 자산, 사용자 Node 설치 불필요
    controller/bat_distribution/
    site-packages/         # 잠근 Windows 3.14.7 의존성, .pyd/pywin32 포함
  tools/ffmpeg.exe
  tools/ffprobe.exe
  licenses/                # Python·의존성·FFmpeg 고지/대응 소스 안내
  README.txt
```

현재12개 샘플은 권리 미확인이므로 외부 전달 목록은 빈 상태로 둔다.
`samples/`나 제품 내부 samples 디렉터리를 ZIP manifest에서 거부한다.
권리 확정 후의 별도 자산 반입 계약은 이번 변경에 넣지 않는다.

개발 venv 또는 PyInstaller `_internal`을 portable Python이라고 이름만 바꿔
전달하지 않는다. 정식 런타임 원본·해시·라이선스·전체 의존성 및 import 경로는
공식 실행 정책 문제가 해결된 뒤 확인해야 한다. `-I -B`의 격리 모드를 유지하고
사용자 site/PYTHONPATH/현재 작업 폴더에서 임의 라이브러리를 찾지 않는 고정된
패키지 경로 초기화가 필요하다. 아직 실제 `.pth`나 제품 진입점을 연결하지 않았다.

`lifecycle.inspect_layout`는 버전/아키텍처 메타데이터와 필수 파일 hash를 읽는
계약일 뿐 실제 PE 정상성·Python DLL 호환성·의존성 완전성을 보증하지 않는다.
단위 테스트 파일들은 실행 불가능한 합성 바이트다.

사용자 데이터는 기존 배포 계약 `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1`을 우선
참조하되 프로그램 경로와 절대로 겹치지 않아야 한다. 실제 ACL/CurrentUser DPAPI/
bootstrap·Origin·CSRF는 기존 제품을 재사용할 후속 경계이며 이 도구가 대체하지 않는다.
경로 생성·PID 확인·소켓 예약은 backend capability를 주입하며 실제 Windows backend는
아직 없다. `prepare_start`는 한 포트를 예약해 lease를 돌려주며 앱을 실행하지 않는다.
생성된 세션/nonce는 repr·로그에 노출하지 않는다. Stop은 동일 핸들의 실제 생성 ID와
소유 SID/경로/세션이 전부 일치해야 정상 종료를 요청하고 timeout이면 UNKNOWN으로 남긴다.

## ZIP 업데이트 계약

독립 배포자 신뢰 `Trust`와 detached manifest signature verifier를 요구한다.
기본 신뢰는 비어 있고 기본 verifier는 항상 거절한다. 실제 cryptographic/backend
검증은 NOT VERIFIED이며 합성 verifier의 성공을 실제 서명 인수로 표시하지 않는다.
기존 `updates.publisher_matches`의 signer/time/purpose 검사를 재사용하고 verifier가
반환하는 서명 대상 digest를 manifest bytes와 결속한다. ZIP 자체를 서명된 것으로
가정하지 않고 signed manifest의 ZIP SHA-256·크기 및 전체 파일 hash 목록으로 결속한다.

manifest 필드: schemaVersion=1, appId=NewsFlowAI, channel=private-bat, version,
sequence, supportedFrom=[현재 버전], pythonVersion=3.14.7, architecture=AMD64,
migration=none, zipName, zipBytes, zipSha256, files(path/bytes/sha256).
DB migration이 필요한 릴리스는 이번 구현에서 차단한다. 현재 원칙은 기존 데이터
schema를 유지하는 업데이트에 한정한다. 실제 migration success를 주장하지 않는다.

ZIP은 파일 항목만 허용하고 명시적 디렉터리/링크/extra/암호화/중복·위험 경로,
미등록 파일과 사용자 자료·미확인 샘플을 거부한다. 크기는 ZIP256MiB/전체1GiB/
단일512MiB/20000개/압축비200으로 제한한다. 이 제한은 아직 실제 완성 런타임의
크기와 비교하지 않았다. 제한 때문에 필요한 패키지가 거절되면 실제 자료를 근거로
검토하며 자동으로 완화하지 않는다.

검증한 ZIP bytes를 불변 복사로 보존하고 apply에서 파일을 재개방하지 않는다.
기존 `OfflineInstall`의 install+desktop lock, SQLite backup API, 불투명 DPAPI 복사,
side-by-side slot, atomic pointer, journal, 확정 실패 rollback과 명시적 recover를
재사용한다. staging/source extraction만 ZIP 계층이 담당한다. 기본 health callback은
없으며 승인·검증되지 않은 앱 실행을 callback으로 넣지 않았다. 합성 테스트는
새 SQLite/가짜 설정·키·미디어만 사용하고 Win32 ACL과 native lock을 fake로 대체한다.
실제 Windows ACL·파일 핸들 race·잠금·정상 종료는 별도 NOT VERIFIED다.

템플릿은 테스트용 공개 실행 스위치를 제공하지 않는다. `contract_entry`는 Start/Stop을
exit2, Update를 exit3으로 종료하며 환경변수·신뢰 파일 편집으로 활성화되지 않는다.
테스트에서 직접 주입하는 가짜 backend/verifier는 BAT 경로로 연결하지 않는다.
