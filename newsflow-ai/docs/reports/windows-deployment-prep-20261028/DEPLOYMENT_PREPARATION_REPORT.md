# Windows 11 다중 사용자 배포 준비 및 설치 패키지 검증

2026-10-28 · **최종 판정: BLOCKED — 일반 사용자 배포 기준**

이번 준비 산출물은 확보했다. 최신 소스의 비공개 onedir EXE 빌드와 패키지
목록 검사를 완료했고, 합성 파일시스템 수명주기 13개 검사는 통과했다.
그러나 실제 Setup 설치·최초 실행·업데이트·제거, 서로 다른 Windows 계정의
차단, 서명 및 샘플 재배포 권리가 확인되지 않았다. 이를 실제 설치 성공이나
제품 출시 승인으로 확대 해석하지 않는다. 운영 프로그램은 교체하지 않았다.

## 1. 기준 및 변경 범위

- 저장소: `jsbae1979-prog/JSBAE`
- 시작 브랜치: `codex/newsflow-windows11-local-runner-20261028`
- 로컬/원격 시작 기준: `39520d4ad99571b28d6ade7418f77837d2b7ffc4`
- 배포 준비 브랜치: `codex/newsflow-windows-deployment-prep-20261028`
- 최종 보고 HEAD는 이 문서가 포함된 Git 커밋 및 완료 메시지로 식별한다.
- 실제 환경: Windows 11 Pro, build 26300, Python 3.14.7.
- 기존 PyInstaller 6.22.3 기술 빌드 구조를 재사용했다. 새 패키징 엔진은 도입하지 않았다.
- 새 파일은 `tools/distribution/` 및 이 보고서 폴더에 한정한다.
- `src/`, `frontend/`, 샘플 원본, 기존 실행기·Guard·의존 패키지를 변경하지 않았다.
- 기존 미추적 `validation/`을 보존했다. reset/clean/stash/force push 없음.

## 2. 실제 패키지 산출물

기존 기술 EXE는 합성 테스트 전용 경계가 있으므로 그 차단을 제거하지 않았다.
이번 후보는 별도 spec과 별도 출력 경로에서 정상 제품 진입점을 패키징했다.
검증용 Guard가 없는 것은 배포 구성의 분리이며, 기존 테스트 EXE의 우회 실행이 아니다.
**이번 후보 앱은 실행하지 않았다.**

| 항목 | 결과 |
|---|---|
| PyInstaller onedir 빌드 | PASS, exit 0 / Python 3.14.7 / PyInstaller 6.22.3 |
| EXE | `NewsFlowAI-Candidate.exe`, 16,565,620 bytes |
| EXE SHA-256 | `7773e4ceadffde92aa786d8727350bfe2dc648841a920ac5c6aef208dfab51c9` |
| 전체 payload | 891개 파일 / 306,395,217 bytes |
| Python runtime / React 정적 자산 | 포함 확인 PASS, 실제 frozen 앱 응답은 NOT VERIFIED |
| FFmpeg / FFprobe | 기존 검증 해시와 일치하는 실행 파일 포함 PASS |
| 샘플 | 이미지 9개 + MP4 3개, manifest·파일 포함 확인 PASS |
| 테스트 Guard·검증 모듈 | 파일 목록 및 PYZ의 검사 대상 모듈 0개 |
| 합성 DB·실제 키·임시 로그 | payload 경로 규칙 및 목록 검사에서 포함 없음 |
| EXE 서명 | **NotSigned** |
| 비공개 ZIP | `NewsFlowAI-Private-Payload.zip`, 140,593,840 bytes |
| ZIP SHA-256 | `47f5153927a300850dcddf2319de54e3d4e17aa0850f3fed9ba4658592cab82f` |
| 실제 Windows Setup | **NOT VERIFIED: 설치 프로그램 미컴파일·미실행** |

로컬 보관 루트:

`C:\Users\ching\.codex\visualizations\2026\10\16\01a14359-7240-7522-8c13-8bc085201d78\windows-private-candidate-20261028-01`

EXE 상대 경로: `dist/NewsFlowAI-Candidate/NewsFlowAI-Candidate.exe`.
EXE만 이동하면 안 되며 `_internal`과 같은 onedir 구성 전체가 필요하다.
EXE/ZIP은 GitHub나 공개 배포 채널에 업로드하지 않는다.

