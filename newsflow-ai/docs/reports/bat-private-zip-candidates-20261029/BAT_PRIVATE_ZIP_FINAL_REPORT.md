# BAT 비공개 ZIP 후보 구성·비실행 검증 최종 보고

완료2026-10-29 KST. 2026-10-28에 시작한 작업 식별자·보관 폴더명은 유지했다. **최종 판정: CONDITIONAL.** 요청한 두 ZIP의 파일 수준 후보 구성을 완료했지만 실제 앱 실행·사용자 전달용 완성품·실제 오프라인 업데이트 인수는 아니다.

## 1. 기준과 후보

- 브랜치 `codex/newsflow-bat-distribution-prep`, 시작 SHA `b1169c35eba9df2df4c1295e353e5c1b4220c25b`.
- 후보 조립 코드/메타데이터 SHA `3b3598f4f6a0b9d3c04e92bb75efae026216fdc2`. 제품 src·React·기존 EXE 체계는 시작 기준에서 변경0이다.
- 보관: `C:/Users/ching/.codex/visualizations/2026/10/16/01a14359-7240-7522-8c13-8bc085201d78/bat-private-package-candidates-20261028/packages-browser`. 후보 ZIP·wheel·runtime·소스 아카이브는 로컬에만 보관한다. GitHub에는 구현/매니페스트/비민감 검증 증거만 올린다.

| 파일 | 바이트 | SHA-256 | 구성 |
|---|---:|---|---|
| NewsFlowAI_v1.0.0.zip | 232213326 | `0228c117409c94b2d70ce0957633a8457f156e017b1a90fef422e7e980ef93d2` | NewsFlowAI/ 아래 2874개 파일 |
| NewsFlowAI_Update_v1.1.0.zip | 232150098 | `18b5369709d7bc6c506becac8b72087746d5d6460a6b8e390013c5aa9661a765` | program 상대 루트 2874개 파일 |

두 파일은 **동일 제품 소스**에 1.0.0/1.1.0 릴리스 metadata·README만 구분한 내부 후보다. 실제 기능이 다른 제품 두 버전 사이의 업데이트 성공으로 표시하지 않는다. ZIP은 CRC·구조·전체 내용 hash 검사를 통과했다. 업데이트 ZIP은 기존 validator의 파일-only·크기·경로 제한에 맞춰 저장 방식으로 구성했다.

## 2. 독립 런타임·wheel

기존 공식 Python3.14.7 AMD64 ZIP의 공개 hash를 재사용해 원본37개를 배치했다. DLL/EXE 등36개는 원본 바이트를 유지하고 python314._pth 1개만 고정된 runtime/site-packages/win32/pywin32_system32/product/controller 검색 경로로 설정했다. import site를 켜지 않았으므로 vendor .pth·설치 후 코드가 자동 실행되지 않는다. 원본 ZIP 자체는 변경하지 않았다. 실제 내장 Python --version/import/앱은 한 번도 실행하지 않았다.

직접13·전체27개 버전을 공식 PyPI에서 원본 wheel로 모두 확보했다. 게시 size/SHA-256, 파일명/버전·cp314/AMD64 또는 호환 ABI/순수 Python 태그, Requires-Python, RECORD2360개를 검증했다. 실제 wheel METADATA로 다시 계산한 의존성 closure도 기존27개와 일치했고 충돌0이었다. [wheel27개 URL·SHA-256 표](WHEEL_27_MANIFEST.md), [전체 검증 JSON](WHEEL_27_VERIFICATION.json), [해시 고정 목록](requirements-offline-hashed.txt) 참조.

압축을 푸는 방식으로 site-packages를 구성했으며 pip/setup.py/빌드 backend/.pth/postinstall/console launcher/pyc compile은 실행하지 않았다. .data purelib/platlib/scripts를 제한된 프로그램 경로로 spread하고 배치본 RECORD를 재작성해2230건을 확인했다. 프로그램/사용자 프로필을 수정하는 pywin32_postinstall은 보관만 하며 실행하지 않았다.

