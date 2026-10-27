# Step 13K-Fix + Step 15-A 최종 보고

검증일: 2026-10-26 KST. Windows 11, Python 3.14.7 단일 기준.

## 1. 판정

- **Step 13K-Fix: PASS** — 확인한 종료 대기 문제 최소 보완, 기존 15초 제한 유지, 로컬·Windows Actions 반복 정상 종료 통과.
- **Step 15-A: CONDITIONAL** — 격리 EXE 빌드·GUI·합성 제작·종료·재실행은 PASS. 새 PC의 완전 독립 실행·일반 사용자용 설치/서명·로컬 음성 런타임은 미검증이며, Actions 별도 범위의 사용자 확인 시간 초과 1건이 남음.
- 전체 작업: **CONDITIONAL**. 운영 적용·재시작·일반 배포·실제 API/OAuth/SNS는 실행하지 않음.

## 2. 정상 종료 실패 원인과 최소 변경

최초 진단에서 CTRL_BREAK는 수신됐지만 Uvicorn shutdown의 `server.wait_closed()`에서 멈췄다. 연결/작업 집계는 0, worker는 유휴 상태였다. 반복 진단에서 Windows Python 3.14.7 Proactor `_call_connection_lost`의 `socket.shutdown()`이 WinError 10054를 발생시키는 로그를 확보했다. 이 예외는 뒤의 socket close와 `Server._detach()`를 건너뛰어 서버 종료 대기를 남긴다. 합성 소켓으로 정리 누락을 재현했다.

**증거 한계:** 과거 최초 실패 테스트는 stderr를 버렸으므로 그 실행에서 같은 예외가 발생했다는 사실까지 소급 확정하지 않는다. 관찰한 대기 지점과 반복 재현한 원인을 구분한다. 단순 타임아웃 증가나 강제 종료로 PASS 처리하지 않았다.

제품 변경은 2개 파일이다.

- `src/newsflow/runtime.py`: Windows 로컬 HTTP 서버용 Selector 루프 팩토리.
- `src/newsflow/main.py`: Windows에서만 해당 루프를 Uvicorn에 명시. 전역 asyncio 정책은 그대로.
- `tests/test_windows.py`: 기존 lifecycle ID 유지, stderr 보존, RST 연결 취소/포트 재사용 및 루프 계약 2개 테스트 추가.

기존 동기식 worker subprocess 경로와 승인·CSP·Guard·비용·결과 불명 정책을 유지했다. Windows Selector의 연결 수 및 비동기 pipe 제약은 향후 고부하·비동기 subprocess 구조 변경 시 검토해야 한다.

로컬 5회 × 3검사 = **15 PASS**(실제 서버 lifecycle 10회). 각 Job의 종료 전 활성 프로세스는 0. Actions에서도 동일 5회 반복 **15 PASS**. 첫 진단 실패의 강제 Job 정리는 실패 증거로 보존했고 정상 종료 PASS에 포함하지 않았다.

## 3. 회귀 결과와 기존 집계 구분

| 지표 | PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|
| 이전 마지막 단일 전체 회귀 | 5,419 | 33 | 0 | 4 |
| 이전 최신 ID 누적 결과 — 전체 재실행 아님 | 5,451 | 1 | 0 | 4 |
| **이번 단일 전체 회귀** | **5,454** | **0** | **0** | **4** |

전체 실행 16:57:54~17:34:21 KST, 약 36분. 전체 Job 종료 전 잔여 프로세스 0. 이전 33 FAIL 중 32건은 이전 Step 13K 후속 검증에서 이미 해결됐고, 이번 종료 보완 대상은 나머지 1건이다. 신규 테스트 2개, 신규 FAIL/ERROR 0, 기존 SKIP 4개 동일, skip/xfail 추가 없음.

기존 ID 집합은 보존됐다. 단, `test_easy_ui`는 수집 시 `uuid4().hex`를 사용하는 잘못된 작업 ID 파라미터 1개가 실행마다 바뀐다. 원시 ID 차이를 보존한 뒤 해당 32자리 UUID만 정규화하여 누락 0을 확인했다. 다른 ID는 정규화하지 않았다.

### Windows Actions