빌드 분석의 누락 import 경고는 118건이다. 조건부·타 플랫폼·선택 의존성 경고가
섞여 있어 이를 118개 런타임 결함으로 판정하지 않는다. `supertonic`,
`onnxruntime`, `win32com.gen_py` 등 로컬 음성 경로는 별도 확인이 필요하다.
Node/Chrome을 사용자 PC에 개발 환경으로 설치해야 하는지, 음성 모델·SAPI의
실제 가용성, Python 없는 새 PC 실행은 이번 빌드 성공만으로 보증하지 않는다.

## 3. 설치·업데이트·제거 검증의 정확한 범위

`newsflow-private.iss`는 기존 빌드의 onedir 결과를 받는 **미컴파일 정의**다.
관리자 권한 없이 `{localappdata}\Programs\NewsFlowAI-PrivateCandidate`에 설치하는
설계이며, 앱 자동 실행·시작 등록·바로가기·공용 ACL 권한 확대·사용자 데이터 삭제를
추가하지 않았다. PATH 및 Inno Setup 6/7의 확인한 기본 위치에서 컴파일러를
확보하지 못했다. 도구 설치나 시스템 전역 설치를 진행하지 않았다.

| 항목 | 신규 결과 | 한계 |
|---|---|---|
| 합성 새 버전 파일 배치 | PASS | Windows Setup 설치 아님 |
| v1→v2 변경, DB·설정·미디어 보존 | PASS | 제품 DB migration·실제 업데이트 아님 |
| 배치 중 오류 주입·이전 포인터 보존 | PASS | Inno Setup rollback 아님 |
| 손상 파일·manifest 거부 | PASS | 외부 서명·배포자 인증 아님 |
| 모형 제거·재설치·반복 배치 | PASS | Windows 제거/레지스트리/업그레이드 아님 |
| 실제 891파일 payload 배치·제거·재배치 | PASS | 자체 모형에서 합성 사용자 파일 보존 |
| 실제 Setup 신규 설치·최초 실행 | NOT VERIFIED | 별도 깨끗한 Windows 테스트 환경 필요 |
| 실제 업데이트 실패·복구·제거·재설치 | NOT VERIFIED | 컴파일된 설치본 및 버전 쌍 필요 |
| EXE 정상 종료·재실행·포트 정리 | NOT VERIFIED | 후보 EXE 미실행; 이전 소스 실행 증거만 재사용 |
| 백신·SmartScreen·방화벽 영향 | NOT VERIFIED | 정책 변경·검사 제외·방화벽 규칙 추가 없음 |

새 집중 단위 검사: **13 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
두 프로필 디렉터리는 같은 Windows 계정 안의 합성 경로다. 보존용 `.dpapi`
파일은 실제 암호문이나 키가 아닌 명시적인 sentinel이다.
실제 설치·다른 계정·DPAPI 복호화 성공으로 보고하지 않는다.

## 4. 사용자별 경로·ACL·인증

| 대상 | 코드/증거 | 판정 |
|---|---|---|
| 사용자 데이터 루트 | `src/newsflow/paths.py`: Windows `%LOCALAPPDATA%\NewsFlowAI`, 명시적 override 지원 | 경로 계약 PASS; 실제 다중 SID NOT VERIFIED |
| DB·미디어·작업 이력 | 현재 Settings/data_dir 및 sessions를 사용 | 코드 확인; 다른 사용자 실증 NOT VERIFIED |
| API 키 | `intelligence/credentials.py`: 사용자 data_dir의 DPAPI 파일 또는 환경, SQLite/로그 아님 | 저장 설계 확인; 실제 키 미사용 |
| OAuth·DPAPI | `oauth/vault.py`: CurrentUser, LOCAL_MACHINE 미사용; production 경로 별도 보호 | 기존 보호 유지; 교차 사용자 복호화 테스트 NOT VERIFIED |
| 샘플·숨김·복사 | `samples/catalog.py`: 공통 읽기 자산, 사용자 DB의 `sample_content:v1:` 상태·복사본 | 기존 API9/GUI21 재사용; 이번 재실행 아님 |
| ACL | 새 합성 A/B 폴더의 Get-Acl 읽기 관찰 | 같은 SID 소유, 상속 사용. 다른 SID 읽기 거부 증명 아님 |
| HTTP 로컬 사용자 인증 | `main.py` TrustedHost·Origin·서명 CSRF cookie | **다중 사용자 출시 차단 조건** |
| 동시 실행·포트 | `config.py` 기본 8765 / `main.py` socket·FileLock | 충돌 처리 기존 증거; 계정별 동시 포트 배정 미확정 |

