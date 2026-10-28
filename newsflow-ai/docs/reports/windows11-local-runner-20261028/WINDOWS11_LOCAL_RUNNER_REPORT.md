# Windows 11 전용 격리 테스트 실행기 및 최종 GUI 검증

작성일: 2026-10-28 · **최종 판정: BLOCKED**

## 1. 기준과 결과

- 저장소: `jsbae1979-prog/JSBAE`
- 기준 브랜치: `codex/newsflow-windows11-final-validation-20261028`
- 기준 HEAD: `abc0085f727d00455ab97cf94e06819e5861c1fa` (작업 시 원격 최신값 확인)
- 신규 검증 브랜치: `codex/newsflow-windows11-local-runner-20261028`
- 실행기·집중 검사 코드: `97b1f6ad7926c309c2ecdbf66252252f38360808`
- Windows 11 Pro, 64비트, 10.0.26300 / build 26300, Python 3.14.7
- 신규 집중 검사: **8 PASS / 0 FAIL / 0 ERROR / 0 SKIP**. 구문 검사: Python 파일 6개 PASS.
- 실제 앱 실행: **1회 시도 후 BLOCKED**, 추가 앱 실행 없음.
- 실제 GUI 12개 화면 / HTTP MP4 3개 / 실제 OS DPI: **NOT VERIFIED**.

기존 22/15/9/21/59 PASS 및 로컬 FFmpeg 4 PASS는 이전 증거로 재사용한다.
이 수치를 이번 실행기의 신규 GUI·미디어 검증 결과로 합산하지 않는다.
전체 Python 회귀, Guard 기존 보안 검사, 디자인·샘플 원본 감사는 반복하지 않았다.

## 2. 새 로컬 실행 경로

`tools/windows_local_validation/`에 별도 실행기를 추가했다. 기존 CI 실행기의
환경 조건을 제거하거나 CI 환경변수를 위조하지 않았다. 기존 CI 전용 파일,
운영 Guard, 설치된 filelock, Python/React 제품 코드는 변경하지 않았다.

| 파일 | 역할 |
|---|---|
| `launch.py` | 새 합성 프로필, 최소 환경변수, 고정 Python 및 소유 자식 1개 실행·정리 |
| `runner.py` | Guard-first → 실제 create_app → 제한된 HTTP/ASGI 연결, 차단 시 중단 |
| `local_policy.py` | 합성 경로/SQLite, 소유 127.0.0.1:18765 listener, 외부 통신·프로세스 차단 |
| `guard_capability.py` | 기존 제한 native facade의 로컬 정책 등록 접점만 분리 |
| `seed.py` | 합성 뉴스 3건·대본·저장된 캐릭터 상태 준비; 공급사 호출 없음 |
| `test_local_policy.py` | 새 실행기의 순수 합성 경계 계약 8개 |
| `SOURCE_HASHES.json` / `BORROWED_SOURCES.json` | 새 실행기 및 변경하지 않은 기존 경계의 바이트 고정 |

실제 앱의 Origin·CSRF, 정적 React 자산, FileResponse/Range를 재사용하도록 구현했다.
ASGI lifespan은 진입하지 않으며 스케줄러/게시/영상 background thread는 시작하지 않는다.
실제 키·OAuth·DPAPI 자료 및 proxy 설정을 전달하지 않는다. 외부 DNS/인터넷,
임의 shell/worker, 유료 생성·OAuth·SNS 실행 경로는 허용하지 않는다.
정상 종료는 소유 합성 폴더의 STOP 신호로 처리하며 강제 정리는 별도 기록하도록 했다.

이 경계는 신뢰된 합성 Python 검증 실행기다. 악성 Python 코드에 대한 OS 수준
완전 격리를 주장하지 않는다. Fake 생성 전체 동선이나 앱→FFmpeg 연결도 아직 입증하지 않았다.

## 3. 실제 단일 실행과 차단 원인

증거: [local-attempt-result.json](local-attempt-result.json),
[process log](local-attempt-process.log), [해당 시도 코드 해시](ATTEMPT_SOURCE_HASHES.json).

1. Guard-first 초기화와 기존 Rtl/FileLock 접점을 통과했다.
2. 실제 `create_app`이 반환했지만, 초기화 중 정책 거절 3건이 이미 누적됐다.
   - `outside-fixed-read-roots` 2건
   - `link-creation` 1건
