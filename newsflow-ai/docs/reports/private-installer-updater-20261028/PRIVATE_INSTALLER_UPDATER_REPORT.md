# 비공개 Windows 설치·오프라인 업데이트 개발 결과

2026-10-28. **최종 판정: BLOCKED.** 두 EXE와 비공개 대응 소스 묶음은 생성했다. 설치·제거·재설치와 데이터 보존 보정은 통과했으나, 다른 합성 프로필의 앱 프로세스 생성이 Windows `WinError 5`로 거부됐다. 실행 정책 원인은 미확정이다. 실제 배포자 서명과 자산 권리도 확보되지 않았으므로 외부 전달·운영 교체는 금지 상태다.

## 1. 기준과 브랜치

- 작업: `codex/newsflow-private-installer-updater`, 구현·진단 체크포인트 `42392fd1afd23882bb542bd94b4ee3ee71b92e8d`. 이 보고서를 포함한 최종 커밋은 별도 보고서 HEAD다.
- 시작 HEAD: `800c9591907038484800467adb69ee6f51748b06` — 이전 3개 MP4 등록 성공을 유지했다.
- `f44f65d` 업데이트 복구와 `ce114227` 사용자 보안 결과는 시작 HEAD의 조상으로 포함돼 있다. 별도 완료 브랜치를 병합·수정하지 않았다.
- 실제 payload와 migration 소스: `0f14ac3851cbdb370496552a62cd4d92bccd45a8`. 설치 정의의 빈 폴더 정리 보정: `75d5ff19b121caeb0ccad890abbc95c594e4346c`.
- 이후 소스 브랜치에 추가한 비민감 실패 진단은 **보관된 두 후보 EXE에 포함됐다고 주장하지 않는다**. 진단 런처는 실패 원인 확인용 별도 로컬 산출물이다.

## 2. 생성 파일과 보관

| 파일 | 바이트 | SHA-256 |
|---|---:|---|
| `NewsFlowAI_Update_v1.1.0.exe` | 123583587 | `9f77700f7bddf1e347b00b45642330f9ac485c954014171ef694b2a992f8909e` |
| `NewsFlowAI_Setup_v1.0.0.exe` | 118134171 | `46eb1254658c7498e3ac625bf5e4b023ed01517a496572c50812437ca5596b93` |

보관: 승인된 로컬 `private-installer-updater-20261028/private-candidates/` 폴더. 두 파일 모두 **무서명 개발 검증 후보**다. `PRIVATE_CANDIDATE_ONLY.txt`, 안내서, SHA 목록, 소스 7개와 빌드·고지 자료를 같이 보관했다. GitHub에는 실행 파일을 올리지 않았으며 Releases·공개 다운로드 사이트·자동 업데이트 서버도 만들지 않았다.

패키지는 Windows Python 3.14.7 / PyInstaller 6.22.3 / Inno Setup 6.7.3 기반이다. Node는 사용자 런타임에 필요하지 않다. Python DLL, React JS/CSS/폰트, FFmpeg/FFprobe 및 샘플이 포함된다. 테스트 Guard·합성 DB·키·실행 로그는 payload에 포함하지 않는다.

## 3. 최초 설치와 사용자별 경계

- Windows 11/현재 사용자 전용 설치이며 Inno 로그의 administrative install mode는 No다. 새 Windows 계정을 만들거나 운영 설치본을 교체하지 않았다.
- 프로그램: `%LOCALAPPDATA%/Programs/NewsFlowAI-Private/slots/<version>`와 안정된 `NewsFlowAI.exe` 진입점.
- 데이터: `%LOCALAPPDATA%/NewsFlowAI-Desktop/v1`. 프로그램과 분리하고 소유 SID·보호 ACL을 확인한다. 기존 운영 프로필을 자동 채택하지 않는다.
- 기존 CurrentUser DPAPI, bootstrap 인증, HttpOnly 쿠키, Origin/CSRF와 비용·게시 승인 코드를 재사용한다. 설치 시 scheduler/task 등록·앱 자동 실행은 없다.
- 실제 새 Windows 표준 사용자·새 PC·다른 SID의 이번 설치 인수는 NOT VERIFIED다. 기존 Windows Server 두 사용자 격리 결과와 구분한다.

## 4. 오프라인 업데이트와 복구 구현

외부 다운로드 기능 없이 한 파일에 payload와 매니페스트를 포함한다. 실제 인증서가 없으므로 `updatesEnabled:false`와 빈 배포자 pin을 유지한다. EXE의 Authenticode·배포자 인증서 SHA-256·타임스탬프 확인이 사용자 프로필·설치 데이터 접근보다 먼저 이뤄진다. 서명 검사를 끄는 CLI·환경변수는 없다.

검증 통과 후의 내부 트랜잭션은 다음과 같다.

