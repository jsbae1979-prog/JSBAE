# 패키징 확정 목록과 배치

2026-10-28. 이 문서는 app/runtime 원본과 목록의 준비 상태다. 실행 가능한 NewsFlow 배포 ZIP을 만들거나 앱을 실행한 기록이 아니다.

## 런타임·의존성

공식 CPython3.14.7 Windows AMD64 embeddable ZIP12,673,227bytes를 별도 로컬 자료 폴더에 확보했다. 공개 SHA-256 `d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15`와 일치하며 ZIP CRC를 확인했다. Sigstore bundle·SPDX SBOM도 보존했으나 Sigstore의 암호학적 검증이나 실제 DLL/EXE 실행 검증은 수행하지 않았다. 원본은 실행 가능한 트리로 풀지 않았다. [Python 공식 릴리스](https://www.python.org/downloads/release/python-3147/)

37개 원본 파일은 `PYTHON_MATERIAL_INVENTORY.json`에 크기·SHA-256을 고정했다. python.exe/pythonw.exe, python314.dll/python3.dll, python314.zip/python314._pth, VC runtime2개, 확장모듈·OpenSSL/libffi/SQLite DLL, LICENSE·catalog를 포함한다. pip·Node·Tcl/Tk 설치를 사용자에게 요구하는 방식은 채택하지 않는다. embeddable Python의 의존성은 빌드 시 vendoring하는 구조다. 실제 import 경로/DLL 초기화는 현재 미연결이다. [Python Windows 문서](https://docs.python.org/3.14/using/windows.html#the-embeddable-package)

`pyproject.toml`의 직접 의존성13개를 기존 승인 Windows3.14.7 build-runtime 메타데이터 한 곳에서 전이 해결해27개 버전을 고정했다. `requirements-runtime.lock`과 `PYTHON_DEPENDENCY_LOCK.json`을 참조한다. 테스트 integration venv에는 tzdata가 없으므로 완전한 배포 원본으로 사용하지 않았다. 패키지를 새로 설치하거나 서로 다른 환경의 패키지를 임의 혼합하지 않았다.

위 목록은 설치된 metadata 기반 버전 잠금이며 wheel 파일·wheel별 해시 확보까지 완료한 lock이 아니다. 5개 native 의존성(markupsafe/Pillow/pydantic-core/pywin32/SQLAlchemy)의 DLL/PYD 이름도 기록했다. pywin32_system32, win32, win32/lib 등의 Windows DLL 탐색과 portable 초기화는 실제 런타임에서 별도 검증해야 한다. pywin32 postinstall·COM 등록·시스템 PATH 변경을 수행하지 않았다.

선택적 local-tts(supertonic/onnxruntime/numpy·별도 모델)는 이번 기본 패키지 목록에서 제외했다. 기존 Windows SAPI는 pywin32와 사용자 Windows의 음성 런타임을 쓰는 계약이며 한국어 음성이 실제 해당 PC에 존재하는지는 별도다. pytest/Ruff/PyInstaller/pip 등 빌드 도구는 사용자 런타임 필수 항목으로 넣지 않았다.

## 경로 정합성

| 대상 | 확정 목적지 | 주의 |
|---|---|---|
| Python 공식37개 원본 | app/runtime/ | 원본 보존, 실행 미검증 |
| 고정 의존성27개 | app/site-packages/ | wheel·native 검증 미완료 |
| 기존 newsflow 패키지 | app/product/newsflow/ | samples·DB·키·로그·tests 제외; 실제 복사 안 함 |
| 기존 React build | **app/frontend/dist/** | resources.py의 부모 경로 계산과 일치. Node는 빌드 때만 사용 |
| 계약 controller | app/controller/bat_distribution/ | 실제 진입점은 비활성, tests/빌드 helper/신뢰 템플릿 제외 |
| FFmpeg·FFprobe | tools/ | 기존7 PASS 재사용, 동봉 source·recipe·고지 최종 인수 필요 |
| 라이선스 | licenses/ 및 대응 소스 별도 동봉 | BAT/ZIP 전환이 기존 의무를 없애지 않음 |
| 샘플12개 | 제외 | rightsVerified:false와 원본/복사본 유지 |

기존 임시 BAT layout의 app/frontend/index.html 표기는 실제 `studio/resources.py` 탐색 규칙과 달랐다. layout 검사와 기존 테스트 fixture의 상대 경로 한 곳을 app/frontend/dist/index.html로 고쳤다. 제품/React 코드는 바꾸지 않았으며 새 경로 전용2개 검사만 실행했다. 기존78개는 반복하지 않았다.

프로필은 프로그램 밖 `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1`이다. 운영 기본 `%LOCALAPPDATA%/NewsFlowAI`와 구분하고 NEWSFLOW_DATA_DIR/Settings.from_env의 운영 기본값을 그대로 상속해 채택하지 않는다. 기존 비용/게시/Origin/CSRF/DPAPI 계약과 포트8765 보호를 유지한다. 실제 프로필·키·DB를 읽거나 생성하지 않았다.

미디어 엔진의 기존 계약은 명시 경로→NEWSFLOW_FFMPEG/NEWSFLOW_FFPROBE→PATH 순서다. 향후 허용된 launcher는 검증한 program/tools의 절대 경로만 고정해야 한다. 이번에는 환경을 설정해 미디어를 실행하지 않았다.

## 실제 서명 검증기 준비

`publisher_verifier.py`는 Windows Get-AuthenticodeSignature에 signed comment **bytes**를 전달하는 reader와 기존 ZIP verifier용 어댑터를 준비한다. `.sig`는 UTF-16LE BOM을 가진 순수 주석 컨테이너이며 첫 줄은 `# NewsFlow-BAT-Manifest-Digest-v1`, 둘째 줄은 manifest의 SHA-256, 나머지는 Authenticode signature block이다. 내용이 명령문이거나 digest가 다르면 Windows reader 이전에 거부한다. [Microsoft ByContent/UTF-16LE 문서](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature?view=powershell-5.1)

reader는 고정 Windows PowerShell·고정 script만 호출하도록 작성했고 -ExecutionPolicy 우회/임의 shell/전달받은 script 실행은 없다. helper SHA-256은 외부 앵커와 대조하며 입력은 stdin의 base64 데이터, 출력은 signer pin·서명 상태·목적·timestamp 존재·서명 컨테이너 hash만 받는다. 사용자 환경의 실키는 자식 환경에 넣지 않는다. 실제 PowerShell 암호 검증은 실행하지 않았고 helper는 AST 문법만 파싱했다.

Windows 서명 API는 시스템 인증서 cache/네트워크의 영향을 받을 수 있다. 이 코드를 cache-only 오프라인 검증이 완료된 것으로 표시하지 않는다. 실제 배포자 인증서가 없고 오프라인 chain/revocation/RFC3161 인수도 미완료라 **updatesEnabled=false, 빈 publisher pin, offlineValidationAccepted=false**를 유지한다. timestamp 필드가 있다고 모든 타임스탬프 인수가 완료된 것은 아니다.

`prepare_update_context(profile)`가 실제 사용자용 CLI/installer와 연결되지는 않았다. 신뢰 앵커가 정식으로 provision되면 반환한 trust/verifier를 기존 `zip_update.validate(..., verifier=...)`에 연결하는 경계만 준비했다. 새로운 실제 업데이트 실행 경로를 열지 않았다.

## 신뢰 앵커 배치

ZIP/프로그램 바깥 `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1/security/`에 publisher-trust.json·publisher.cer(공개 DER 인증서)를 둔다. 사용자가 별도로 신뢰하는 공식 배포자 경로에서 cert의 DER SHA-256을 대조한 뒤 정식 provisioning이 필요하다. ZIP 스스로 제공한 키/JSON으로 신뢰를 부트스트랩하지 않는다. PFX·개인키는 사용자 패키지에 넣지 않는다.

load_anchor는 고정 파일명·소유 SID·보호 DACL·로컬 비링크 경로·공개 cert hash·helper pin을 읽기 전용 검증한다. 파일을 만들거나 ACL을 완화하지 않는다. 실제 배치한 적은 없으며 보호 경계는 합성 attestor로만 검증했다. 현재 default CLI는 Start/Stop2, Update3의 거절 상태 그대로다. 환경변수나 ZIP 입력으로 이를 활성화하지 않는다.

`publisher-anchor.example.json`은 disabled 템플릿이며 유효 신뢰 정보가 아니다. 서명 인증서·공식 오프라인 검증 자료가 생기기 전 enabled/offline 승인 값을 true로 바꾸지 않는다. 실제 앵커/인증서/키는 GitHub에 저장하지 않는다.

앵커 예시의 helper pin은 이번 개발 Windows CRLF 바이트 기준이다. 정식 배포에서는 줄바꿈 정규화·실제 helper 서명을 마친 최종 바이트의 hash를 별도 신뢰 경로로 재확정해야 한다. 개발 예시 pin을 정식 신뢰 값으로 자동 채택하지 않는다. Windows PowerShell 실행 정책도 그대로 유지하므로 helper의 실제 서명/실행 가능성은 별도 미검증이다.