3. 라이브러리가 PermissionError를 처리하여 초기화가 계속된 상태였다.
4. 초안 실행기는 이 누적 거절을 서버 준비 전 검사하지 않아 READY 한 줄을 출력했다.
   이어서 중단 flag에 따라 HTTP 요청 **0건** 상태에서 서버를 닫았다.
5. 최종 기록은 BLOCKED다. **READY 문구와 JSON의 `real_create_app: PASS`는
   정책을 통과한 전체 앱/GUI 성공 증거가 아니다.** 해당 필드는 함수 반환만 뜻한다.

이 최초 기록에는 거절 대상 경로와 호출 stack이 저장되지 않았다. 따라서 정확한
두 경로와 링크 호출자는 **원인 미확정**이다. 정적 확인만으로 임의의 파일이나
패키지를 원인으로 확정하지 않았다. native ntdll 호출이 이번 직접 차단 원인이라고
다시 주장하지 않는다. 기존 FileLock은 실제 획득/해제 7회가 균형을 이뤘다.

거절 확인 후 읽기 범위·링크·DLL·native/thread 권한을 추가하지 않았으며
같은 앱 경로를 다시 실행하지 않았다. 다른 진입점/EXE/운영 앱을 사용하지 않았다.

### 실행기 자체 최소 보완

누적 거절이 있으면 create_app 직후, 합성 seed 이후, 서버 구성 전에 중단하는
checkpoint를 추가했다. 향후 진단용 호출 위치는 입력/비밀값 없이 기록하도록 했다.
라이브러리가 예외를 처리해도 다음 단계로 진행하지 않는 검사 2개를 추가했다.
**이 보완본의 전체 앱 실행은 미실행**이며, 단위 검사 성공을 앱 성공으로 대체하지 않는다.

기존 FileLock 소유권은 원래 thread에 고정된다. AnyIO sync-route에서 잠금을
요청하거나 등록되지 않은 하위 character 잠금 경로를 사용하는 경우는 여전히
차단될 수 있다. 이 경계를 변경하거나 잠금 없는 코드로 대체하지 않았다.

## 4. GUI 12개 화면 및 주요 동선

| 화면 | 이번 Windows 11 GUI | 사유 |
|---|---|---|
| 홈 | NOT VERIFIED | 허용된 HTTP 세션 시작 전 중단 |
| 콘텐츠 제작 홈 | NOT VERIFIED | 동일; 승인 UI 소스 무변경 |
| 뉴스 쇼츠 | NOT VERIFIED | TOP 3→대본→제작·저장 사용자 동선 미실행 |
| 캐릭터 쇼츠 | NOT VERIFIED | 샘플 선택→스토리→견적·장면 동선 미실행 |
| 독립 AI 이미지 | NOT VERIFIED | 초안→Fake 생성→결과 확인 미실행 |
| 뉴스 TOP 3 이미지 | NOT VERIFIED | 3건 독립 결과·문구 검토·저장 미실행 |
| 뉴스 스튜디오 | NOT VERIFIED | 검색→기사→저장 분석→제작실 이동 미실행 |
| 자동화 센터 | NOT VERIFIED | 예약 실행 없음 |
| 라이브러리 | NOT VERIFIED | 샘플·내 콘텐츠 조작 미실행 |
| 게시 스튜디오 | NOT VERIFIED | 검토·승인 UI 미실행; 실제 게시 없음 |
| 성과·비용 | NOT VERIFIED | 실제 계정/비용 조회 없음 |
| 설정·관리 | NOT VERIFIED | 비밀값 사용·복호화 없음 |

새 GUI 캡처를 만들지 못했으므로 이전 캡처를 이번 실제 Windows 11 결과로
표시하지 않는다. 새 시각 MATCH 판정도 부여하지 않는다.
기존 디자인 비교는 [완료 제작실 보고서](../core-studios-final-match-20261028/CORE_STUDIOS_FINAL_MATCH_REPORT.md)와
[기존 비교 자료](../core-studios-final-match-20261028/visual-comparison-final.html)를 재사용한다.

## 5. MP4 및 DPI