1. 설치 버전·지원 경로·증가하는 순서·파일 전체 SHA-256 확인. 현재 정의는 1.0.0→1.1.0이다.
2. 설치 잠금과 기존 desktop 잠금 확보. 실행 중이면 정상 종료를 요구하고 강제 종료하지 않는다.
3. 전체 프로필 백업. SQLite는 backup API로 일관된 사본을 만들고 키/DPAPI는 불투명 바이트로 복사한다. 운영 자료를 사용하지 않는다.
4. 새 버전 슬롯에 복사·검증. 동일 소스 migration과 SQLite 무결성, 새 런타임·React·FFmpeg 사전 점검 후에만 현재 포인터 전환.
5. 확인된 실패는 이전 포인터·DB/설정을 복원한다. 결과 불명·전원 중단은 journal을 남기고 재실행/재업데이트를 차단한다. `--recover-update`는 명시적 복구이며 업데이트 재요청이 아니다.

백업은 사용자 데이터의 `update-backups`에 보존하고 다음 백업에서 재귀 복제하지 않는다. 제거는 알려진 프로그램 파일만 지우고 데이터·백업은 남긴다. 비가역 migration/실제 사용자 자료의 복구 가능성이 확인되지 않으면 전달 승인을 하지 않는다.

**구분:** 자동 health 검사는 migration/런타임 사전 점검이다. 실제 새 버전의 전체 GUI·사용자 작업 성공 검사와 같지 않다. 두 후보 payload는 동일 제품 코드와 서로 다른 릴리스 메타데이터로 구성했다. 실제 기능 변경이 있는 두 제품 버전의 서명된 오프라인 업데이트 성공으로 표시하지 않는다. 기존 서로 다른 제품 코드의 42 PASS는 별도 과거 증거다.

## 5. 신규 샘플 12개

캐릭터 3·독립 이미지 3·뉴스 TOP3 이미지 3·무음 12초 MP4 3을 후보에 포함했다. 기존 원본·ID·사용자 복사본·숨김 상태를 삭제하지 않았다. 신규 v2 ID를 사용하고 `rightsVerified:false`, sample 표시, 비편집 원본/무음 예제 설명을 유지했다. 실제 AI 공급사 작업 성공이나 실제 뉴스 분석으로 표시하지 않는다.

포스터 3개도 포함해 기존 Samples 카탈로그에서 12개를 로딩했다. PNG 포스터를 JPEG로 고정 응답하던 한 줄을 실제 PNG/JPEG 형식에 맞췄다. 뉴스·캐릭터 제작 엔진, 프런트 디자인과 저장 schema는 바꾸지 않았다.

기존 28개 생성·디코딩 증거를 재사용했다. 최신 후보의 12개 샘플 전체 브라우저 조작·HTTP 재생을 새로 PASS로 표시하지 않는다. 패키지 포함/카탈로그 로딩과 실제 재생은 별개다.

## 6. 새 FFmpeg와 라이선스

- FFmpeg: `26f21efe3d78e27699baa71c6fe668c28aaffd56db8ce11f361ed71987119dea`
- FFprobe: `a9e63afd32450722e6b1ab94dac955edc643c4943322713c4652185f10246e50`

기존 고정 소스 7개와 Windows 네이티브 MSYS2/MinGW 도구로 로컬 재빌드했다. CI 환경변수를 위조하지 않았다. 기존 제품의 Gyan 바이너리를 교체하지 않았고 후보에서만 새 바이너리를 선택했다. libx264를 포함하는 GPL/version3 정적 구성이지 LGPL 전용 구성이 아니다. 네트워크 기능은 비활성이다.

`corresponding-sources/`에 원본 아카이브 7개, 해시·commit·고지, 실제 recipe·빌드 설정·컴파일러·도구 목록과 바이너리 대응표를 보관했다. 만료되는 CI 링크만 제시하지 않는다. 고지 원문은 유지하고 설치 경로만 평탄화했다. 자료 수집과 최종 법적 준수를 동일시하지 않는다. 외부 전달 전 정적 런타임/시스템 라이브러리 예외 등 대응 소스 완전성과 모든 포함 자산의 권리를 확인해야 한다.

## 7. 검증 결과 — 중복 합산하지 않음

| 범위 | 결과 | 근거/한계 |
|---|---|---|
| 새 업데이트 집중 검사 | 43 PASS / 0 FAIL | Windows 3.14.7 로컬 및 CI, 서로 다른 실행 |
| 새 오류 문구 비밀값 보호 | 추가 2 PASS | 원시 예외 문자열을 출력하지 않음; 43개는 재사용 |
| 배포 진입점 회귀 | 7 PASS | 일반/브라우저 미실행·정상 종료·무결성 경계 |
| 새 FFmpeg 실물 | 7 PASS | 실제 뉴스·캐릭터 30초 1080×1920 MP4, 한글 자막·합성·전체 디코딩·시스템 DLL |
| 첫 Windows11 설치 시도 | 27 PASS / 1 FAIL | 기동·재기동·익명 API403·무서명 Update 차단·데이터 보존 통과; 빈 폴더 재설치 결함 발견 |
| 설치기 보정 후 전용 검증 | 19 PASS / 0 FAIL | 설치/제거 2회, 빈 프로그램 폴더 제거, DB·설정·숨김·DPAPI·미디어 보존. 앱 실행은 하지 않음 |
| 다른 새 프로필의 전체 앱 | 2 PASS / 1 FAIL | 설치/포인터 통과, Windows CreateProcess AccessDenied 미해결 |
| 실제 인증서 기반 업데이트 | BLOCKED | 제공된 실제 배포자 인증서 없음. 후보는 실행 시 정상 차단됨 |
| 완전 오프라인 인증서 체인/폐기 확인 | NOT VERIFIED | 실제 인증서와 오프라인 새 PC 필요 |
| 최신 후보 전체 GUI·DPI | NOT VERIFIED | 기존 GUI 12화면/샘플 재생은 과거 증거. OS 설정 변경 없음 |

