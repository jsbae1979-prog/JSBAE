# Windows 일반 사용자 배포 차단 사항 통합 해결 결과

2026-10-28 · **최종 판정: BLOCKED — 일반 사용자 공개 배포 기준**

개발·검증 가능한 경계는 보완했다. 샘플의 원본 권리 증빙, 정확한 FFmpeg
대응 소스, 실제 배포자 인증서, 다른 Windows 계정 및 별도 DPI 테스트 세션은
이번 코드만으로 만들 수 없으므로 확인되지 않은 성공으로 처리하지 않는다.
운영 앱 교체·공개 배포·실계정 API·SNS 실행은 하지 않았다.

## 1. 브랜치·변경 범위

- 저장소: `jsbae1979-prog/JSBAE`
- 시작 기준: `codex/newsflow-windows-deployment-prep-20261028`,
  `9a54ec8e26f33ae6312b3d5eb80715b9a7f01342`.
- 작업 브랜치: `codex/newsflow-distribution-gates-20261028`.
- 구현 코드: `53207f8485ccffb9fb02cc71461ed7af834a883a`.
- 음성 검증 입력 보완: `f47d4ab61ccf54535e38901d753ff9f9148fe32c`.
- 설치 검증기 제거 추적 보완: `1ab226a2789a26af13979b5319f296e00885206d`.
- 최종 보고 HEAD는 이 보고서가 포함된 최종 Git 커밋/완료 메시지에 기록한다.
- Windows 11 Pro build 26300 / Python 3.14.7. CI는 Windows Server Runner다.
- 신규 코드: `src/newsflow/distribution/`, `tools/distribution/`.
  고지 자료: `src/newsflow/assets/distribution/licenses/`.
- 기존 `main.py`, `config.py`, UI 12개·API·제작 엔진·샘플 원본은 무변경.
  운영 진입점에 이 기능을 강제로 활성화하거나 운영 data_dir을 이관하지 않았다.

## 2. 샘플 권리 — BLOCKED

기존 샘플 12개의 SHA-256 및 디코딩/재생 증거를 재사용했다. PNG9개는 권리
위험 관점에서 시각 검토했고, 첨부 ZIP의 README/MANIFEST를 확인했다.
ZIP은 콜라주 추출·확대 시연물이며 배포 전 권리 확인이 필요하다고 설명한다.
ChatGPT 생성 대화·원본 콜라주·입력 권리·상용 재배포 허락은 확보되지 않았다.

**12개 모두 rightsVerified:false를 유지**한다. 로봇·고양이·드래곤·도시·지구·
뉴스 카드의 모습만으로 출처/권리를 인증하지 않는다. 차량 이미지의 외관·
엠블럼 유사 표현은 특히 재검토 대상으로 남긴다. 무음 슬라이드 MP4도 원본
이미지의 권리 검토를 승계해야 한다.

파일별 기존 해시·판정·필요 자료·자체 제작 대체 계획은
`SAMPLE_RIGHTS_REVIEW.md`, `sample-rights-evidence.json`에 정리했다.
새 유료 생성·원본 교체·라이선스 허위 표시·사용자 복사본 덮어쓰기 없음.

## 3. 라이선스 고지 — 준비 PASS / 최종 적합성 CONDITIONAL

Python 런타임 배포판30개에서 고지64개, 브라우저 런타임4개 고지,
SIL OFL 및 FFmpeg GPLv3 원문을 수집했다. 전체 licenses 폴더 파일은72개
(목록/NOTICE 포함)이며 새 실제 payload에도72개가 포함됐다.
Node 개발 런타임을 사용자 EXE에 넣지 않았다.

실제 FFmpeg는 GPL/version3/static/libx264/libx265 구성이다. LGPL 전용으로
표시하지 않는다. 정확한 외부 라이브러리 소스·패치·빌드 자료·소스 제공
체계가 아직 없으므로 일반 사용자 재배포 요건은 미충족이다.
`LICENSE_REVIEW.md`에 현재 구성 유지/GPL 준수 및 검증된 LGPL 대체 구성의
두 방안을 적었다. 렌더 엔진을 임의로 변경하지 않았다.