| 항목 | 이번 결과 |
|---|---|
| 뉴스 쇼츠 샘플 MP4 1개 HTTP 재생·일시정지·탐색 | NOT VERIFIED |
| 캐릭터 쇼츠 샘플 MP4 2개 HTTP 재생·일시정지·탐색 | NOT VERIFIED |
| 실제 HTTP Range / Content-Type / 길이 / 9:16 | NOT VERIFIED; 응답 구현 재사용만으로 PASS 처리 안 함 |
| 앱→로컬 FFmpeg 새 합성 | NOT VERIFIED; 프로세스 권한 추가 없음 |
| 기존 로컬 FFmpeg 30초 합성 | 기존 4 PASS 재사용; 이번 신규 실행 아님 |
| 실제 Windows OS DPI 100% | NOT VERIFIED |
| 실제 Windows OS DPI 125% | NOT VERIFIED |
| 실제 Windows OS DPI 150% | NOT VERIFIED |
| 실제 Windows OS DPI 200% | NOT VERIFIED |

브라우저 viewport/CSS zoom/devicePixelRatio는 OS DPI 증거로 사용하지 않았다.
운영 사용자 세션의 DPI·로그아웃·등록 정보는 변경하지 않았다.
샘플 원본 파일, 사용자별 복사본, manifest는 변경하지 않았다.

## 6. 자원 및 보호 결과

증거: [environment-and-cleanup.json](environment-and-cleanup.json).

- 소유 테스트 자식 PID 1928 종료, 남은 테스트 프로세스 없음.
- 18765 listener 없음. 8765는 기존 PID **55740**으로 유지.
- native handle 0, CRT descriptor 0, native buffer 0, unresolved call 0.
- Rtl 할당/해제 7/7, 실제 잠금/해제 7/7, 열린 SQLite 0, 살아 있는 테스트 thread 0.
- cleanup error 0. 자식 exit 0은 정리 성공이며 GUI 인수 성공은 아니다.
- 실제 운영 파일/DB/ledger/키/OAuth/미디어/백업을 테스트 입력으로 사용하지 않았고
  읽기·쓰기·복호화·복사·재시작 작업을 수행하지 않았다. 운영 파일 전수 해시 감사는 반복하지 않았다.
- Guard의 기존 DLL/심볼 표 불변, 빌려 쓴 보안 모듈 source 해시 일치.
- 기준 HEAD 대비 `src`, `frontend`, 기존 native/Guard/CI 도구의 tracked 변경 0.
  따라서 보호된 12개 화면 및 샘플 원본의 제품 소스 변경 0.
- 기존 미추적 `validation/` 보존. reset/clean/stash/force push 없음.
- 실제 유료 API·SNS·OAuth·DPI 변경 0. 운영 배포/재시작 없음.
- main `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`, PR #35
  `75626f74cc1bfe750d24132e44019bcda478247b` Draft/open/unmerged 유지.
- 완료 제작실 브랜치 `5a8a622748464897033a49e421725812267245d9` 및
  관리 화면 완료 브랜치는 변경하지 않았다.

## 7. 신규 집중 결과와 남은 조건

[집중 검사 로그](focused-policy-tests.log): 고정 포트, 합성 쓰기, 비밀 파일 차단,
소유 listener, DNS 차단, 임의 프로세스 차단, 처리된 예외 이후 중단,
Guard 누적 거절 이후 준비 금지의 **8 PASS**. 기존 검사와 중복 합산하지 않는다.
TypeScript/Vite는 변경되지 않은 기존 UI 소스를 이번에 빌드하여 통과했다.
Vite의 런타임 font 경로 및 큰 chunk 안내는 남아 있으며 UI 실행 성공 증거는 아니다.
Windows CI 전체·Python 전체 회귀는 새로 실행하지 않았다.

남은 차단은 초기화 시 두 읽기 경로와 링크 호출의 정확한 주체/필요성을 특정하지
못한 것이다. 현재 기록만으로 해당 권한을 안전하게 승인·확장할 수 없다.
또한 thread별 FileLock 및 미등록 잠금 경로의 실제 GUI 호환성은 미검증이다.
따라서 로컬 GUI/HTTP 미디어/DPI 최종 인수는 **BLOCKED**로 유지한다.

어댑터 추가 개발, 경계 확대, 앱 재실행, 운영 적용, PR 병합 및 유료 호출 없이 종료한다.