확인된 CI: [40675363900](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40675363900), 코드 `75d5ff1`, job `122772271403`, **43 PASS**. 후속 소스의 오류 출력 보완은 별도 로컬 2 PASS다. 최신 CI [40678895017](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40678895017)는 코드 `42392fd`에서 **45 PASS / 0 FAIL**을 기록했다. 전체 Python 회귀·Guard 감사·디자인 감사·기존 샘플 무결성 감사를 반복하지 않았다. skip/xfail 추가는 없다.

## 8. 해결된 결함과 남은 실행 거부

해결: Windows 잠금 파일 읽기, SQLite 연결 수명, fsync 핸들 모드의 초기 구현 문제. Inno 코드 주석 문법, 긴 경로, 제거 후 빈 프로그램 폴더도 보정했다. 실패 기록을 성공으로 덮어쓰지 않고 JSON 증거를 보존했다.

미해결: 합성 프로필 w3에서 `private_entry.main → subprocess.Popen`의 Windows `CreateProcess`가 `PermissionError / WinError 5`를 반환했다. 진단 빌드의 원래 호출 줄은 119다. 동일 설치 파일의 ACL/해시 검사는 통과했고, 직접 읽기 전용 runtime-check 프로세스 생성도 같은 Windows 오류로 거부됐다. 관련 실행 정책 이벤트 증거는 확보하지 못했으므로 Guard·Defender·SmartScreen 중 어느 원인이라고 단정하지 않는다.

이 거부 후 앱 파일의 경로 변경·재인코딩·권한 확대·정책 완화로 실행하지 않았다. 이후 작업은 정식 제거와 설치기 전용 보존 검사로 제한했다. 테스트 앱과 등록 항목을 제거하고 합성 데이터·실패 증거를 남겼다. 강제 종료로 PASS 처리하지 않았다. 첫 12초 진단은 CTRL_BREAK 후 `0xC000013A`로 종료되어 정상 종료 PASS로 집계하지 않았다. 이후 진단의 WinError5 및 설치기 전용 성공과 구분했다.

## 9. 운영·보호 상태

- main `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`, PR35 head `75626f74cc1bfe750d24132e44019bcda478247b`; PR35 Open/Draft/미병합 유지.
- 이전 sample/FFmpeg, recovery, distribution 완료 브랜치 HEAD를 유지했다.
- 프런트 전체, 기존 샘플 원본, 뉴스·캐릭터 엔진, DB migration 원본의 시작 HEAD 대비 변경 0.
- 운영 앱 종료·재시작·교체 0. 읽기 전용 확인에서 8765 listener는 0개였다. 임의 복구하지 않았다.
- 운영 DB·키·OAuth·미디어·백업을 테스트 입력으로 쓰거나 변경하지 않았다. 금지 자료의 전후 파일 해시 감사를 새로 실행한 것은 아니다.
- 실제 유료 AI/OAuth/SNS 호출 0. 기존 미추적 `validation/`을 보존했고 reset/clean/stash/force push를 사용하지 않았다.

## 10. 남은 조건과 재개점

1. Windows의 실제 프로세스 생성 거부 원인을 공식 로그/허용된 테스트 환경에서 확인하고 일관된 앱 기동을 검증해야 한다. 이번 결과는 전체 앱 인수 PASS가 아니다.
2. 실제 배포자 인증서 확보·DER SHA-256 pin·서명·타임스탬프·오프라인 검증과 실제 signed update/rollback 검증이 필요하다. 인증서가 생겨도 현재 오류가 자동 해결된다고 단정하지 않는다.
3. 신규 12개 및 다른 포함 자산의 사용·재배포 권리 확인, FFmpeg 대응 소스/런타임 고지의 최종 전달 조건 검토가 필요하다.
4. 새 Windows11 표준 사용자/새 PC, 실제 코드가 다른 차기 버전과 사용자 자료 migration, 최신 샘플 전체 브라우저 재생·DPI는 별도 미검증이다.

파일과 개발 증거는 보존했으며 실제 사용자 전달, 운영 전환, 공개 게시, PR 병합은 수행하지 않았다. **현재 두 파일은 RELEASE READY가 아니다.**