- [확대 선택 범위 run 40290221694](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40290221694): 동일 코드 2회 모두 **380 PASS / 1 FAIL**. 실패 시 중단 정책 때문에 뒤의 종료 반복 15검사는 그 run에서 실행되지 않았다.
- 실패 ID: `tests.test_operational_startup::test_native_windows_schema_roundtrip_without_registration`.
- 직접 오류: 테스트 Guard의 승인된 PowerShell identity 조회에서 `TimeoutExpired`. 로컬 전체 회귀의 같은 ID는 PASS. Windows Server 2025 runner와 로컬 Windows 11 차이가 있으며, 시간 초과의 근본 원인은 미확정이다. timeout 상향·skip·보안 완화로 수용하지 않았다. 이전 CI PASS 대비 실패이므로 CI 잔여 위험으로 남긴다.
- [종료·보안 집중 run 40292282593](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40292282593): **145 검사 PASS** = Guard 78 + native Guard 52 + 종료 3검사×5회. 고유 ID는 133개다. 실패 1건을 숨긴 전체 PASS가 아니라 명시적으로 분리한 집중 검증이다.
- 최종 패키징 후속 코드는 로컬 EXE로 검증했다. Actions는 제품 종료 코드/Guard 검증이며 EXE를 runner에서 새로 빌드한 결과가 아니다.

## 4. 패키징 선정 및 실제 산출물

PyInstaller **6.22.3**를 우선 선정해 Python 3.14.7에서 실제 빌드했다. 기존 GUI/엔진/정적 자산 구조와 onedir 묶음에 적합하고 별도 C 컴파일러 전체 빌드를 요구하지 않는다. Nuitka의 Python 지원·C 도구 조건을 비교했으며 두 도구 빌드를 불필요하게 반복하지 않았다.