중요한 차이: loopback/Host/Origin/CSRF는 현재 Windows 계정의 신원을 인증하는
절차가 아니다. GET에서 접근자가 유효한 서명 CSRF 쿠키를 얻는 코드 경로를
확인했으며, 서로 다른 로컬 Windows 계정을 분리하는 별도 bootstrap 인증은
찾지 못했다. **실제 다른 계정으로 접근하거나 운영 API를 호출하지 않았다.**
이는 정적 코드 기반의 출시 위험이며 침해 성공 실증이 아니다.
다른 Windows 사용자의 HTTP 접근까지 격리하는 정책과 검증이 필요하다.

합성 ACL에는 현재 사용자/SYSTEM/Administrators 외 식별자에 대한 상속 읽기
규칙도 있었다. 민감한 SID는 증거에서 익명화했다. 이 작업 폴더의 ACL을
제품 AppData ACL로 일반화하지 않는다. 실제 설치 경로와 데이터 경로의 ACL,
다른 Windows SID의 파일 접근 거부를 별도 검증해야 한다. ACL 변경은 하지 않았다.

## 5. 배포 보안 및 무결성

- 로컬 접근·Origin·CSRF·CSP, DPAPI, 생성 견적/승인, 게시 승인, 결과 불명 재요청
  금지 코드를 변경하지 않았다. 패키징 보조 코드가 이를 대체하지 않는다.
- private 후보 entry는 포함된 FFmpeg/FFprobe 해시를 확인하고 기존 제품 run으로
  연결한다. 테스트 Guard 및 검증 사본은 배포할 필요가 없으며 후보에서 제외했다.
- 평문 hash/manifest는 신뢰하는 기준과의 동일성만 확인한다. 공격자가 파일과
  manifest를 함께 바꿀 수 있는 채널의 진위까지 증명하지 않는다.
- 코드 서명·타임스탬프·서명된 업데이트 manifest/배포 채널·버전 rollback 방지·
  실제 업데이트 복구는 출시 전에 구현/검증해야 한다. 현재 후보는 unsigned다.
- 제품 기본 실행은 사용자 AppData와 8765를 사용하고 background coordinator를
  초기화한다. 그래서 현재 운영 사용자 프로필에서 후보를 실행하지 않았다.
  최초 실행 검증은 실제 키·운영 데이터가 없는 별도 Windows 테스트 환경에서 수행해야 한다.

## 6. 샘플·FFmpeg·필수 구성요소 권리

샘플 12개 모두 기존 manifest의 **`rightsVerified: false`** 상태다.
출처는 사용자 제공 ZIP의 시연 자산이며 상업적 이용·재배포 권리 근거가 없다.
로컬 비공개 검증 포함과 일반 사용자 설치 패키지 공개는 별개다.
원본을 임의로 수정하거나 권리 확인 완료로 변경하지 않았다.
허용된 권리 문서 확보 또는 별도 승인된 자체 제작 자산·시나리오·오프라인
합성 영상으로 교체하는 방안이 필요하다. 이번에 교체 제작은 하지 않았다.