## 4. Windows 사용자별 보안 — 구현·집중 검증 PASS / 교차 SID NOT VERIFIED

새 패키지 전용 `distribution.launch.run`은 다음 경계를 적용한다.

- 데이터: `%LOCALAPPDATA%\NewsFlowAI-Desktop\v1`. 기존 운영
  `%LOCALAPPDATA%\NewsFlowAI`를 읽거나 migration하지 않는다.
- 새 디렉터리를 현재 사용자/SYSTEM/Administrators의3 ACE 및 보호 DACL로
  생성한다. 기존 폴더의 owner·DACL이 맞지 않으면 실패하며 임의로 고치지 않는다.
  Junction/Reparse 경유도 거부한다. 하위 DB/DPAPI/미디어/설정은 이 경계를 상속한다.
- API 키·OAuth는 기존 서비스의 data_dir/CurrentUser DPAPI를 재사용한다.
  실제 키나 기존 암호문은 사용하지 않았다.
- 같은 사용자 실행은 `desktop.lock`으로 단일 인스턴스를 정한다. 서로 다른
  사용자 프로필은 OS가 배정한 별도 exclusive loopback 포트를 사용한다.
  운영8765를 선택하지 않으며 공유 포트의 기존 세션을 재사용하지 않는다.
- 브라우저는 실행별 일회용256-bit bootstrap을 URL fragment로 전달받는다.
  query/서버 접근 로그에 토큰을 싣지 않고, JS가 fragment를 지운 뒤 bounded
  POST header로 교환한다. 120초 만료·한 번만 교환·동시 교환 단일 성공.
- 실행별 별도 HttpOnly/SameSite=Strict 세션 쿠키, 포트별 이름, 12시간 만료.
  앱 재시작 시 무효. loopback·정확한 Host·Origin·cross-site·중복 헤더를
  검사하고 인증 전 데이터/static/media/API 접근을 거부한다.
- 기존 앱의 Origin·서명 CSRF·비용/게시 승인 검사를 **안쪽에 그대로 유지**한다.
  인증 성공이 생성·게시 승인이라는 의미가 아니다. WebSocket은 새로 열지 않는다.
- 브라우저 cookie 권한은 Windows OS 통합 인증(예: Windows 인증 서비스)이 아니라
  보호된 현재 사용자 실행에서 받은 capability다. 동일 사용자 악성 코드나
  관리자 권한 위협을 완전히 차단하는 경계라고 주장하지 않는다.

신규 ASGI/업데이트 계약 unit **28 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
Windows 네이티브 합성 검사6개 성공: ACL 생성/재열기, DACL 보호,
같은 사용자 DPAPI 왕복, 암호문 보존, 불안전한 기존 ACL 거부, 별도 포트.
실제 키 대신 합성 문자열을 사용했다. 다른 실제 Windows SID의 HTTP·파일·
DPAPI 접근 거부, 새 사용자 권한, 새 진입점의 전체 GUI는 **NOT VERIFIED**.
ASGI contract PASS를 전체 Python 앱 검증으로 표시하지 않는다.
실제 OAuth redirect URI·동적 포트·교차 사이트 callback과 새 인증 쿠키의
연결도 NOT VERIFIED다. 기존 공급사/OAuth 서비스를 수정하지 않았다는 사실이
새 desktop 진입점에서 실제 계정 연결까지 성공한다는 증거는 아니다.

## 5. 실제 설치·업데이트·제거

Windows CI run40640414466에서 실제 Inno Setup을 컴파일하고 합성 Runner TEMP에서
신규 설치·동일 payload의 설치 버전 갱신·제거·재설치·최종 정리를 모두
확인했다. 앱은 실행하지 않았다.