초기 조립은 isapi/samples의 개발 예제6개가 샘플 경로 정책에 걸려 중단됐다. 해당 시도는 ZIP을 내지 않았고 원본 wheel은 변경하지 않았다. 기본 runtime에서 쓰지 않는 이 예제만 제외했다. 이어 중간 후보의 정적 PE 분석에서 선택 PythonWin/MAPI 모듈이 mfc140u.dll/msvcp140.dll을 요구함을 확인했다. 제품의 직접 참조가 없으므로 브라우저형 기본 profile에서 PythonWin/MAPI 선택 구성요소124개 파일(추가 native7개)을 제외했고 원본27개 wheel은 그대로 보존했다. 핵심 win32api/COM/pywin32_system32와27개 배포판 metadata는 유지했다. 이 profile은 범용 PythonWin/MAPI 실행 지원을 표방하지 않는다. 제외 목록은 [PACKAGE_RESULT.json](PACKAGE_RESULT.json)의 wheel 행에 있다.

최종 native103개를 기존 개발 Python3.14.7의 PE parser로 읽기만 했으며 모두AMD64였다. 정적 import 목록상 누락된 추가 CRT 이름은0이다. Windows 기본 DLL/API-set 실제 resolution·COM/DLL search path·SAPI 초기화는 미검증이다. **파일/헤더 검사와 실제 DLL 로딩 성공은 다르다.** [native 목록](NATIVE_IMPORT_INVENTORY.json)

## 3. 실제 패키지 경로·BAT

```text
NewsFlowAI/
  Start_NewsFlowAI.bat
  Stop_NewsFlowAI.bat
  Update_NewsFlowAI.bat
  app/runtime/                  # CPython 원본 및 고정 검색 경로 데이터
  app/site-packages/            # 검증한27개 wheel의 기본 browser profile
  app/product/newsflow/         # 기존 제품 코드·리소스, 원본 sample assets 제외
  app/frontend/dist/           # 기존 React 자산
  app/controller/bat_distribution/
  tools/ffmpeg.exe, ffprobe.exe
  licenses/                    # 기존 고지·대응 소스7개·recipe 포함
  README.txt
```

첫 ZIP은 이 NewsFlowAI/를 포함하고 업데이트 ZIP은 내부 프로그램 상대 경로부터 시작한다. 모든 경로/파일 hash는 [무서명 업데이트 inventory](UPDATE_MANIFEST_UNSIGNED.json)에 기록했다. 폴더명 samples 때문에 카탈로그 Python 소스까지 누락되지 않도록 `newsflow/samples/*.py`만 허용했고 실제 `assets/samples` 및 media/manifest는 제외했다. 새 가짜 결과 이미지로 채우지 않았다.

Start/Stop의 경로·포트·소유권 계약은 기존78 PASS를 재사용한다. BAT quoting·CRLF·-I -B·존재 검사를 정적으로 확인했고 **거절 dispatcher는 그대로**다. Start/Stop exit2, Update exit3이며 실제 프로세스/loopback binding/브라우저 생성/강제 종료를 수행하지 않았다. 기본 port는 미래의 허용된 live adapter에 명시적으로 전달해야 하며 운영8765나 Settings.from_env의 운영 default를 상속하지 않는다.

사용자 데이터 계약은 프로그램 밖 `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1`, 운영 기본 `%LOCALAPPDATA%/NewsFlowAI`와 분리다. 실제 해당 프로필을 만들거나 열지 않았다. 기존 인증/Origin/CSRF·DPAPI·비용/게시 승인·결과 불명 보호를 변경하지 않았다.

## 4. 업데이트·라이선스

파일명 NewsFlowAI_Update_v1.1.0.zip과 외부 manifest JSON은 만들었으나 배포자 인증서·앵커·.sig는 없다. manifest의 SHA-256만으로 진위를 인정하지 않는다. 기존 ZIP verifier에 실제 후보를 주었을 때 기본 Trust 부재로 **추출/쓰기/실행 이전에 차단**됐다. 실제 업데이트·DB migration·프로필 backup/restore를 실행하지 않았다. 기존78/31의 버전·서명 경계·합성 백업/복구 성공을 재사용한다.

실제 서명 검증기와 오프라인 chain/revocation/timestamp qualification은 이전 준비 상태다. Update enabled/offline approval을 true로 바꾸거나 테스트 인증서·가짜 서명으로 대체하지 않았다. 후보에 trust anchor/개인키/실키·OAuth·DB·ledger·사용자 영상/백업이 들어 있지 않다.