공식 근거: [PyInstaller 실행 구조](https://pyinstaller.org/en/stable/operating-mode.html), [리소스 경로](https://pyinstaller.org/en/stable/runtime-information.html), [Nuitka 매뉴얼](https://nuitka.net/user-documentation/user-manual.html), [Uvicorn 이벤트 루프](https://uvicorn.dev/concepts/event-loop/).

- EXE: `build-attempt6/dist/NewsFlowAI-Technical/NewsFlowAI-Technical.exe` (별도 진단 루트 기준).
- SHA-256: `7a59124875e27b95131297730a868eae87b3c4d76eafd2aa1a86e65a4b80898c`.
- EXE 크기: 16,877,478 bytes. 전체 묶음: **856파일 / 288,241,901 bytes**.
- Python DLL, FFmpeg/ffprobe, HTML 74개, 정적 자산 64개, Noto 글꼴 1개 포함.
- EXE와 `_internal` 폴더를 함께 보존해야 한다. 단일 EXE 파일만 이동하면 안 된다.
- 운영 DB·키·암호문·개인 미디어 없음. Node/Chrome은 테스트/브라우저 의존성으로 EXE에 포함되지 않음.

**독립 실행 판정:** PATH에서 Python을 제거하고 번들 Python DLL로 실행하는 검사 PASS. 읽기 경계도 번들·Windows·합성 루트로 제한했다. 그러나 Python이 전혀 설치되지 않은 새 Windows PC에서 실행한 것은 아니므로 최종 무설치 런타임 독립성은 NOT VERIFIED.

이 파일은 합성 프로필 표식을 요구하는 **내부 기술 EXE**이며 일반 사용자용 진입점·설치파일이 아니다. scheduler/게시/AI 장면 자동 worker는 이 테스트 진입점에서 시작하지 않으며, 기존 제품 엔진을 합성 입력으로 호출한다. 제품의 정상 worker lifecycle은 별도 원본 실행 테스트로 검증했다.

## 5. EXE 기능·GUI 검증

| 항목 | 결과와 범위 |
|---|---|
| 뉴스 영상 | Fake RSS → 합성 기사 → 권리 확인된 로컬 이미지 자동 연결 → Offline 분석/대본 → FakeTTS → 실제 FFmpeg 1080×1920·30초 MP4 PASS |
| 뉴스 모델 설정 | 제작/설정/AI 영상 화면과 모델 선택 경로 표시 PASS. 저장·독립 설정의 전체 조합 계약은 동일 소스의 전체 회귀로 보완. EXE에서 실제 AI 모델 생성은 미실행 |
| 이미지 제작 | 독립 메뉴, 1024×1024·high 선택, Fake 생성 1회, 검토 후 자산 내보내기 PASS. 이미지 선택 변경 시 캐릭터 기본값 불변 |
| 이미지 재사용 | 실제 브라우저에서 미리보기 확인·검토 체크·캐릭터 참조로 저장·선택값 연결 PASS |
| 캐릭터 | Claude 모델 선택 작업 고정, 기존 Seedance/참조 계약 코드 포함. 합성 10초 클립 3장면의 실제 FFmpeg 1080×1920·30초 합성 PASS. 실제 캐릭터 일관성·AI 생성 품질 검증 아님 |
| 영상 프레임 | 뉴스/캐릭터 각각 5·15·25초, 6프레임 검증. 뉴스 이미지 색상 대조 및 장면/자막 표시 PASS |
| GUI | 홈·뉴스·쇼츠 생성·AI 대본·영상·AI 영상·이미지·캐릭터·게시·설정 10화면 × 1440/980/390px = 30검사 PASS. 가로 넘침 없음 |
| GUI 자산 | JavaScript 오류 0, 정적 자산 HTTP 실패 0, 페이지 외부 요청 0 |
| 영상 재생 | 브라우저에서 1080×1920 영상 재생 시간이 실제 증가함을 확인 |
| 포트 충돌 | 같은 합성 프로필 중복 실행 exit 1 및 conflict 기록 PASS |
| 종료·재실행 | EXE 2회 모두 CTRL_BREAK 후 15초 내 exit 0·server_stop·포트 해제. 같은 합성 프로필 재실행 PASS. 최종 Job 활성 프로세스 0 |

첫 GUI 검사의 Playwright 문자열 `wait_for_function`이 기존 CSP의 unsafe-eval 차단에 걸렸다. 제품 CSP를 바꾸지 않고 테스트의 영상 대기를 Python 제한 시간 polling으로 바꿔 재검증했다. Uvicorn이 정상 정리 후 다시 올리는 KeyboardInterrupt는 기술 진입점에서 마지막 server_stop이 확인된 경우에만 정상 종료로 처리했다. 실제 소켓/프로세스 종료를 감독 도구에서 별도 확인했다. 빌드 1~5의 경계/시험 도구 실패 기록과 GUI 첫 실패는 삭제하지 않았다.

## 6. 변경 파일·소스 관리

제품/회귀 변경 3파일은 위 2절 참조. 상세 diff: `shutdown-minimal.diff`.

추가 파일:
- `.github/workflows/newsflow-step15a-windows.yml`
- `tools/validation/step15a/prepare_windows.py`, `phases-safe.json`
- `tools/packaging/{technical_entry.py,technical_boundary.py,technical_media.py,technical_probe.py,build_technical.py,newsflow-technical.spec,README.md}`
- `tools/packaging/validation/{test_exe_gui.py,test_exe_media_frames.py,README.md}`
- 본 보고서와 비민감 검증 요약. 전체 변경 목록·hash/diff는 `code-changes-safe.json`, `technical-changes.diff`.

개발 브랜치: `codex/newsflow-step13kfix-15a-20261026`.
- 이전 기준 제품 de4cfaa / 보고서 a7e58bf.
- 제품·테스트 수정: `f6ff13390add7df0fb1a3b9827b442de74a87d74`.
- CI 수정: ae9a984, 집중 범위 5cfe554.
- 패키징 최초: dea4852.
- **최종 제품/패키징/검증 코드: `08bfec12f71fbe10b2bf2b7df4a2b8efd4283ba8`**.
- 보고서 commit HEAD는 별도 최종 체크포인트에 기록한다.

PR #35는 Draft·open·미병합. 기존 PR head/base를 변경하지 않고 개발 브랜치와 결과를 댓글로 연결한다. main·운영 Git refs 변경 없음. 실제 EXE/DB/키/미디어/백업을 GitHub에 업로드하지 않았다.

## 7. 보호·보존 결과

운영 로컬 수정 64개, 보존 대상 데이터 33파일, DB/ledger 등 핵심 보호 파일 10개 해시 불일치 0. 기존 후보 655파일·G9 소스 2,142파일 변동 0. 이전 Step 13K 봉인 자료 8개도 일치했다.

백업 A/B 각각 **45,572파일 / 6,388,588,775 bytes**, 경로 집합/크기/수정시각 불일치 0, 핵심 파일 및 운영 데이터 해시 불일치 0. 승인된 이전 전체 SHA·SQLite·Git 검증 증거를 재사용했으며 전체 백업을 다시 전수 해싱하거나 원본 DB에 연결하지 않았다. DB revision 0018의 기존 근거는 파일 해시 불변으로 재사용했다.

기존 보조 Git 참조 누락 1개는 알려진 예외로 유지. 새 누락·강제 복구·gc/prune 없음. API 결과 불명 7건, 피드 1건, ElevenLabs reserved 1건·HTTP402 기록은 변경되지 않은 DB 근거로 보존 확인.

운영/백업 쓰기 0, 운영 DB 연결 0, 운영 적용/재시작 0, 실제 공급사·OAuth·SNS 호출 0. 최종 포트 8765/18765 listener 0, 시험 프로세스·운영 소스 실행 프로세스 0.

기술 EXE 경계의 외부 경로 읽기·번들 쓰기·shell·미디어 경로 탈출·위험 필터·외부 connect 차단 6건 PASS. 기존 Guard/fixture 관련 7파일은 이전 Step과 동일하다. 현재 Windows 사용자의 OS 권한 자체를 제거한 것은 아니며, Playwright 요청 Mock으로 Chrome 자체 배경 통신 전체 차단을 입증했다고 주장하지 않는다.

## 8. 전체 진행표

| Step | 상태 |
|---|---|
| 1~9 | 기존 조사·백업·복원 증거 보존·재사용 |
| 10 | ACCEPTED — Git 긴 경로 진단 |
| 11 | SKIPPED — Git 복구 불필요 |
| 12 / 12-IMG | PASS / CONDITIONAL — 기존 승인 |
| 13A~F / 13G 계열 | 승인된 진단·개선·회귀 결과와 예외 보존 |
| 13H | CONDITIONAL ACCEPTED — 이미지 자동 연결 |
| 13I | CONDITIONAL ACCEPTED — API 준비/Fake |
| 13J | CONDITIONAL ACCEPTED — 통합 기능 |
| 13K | CONDITIONAL ACCEPTED — 제작 모드 선택 |
| **13K-Fix** | **PASS — 종료 보완 및 반복 검증** |
| 14 | NOT AUTHORIZED — 운영 적용/재시작 미실행 |
| **15-A** | **CONDITIONAL — 기술 EXE/Fake PASS, 배포 조건 미완료** |
| 15 나머지 | 일반 사용자 진입점·설치·서명/라이선스 등 별도 승인 |
| 16 | NOT AUTHORIZED — 다수 사용자 설치/데이터 분리 |
| 17 | NOT AUTHORIZED — 업데이트/제거/복구 |
| 18 | NOT AUTHORIZED — 최종 일반 배포 |

## 9. 남은 조건과 권장 순서

1. Windows Actions PowerShell identity 시간 초과 1건의 runner 환경 원인 확인 및 제한적 재검증. 로컬 전체 PASS로 CI 실패를 상쇄하지 않는다.
2. Step 15 후속 승인: 실제 사용자용 진입점/설치 구성, FFmpeg·글꼴·런타임 배포 라이선스, 코드 서명·백신 검사, 필요한 SAPI/Supertonic 모델 제공 방식을 확정. 이번 빌드는 FakeTTS이며 실제 로컬 음성 제공 완료가 아님.
3. Python 없는 새 Windows PC에서 전체 묶음 실행, 사용자별 DPAPI/DB/미디어, 포트 충돌·정상 종료·다중 사용자 검증. 현재는 동일 PC의 PATH/파일 경계 검증까지만 완료.
4. 위 전제와 별도 승인 후 Step 16. Step 17 업데이트/제거/복구 및 Step 18 공개 승인은 이후 별도 수행. 설치파일은 아직 만들지 않았으므로 Step 16 완료/배포 준비 완료로 판정하지 않는다.
5. 실제 API 모델/가격/권한, 유료 생성, OAuth/게시, 운영 Step 14는 각각 별도 승인 대상. 자동 실행·재요청하지 않는다.

재부팅 시 이 개발 브랜치의 최종 보고서 HEAD와 코드 SHA를 확인하고, 기존 증거를 먼저 읽는다. 새 합성 폴더와 marker, credential 없는 환경, 포트 18765 비사용을 확인한 뒤 승인된 검사만 재개한다. 운영 앱을 자동 시작하지 않는다. 전체 onedir 묶음을 해시 대조하고, 이전 probe를 재실행해 기존 결과를 덮어쓰지 않는다.

승인된 작업은 여기서 종료한다.