실제 bundled FFmpeg는 `9.0.2-essentials_build-www.gyan.dev`이며
`--enable-gpl --enable-version3 --enable-static` 및 libx264/libx265를 포함한다.
LGPL 전용 빌드라고 보고할 수 없다. 해당 빌드에 맞는 저작권 고지·라이선스·
대응 소스/빌드 자료 및 선택 코덱의 배포 조건을 정리해야 한다.
서브프로세스 사용만으로 앱 전체의 라이선스를 단정하지 않는다.
[FFmpeg 공식 안내](https://ffmpeg.org/legal.html).

PyInstaller의 예외는 상용 프로그램 번들 배포를 허용하지만 다른 구성요소의
의무까지 면제하지 않는다. [PyInstaller 라이선스](https://pyinstaller.org/en/stable/license.html).
Python LICENSE, Noto/SIL OFL 및 일부 의존성 고지는 실제 포함됐다. 모든 의존성
고지·음성/모델 자산 재배포 검토가 완료된 것은 아니다. 이번 metadata 목록은
구성요소 조사이며 법적 적합성 최종 판정이 아니다.

## 7. DPI 및 과거 증거 재사용

| 실제 OS DPI | 이번 상태 |
|---|---|
| 100% | NOT VERIFIED |
| 125% | NOT VERIFIED |
| 150% | NOT VERIFIED |
| 200% | NOT VERIFIED |

별도 Windows 테스트 세션을 확보하지 않았다. 운영 세션의 배율·레지스트리·
로그인 상태를 변경하지 않았다. viewport/CSS zoom으로 대체하지 않는다.

제작실 Chrome22, 관리 Chrome15, 샘플 API9/GUI21, 집중 CI59,
Windows11 실제12화면 접근, MP4 3개 재생, TOP3 이력·포인터 이동,
로컬 FFmpeg4 PASS를 **이전 증거**로 재사용했다. 이번 신규 실행으로 합산하지 않는다.
전체 Python 회귀·Guard 감사·디자인 비교·샘플 원본 디코딩을 반복하지 않았다.
이번 GitHub Actions 실행은 없으며, 로컬 packaging 모델 검사만 새로 실행했다.

## 8. 운영·소스 보호

- 운영 앱 시작/종료/재시작·HTTP 요청 없음. 최종 비파괴 조회에서
  `127.0.0.1:8765`, 기존 PID `55740`의 listener 유지 확인.
- 운영 DB·ledger·설정·키·OAuth·미디어·백업 내용 열람·복호화·수정 없음.
  내용을 읽지 않았으므로 운영 DB 전체 해시 비교를 했다고 주장하지 않는다.
- 승인 12개 화면 및 샘플 원본의 tracked source diff 없음.
- 기존 빌드 런타임·검증된 미디어만 읽기 사용. 패키지 설치/의존성 변경 없음.
  빌드 cache/TEMP/profile은 새 출력 폴더로 지정했다.
- PR35: Draft/open/unmerged, HEAD `75626f74cc1bfe750d24132e44019bcda478247b`.
- main: `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`.
- 지정 새 배포 준비 브랜치에 코드·보고서·비민감 증거만 보존한다.
  EXE/ZIP/합성 DB·키 sentinel·운영 자료는 GitHub에 올리지 않는다.

## 9. 남은 배포 차단 및 권장 순서

1. **P1 — 권리/라이선스:** 샘플 12개 권리 근거, FFmpeg GPL 빌드 대응 소스·고지,
   포함 의존성/음성/모델의 배포 조건을 확정한다. 해결 전 공개 금지.
2. **P1 — 다중 Windows 사용자:** 사용자 인증이 있는 로컬 앱 접근, 데이터 경로
   ACL, 다른 SID 접근/DPAPI 거부, 계정별 포트/다중 실행·OAuth redirect 계약을
   결정하고 합성 계정에서 검증한다. 이번에 보안 정책을 임의 변경하지 않았다.
3. **P1 — 실제 설치/업데이트:** 컴파일러와 깨끗한 테스트 환경을 확보해 후보
   Setup을 컴파일하고 Python 없는 PC에서 최초 실행·sample 표시·종료·재실행,
   실제 구버전→신버전·실패 복구·제거·재설치를 확인한다. 사용자가 명시적으로
   삭제를 선택하지 않는 한 DB·키·미디어를 삭제하지 않는 계약을 확정한다.
4. **P1 — 배포 진위:** 서명·타임스탬프·업데이트 검증·rollback 정책 및 백신/
   SmartScreen 관찰을 완료한다. 방화벽/보안 기능 비활성화로 대체하지 않는다.
5. **P2 — 실제 화면/음성:** 별도 OS 테스트 세션에서 DPI4종 및 옵션 음성 런타임,
   9:16 미리보기/모달·새 PC 필수 자산을 확인한다.

일반 사용자 배포 준비는 아직 **BLOCKED**다. 이번 작업은 준비 코드와 비공개
빌드·증거 확보까지 완료했으며, 실제 설치 또는 운영 교체를 수행하지 않았다.
운영 전환·PR 병합·실계정 API·SNS 게시 없이 종료한다.

## 10. 재개 체크포인트 및 증거

- `build-summary.json`: 실제 EXE 빌드와 포함 상태.
- `payload-validation.json`: private ZIP 및 실제 payload의 모형 배치/제거/재배치.
- `payload-manifest.json`: 패키지의 파일별 size/SHA-256. 운영 파일 목록 아님.
- `contract-result.json`: 13개 신규 검사 ID, PASS/FAIL/ERROR/SKIP.
- `acl-observation.json`: 새 합성 폴더만 조회한 익명화 ACL.
- `preparation-evidence.json`: 소스 변경 범위·서명·실행 여부·빌드 입력 해시.
- `tools/distribution/README.md`: 재현 조건과 실행 금지/미검증 범위.

다음 작업은 이 브랜치의 최종 보고 커밋에서 재개한다. 검증 도구나 패키지
모형을 실제 설치·제품 보안 구현으로 간주하지 않는다.

공식 기준 참고: [per-user 최소 권한](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[Windows ACL](https://learn.microsoft.com/en-us/windows/win32/secauthz/access-control-lists),
[CurrentUser DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).