기존 source-built FFmpeg/FFprobe의 고정hash와 일치하며 기존7 PASS를 재사용했다. 새 영상이나 ffmpeg -version도 실행하지 않았다. licenses에 Python/wheel 고지와 FFmpeg 대응 소스7개·build recipe·기존 evidence를 포함했다. 최종 라이선스/대응 소스 완전성·실제 제공 조건은 여전히 인수 대상이며 **외부 배포 승인이 아니다**. 권리 미확인 샘플12개 및 사용자 복사본/원본/rightsVerified:false는 그대로 보존했고 후보의 sample assets는0개다.

## 5. 이번 검증·실패 이력 구분

| 구분 | 결과 | 의미 |
|---|---|---|
| 새 집중 단위 검사 | **30 PASS / 0 FAIL / 0 ERROR / 0 SKIP** | 처음26개·ISAPI 제외2개·browser profile2개, 서로 다른 ID이며 기존78/31은 재실행 안 함 |
| 최종 산출물 정적 검사 | **16 PASS / 0 FAIL / 0 ERROR** | ZIP hash/size/CRC·경로, runtime37, 설치 RECORD/27버전, React/media, 샘플/개인자료 배제, BAT·unsigned gate, source/license 포함 |
| native 정적 분석 | 103개AMD64·추가 CRT 미동봉 import 이름0 | 실제 loader 또는 앱 실행 PASS가 아님 |
| 기존 증거 | 78/31/Windows CI45/설치19/FFmpeg7 PASS 재사용 | 이번 신규 결과와 합산하지 않음 |
| 앱/BAT/내장Python/FFmpeg 실제 실행 | **NOT VERIFIED / 미실행** | 사용자 승인 범위 밖 |
| 실서명 업데이트/신규Windows 설치·GUI·DPI | **NOT VERIFIED** | 실제 계정/신뢰·실행 조건 미확보 |

초기 경로 차단과 중간 선택적 CRT 미확보를 성공으로 덮지 않았다. 첫 packages 폴더는 미완료, packages-final은 중간 후보로 보존하고 SUPERSEDED 표시했다. 최종 검토 대상은 **packages-browser만**이다. 복구·전송을 위해 오래된 후보를 삭제하거나 재압축하지 않았다. 최종 unit [JUnit](junit-new-only.xml)·[산출물16개 검사](MATERIAL_CHECKS.json)·[종합판정](RESULTS.json)을 보존했다.

전체 회귀·Guard/디자인 감사·V3 반복 진단·AhnLab 요청0. 네트워크는 요청된 wheel 확보를 위한 공식 PyPI/파일 호스트 GET뿐이고 실제 AI/OAuth/SNS 호출0이다. 보안 비활성화·예외·ACL 완화·포트8765 사용·외부 사용자 전달0이다. 소유 앱/서버/worker를 시작하지 않았으므로 앱 정상 종료·process cleanup PASS로 집계하지 않는다.

## 6. 남은 조건·운영 보호·종료

파일 후보는 갖췄지만 live adapter는 의도적으로 연결하지 않았다. 실제 portable import·DLL/COM/SAPI·React/제작·정상 종료·실업데이트를 인수하려면 실행 허용 조건 확인과 별도 승인이 필요하다. 이번에는 AhnLab 분석 요청을 하지 않았고 특정 분석 접수를 자동으로 다음 단계로 만들지 않는다. 실제 배포자 인증서/외부 앵커 및 오프라인 검증, FFmpeg/포함 자산 권리·source 전달 조건도 남아 있다.

운영 앱·DB·키·OAuth·설정·미디어·백업을 사용하거나 변경하지 않았다. 기존 EXE 후보·원본 샘플·완료 브랜치도 보존했다. 제품/React/기존 설치 도구의 기준 SHA 대비 Git 변경0을 확인했으며 main·PR35를 변경하지 않았다. 이 보호는 금지된 운영 파일을 새로 해시/열람한 감사가 아니라 해당 경로를 읽거나 쓰지 않은 작업 범위와 Git diff에 근거한다. 기존 미추적 validation/도 유지했다.

결과를 개발 브랜치에 보존한 뒤 **CONDITIONAL**로 종료한다. 실제 사용자에게 실행 가능한 완성품으로 전달하거나 운영 교체·PR 병합·추가 실행을 하지 않는다.