| 실제 Windows Server CI 검사 | 결과 |
|---|---|
| Setup 두 버전 컴파일 | PASS |
| 신규 설치·설치 EXE 해시 확인 | PASS |
| 동일 payload의 installer-version 갱신 | PASS |
| 제거·합성 DB/설정/미디어/sentinel 보존 | PASS |
| 재설치·사용자 파일 보존 | PASS |
| 최종 제거 프로그램/등록/self-cleanup 완료 | PASS |

최종 Setup:107,241,063bytes, SHA-256
`cecccb8b26a5b56cb37b74bd539718aeeda50d9ce8bfb5e4f34e96e46052f6df`.
CI 생성물은 공개하거나 EXE artifact로 업로드하지 않았다. `ci-final-attempt.json`
및 CI 로그에서 결과를 확인할 수 있다. 로컬 Windows11에 설치한 것은 아니다.

실제 Windows11 새 일반 사용자·Python 없는 PC의 최초 실행/정상 종료/
재실행은 NOT VERIFIED다. 같은 payload에 설치 버전만 달리한 테스트와
구제품→신제품의 DB migration/실패 rollback을 구분한다. 뒤의 검증은 아직
NOT VERIFIED다. 기존 모형13 PASS는 이전 증거이며 실제 설치 결과에 합산하지 않는다.
샘플 중복 등록의 기존 API9/GUI21 PASS도 재사용 증거다.

## 6. 서명·업데이트 진위 — 안전 차단 구현 / 실제 서명 NOT VERIFIED

`updates.py`/`verify_authenticode.ps1`는 publisher certificate SHA-256 pin,
Authenticode Valid, code-signing EKU·timestamp, manifest/파일 size·SHA-256,
AppId/channel·단조 sequence를 확인하는 읽기 전용 검증기다.
주석 형식의 서명 manifest는 데이터로만 읽고 실행하지 않는다.

실제 publisher pin은 비어 있고 **updatesEnabled:false**다. 인증서 없는
업데이트는 차단한다. 서명된 실제 배포 파일이나 timestamp 성공은 없다.
단위 테스트는 명시적인 stub이며 실제 서명 성공으로 집계하지 않았다.
로컬 후보 EXE는 **NotSigned**다. 실제 updater/apply·원자적 high-water 저장·
설치 rollback은 구현 완료라고 주장하지 않는다. 세부 조건은
`RELEASE_SIGNING_PLAN.md`에 보존했다. SmartScreen/백신 영향은 NOT VERIFIED.

## 7. DPI·오프라인 음성

| 검증 | 결과 |
|---|---|
| 실제 OS DPI100/125/150/200% | 각각 NOT VERIFIED, 별도 테스트 세션 없음 |
| 개발 Python SAPI | PASS,2개 음성/한국어1개,16kHz·16bit·mono,3.24초,신호 존재 |
| 로컬 frozen EXE SAPI | PASS,동일 규격3.24초,외부 API0,앱 서버 미실행 |
| Windows CI 음성 | PASS,영문 음성3.645초·신호 존재;한국어 음성 없음/한국어 NOT VERIFIED |
| 사람의 한국어 청취·품질 | NOT VERIFIED |
| Supertonic/ONNX/실제 모델 가중치 | 이번 패키지 미포함,오프라인 사용 NOT VERIFIED |

패키지 entry에서 고정된 `-m newsflow.video.windows_sapi`만 해당 worker로
전달하도록 보완했다. 임의 `-m`/shell 실행 경로를 만들지 않았다.
현재 Windows 음성 파일을 설치본에 복제하지 않았다. 브라우저/CSS zoom을
OS DPI 검증으로 대체하지 않았고 운영 배율·레지스트리·로그인 상태는 그대로다.

## 8. 새 비공개 EXE

- 로컬 source 기준: `53207f8`; `f47d4ab`은 비포함 검증 도구 입력만 변경한다.
- Python3.14.7 / PyInstaller6.22.3. 967파일,307,088,684bytes.
- EXE:16,581,845bytes.
- SHA-256: `f4e0d09cf9b7218b419454c8c6cfaeb8de7730dc70366bca7720d208b007e512`.
- 루트: `C:\Users\ching\.codex\visualizations\2026\10\16\01a14359-7240-7522-8c13-8bc085201d78\distribution-secured-candidate-20261028-01`.
- 상대경로: `dist/NewsFlowAI-Candidate/NewsFlowAI-Candidate.exe`.
- React/runtime/FFmpeg·FFprobe/샘플12/라이선스 고지 포함 확인.
- 검증용 Guard/PYZ 검사 대상 모듈0. 기존 Guard·filelock 수정 없음.
- **이 후보의 로컬 실행은 고정 SAPI worker만**이다. 새 전체 GUI/HTTP 서버를
  운영 PC에서 실행하거나 현재 사용자 데이터로 최초 실행하지 않았다.

## 9. 실행 이력·신규 실패 구분

- 로컬 unit28 PASS. 네이티브6개 assertion 성공.
- 최초 네이티브 helper는 성공 assertion6개 뒤의 `real_keys_used:false` 설명값을
  실수로 assertion에 합산해 exit1이 났다. 여섯 이름을 명시하도록 고쳐 새
  합성 경로에서 모두 성공했다. 제품/DPAPI 실패가 아니다.
- CI1 [40639156438](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40639156438):
  unit/네이티브·EXE 빌드 성공 후 한국어 음성 없는 Runner의 영문 음성에 한글을
  입력한 음성 probe가0프레임 WAV로 실패했다. 실패를 보존하고 지원 언어에
  맞는 합성 문장만 보완했다. skip/xfail이나 무음 파일 PASS로 숨기지 않았다.
- CI2 [40639658464](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40639658464):
  unit/네이티브·EXE·영문 음성은 성공했지만 재설치 후 마지막 제거에서 고정
  `unins000.exe` 추적이 실패했다. 기록된 제거 경로와 registry/self-cleanup을
  함께 확인하도록 보완했다. 제품 실패로 단정하거나 이 실행을 성공으로
  바꾸지 않는다.
- CI3 [40640414466](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40640414466):
  **SUCCESS**. unit28/네이티브6개 assertion,EXE 빌드,frozen 영문 SAPI,실제 Setup
  신규 설치·동일payload 버전 갱신·제거·재설치·최종정리 모두 성공.
- 기존 전체 Python 회귀·Guard 감사·디자인 검사·샘플 바이너리 검사를 반복하지
  않았다. 과거 전체 PASS를 최신 패키지 실행 결과로 표시하지 않는다.

## 10. 보호·잔여 인수 조건

운영 `127.0.0.1:8765`/PID55740 listener 유지. 운영 코드·프로세스 재시작,
DB/ledger/키/OAuth/미디어/백업 읽기·복호화·수정 없음. 기존 untracked
`validation/`과 완료 브랜치를 보존했다. 보호 UI·샘플·main/config 소스 diff0.
PR35 Draft/open/unmerged와 main은 변경하지 않는다. 비공개 EXE/Setup/ZIP,
합성 DB·DPAPI·WAV·토큰은 GitHub에 올리지 않고 코드·고지·비민감 JSON만 보존한다.

남은 인수 조건:

1. 샘플 생성/입력/상용 재배포 증빙 또는 별도 승인된 자체 제작 원본 교체.
2. 정확한 GPL 대응 소스·빌드/외부 라이브러리 자료 및 제공 체계 확보.
3. 실제 배포자 인증서/서명·timestamp·업데이트 적용/rollback 체계 인수.
4. 다른 실제 Windows 사용자와 새 PC에서 인증·ACL·DPAPI·동시 실행·설치 인수.
5. 실제 제품 업데이트/migration 실패 복구, OS DPI4종, 옵션 음성 모델 검증.

이 조건이 해소되기 전 공개 배포는 **BLOCKED**다. 개발 결과를 운영에 적용하거나
PR을 병합하지 않고 보고 후 종료한다.
