# BAT 비공개 배포 계약 구현·합성 검증 결과

2026-10-28 (Asia/Seoul). **최종 판정: CONDITIONAL.** 승인된 비실행 개발·합성 검증 범위를 완료했다. 실제 앱 실행·전달용 ZIP·일반 배포는 계속 미검증/차단 상태다. 이전 준비 단계의 BLOCKED 기록을 앱 실행 성공으로 변경하지 않는다.

## 1. Git 기준

- 브랜치: `codex/newsflow-bat-distribution-prep`.
- 시작: `99334215f103e1fea94cf8fd92fe43b317f81058`.
- 구현·집중 테스트 코드: `0de0e19deb8e1e89d2f6b5f4745b7e63fc981b6d`.
- 별도 기존 EXE 개발 브랜치는 `66c80be58205a6c52e4428fc4fb9171fe9734f3f` 그대로다. 이번에 추가 EXE 개발이나 재빌드는 하지 않았다.

## 2. 구현 범위

새 도구는 `tools/bat_distribution/`이며 기존 운영 실행 경로와 연결하지 않았다.

| 파일 | 구현 |
|---|---|
| `RUNTIME_LAYOUT.md` | Python3.14.7 AMD64, 표준 라이브러리/DLL, 고정 site-packages/product/controller/React/media/license 구조와 미확보 항목 |
| `lifecycle.py` | 절대 로컬 경로·프로그램/데이터 분리·reparse/ADS/상위 경로 거부, 런타임 파일 inventory, 하나의 지정 loopback 포트 예약 계약 |
| 동일 모듈 Stop | 소유 SID·PID·생성 ID·실행 경로·설치 ID·숨겨진 세션 nonce 대조, 동일 retained process lease에만 정상 종료 요청, timeout/통신 불명은 UNKNOWN·재시도 없음 |
| `zip_update.py` | 배포자 신뢰 선확인·서명 대상 digest·기존 signer pin/time/purpose 검사, 버전/sequence/지원 이전 버전·Python/ABI·ZIP/파일 해시·경로/형식/크기 검증 |
| 동일 모듈 transaction | 기존 `OfflineInstall`의 잠금·SQLite backup·키 불투명 복사·slot·atomic pointer·journal·확정 실패 복구·명시적 recover를 재사용 |
| `publisher-trust.json` | updatesEnabled=false, 빈 배포자 pin 유지 |
| `contract_entry.py` | 실제 Start/Stop/업데이트를 활성화하지 않는 거절 dispatcher. 환경변수/CLI 실행 허용 스위치 없음 |
| `templates/*.bat` | 따옴표 경로·DisableDelayedExpansion·내장 런타임/dispatcher 존재 검사·-I -B 호출·종료코드 전달. 실제 BAT/CMD 미실행 |
| `tests/` | 합성 파일·SQLite·서명 응답·가짜 포트·프로세스·ACL/잠금으로 이번 계약만 검증 |

기존 제품 `src/newsflow`, React, migration, 설치/업데이트 도구와 배포자 신뢰 원본은 수정하지 않았다. 기존 `windows_profile.unlinked`, `offline.relative/version/OfflineInstall`, `updates.publisher_matches`를 재사용했다. `create_app`이나 기존 앱 진입점을 import/실행하지 않았다.

## 3. 실동작과 계약 구현의 구분

### Start/Stop

`start_plan/prepare_start`는 하나의 고정된 비운영 포트를 한 번만 예약하고 보유 lease를 반환하는 로직이다. 충돌 시 fallback 없음, 잘못된 lease는 닫음, ACL precondition 거부 시 포트 동작 없음까지 합성으로 확인했다. **실제 Windows 소켓·현재 사용자 ACL 확인 backend는 아직 없다.**

`stop_owned`는 별도 열거/임의 PID 종료가 아니라 하나의 retained handle/session capability를 요구한다. 소유자·생성 ID·경로·설치 ID·nonce 불일치 시 종료 요청을 보내지 않는다. 정상 요청은 최대1회이며 timeout/OS 오류는 UNKNOWN으로 남긴다. kill API 자체를 제공하지 않는다. **실제 운영체제 handle·신호·프로세스 확인 backend는 없으며 host PID를 열거나 종료하지 않았다.**

BAT 템플릿과 CLI가 준비됐지만 실제 실행 기능이 완성됐다는 뜻은 아니다. 기본 dispatcher는 Start/Stop exit2, Update exit3으로 거절한다. Python runtime·제품·FFmpeg를 복사하거나 V3 차단된 앱을 source/Python으로 대신 실행하지 않았다. bootstrap/Origin/CSRF/DPAPI는 기존 제품 경계로 보존했고 새 backend에 재연결하는 실제 인수는 후속 미검증이다.

### ZIP 인증·업데이트

별도로 제공된 신뢰 정보가 없으면 파일 조회·추출·백업보다 먼저 거절한다. ZIP 자체의 hash와 파일별 hash는 **서명된 manifest bytes**에 결속하며 해시만으로 배포자 진위를 인정하지 않는다. verifier의 서명 대상 digest·고정 signer pin·timestamp·code-signing purpose를 확인하는 계약을 구현했다.

**실제 암호학적 서명 검증기·배포자 인증서는 미연결**이다. 기본 verifier는 항상 거절한다. 테스트의 SyntheticVerifier는 고정 합성 signature bytes를 비교할 뿐 실제 암호 검증이 아니다. tests에서 직접 주입한 가짜 신뢰를 BAT나 실제 업데이트에 사용할 공개 스위치는 없다. 실제 서명 체인/폐기/타임스탬프의 오프라인 검증은 NOT VERIFIED다.

검증 완료 시 ZIP bytes를 불변 복사로 보존하고 적용 시 원본 ZIP 경로를 다시 읽지 않는다. 사용자 데이터/키/미디어 목적지는 payload에 허용하지 않는다. 현재는 schema migration=none만 지원하고 migration 필요 릴리스는 거부한다. ZIP은 파일-only schema이며 explicit directory/extra/encrypted/symlink 항목도 거부한다. 최대 ZIP256MiB·총1GiB·파일512MiB·20000개·압축비200 제한은 실제 런타임 전체 크기와 아직 대조하지 않았다.

실제 디스크 백업·SQLite backup/restore·slot pointer와 journal은 **합성 임시 디렉터리에서** 기존 구현으로 검사했다. 파일 잠금과 Windows ACL은 test double이며 native 성능·정확성을 새로 인수한 것은 아니다. 기본 health callback은 없고, 테스트의 callback은 합성 파일만 다루었다. 실제 앱을 실행하는 health hook은 연결하지 않았다.

## 4. 신규 검증과 발견 사항

| 검증 | 결과 |
|---|---|
| Windows Python | 3.14.7, 기존 환경 재사용·새 패키지 설치 없음 |
| 최종 집중 단위 테스트 | **78 PASS / 0 FAIL / 0 ERROR / 0 SKIP**, 3.34초 |
| Ruff | PASS, 기존 전역 규칙 변경 없음 |
| 새 소스 AST | 직접 subprocess/socket/ctypes/app 초기화 import 없음 |
| BAT 정적 확인 | CRLF·경로 quoting·isolated flags 확인. CMD 실행 결과는 아님 |
| 실제 BAT/React/FFmpeg/V3 | 이번에 실행하지 않음, NOT VERIFIED |

검증 이력을 숨기지 않는다. 첫 실행은72 PASS/2 FAIL이었다. 테스트에서 `with sqlite3.connect(...)`가 transaction 종료만 수행하고 connection을 닫지 않아 Windows가 합성 DB 복원 파일 교체를 거부했다. **테스트만** `contextlib.closing`+명시적 commit으로 고쳤고 실패한2개 복구 검사는 재검증2 PASS였다. 운영/제품 복구 코드는 이미 closing을 사용하므로 변경하지 않았다. 이는 차단 EXE 재실행이나 V3 추가 진단이 아니다.

그 뒤 직접 관련된 경로·소유권·schema 경계4개를 더해 최종78 PASS로 확인했다. 최초 Ruff의 새 파일11개 style findings도 해당 신규 파일 안에서만 정리했다. 첫 실행과 최종 결과를 합산하지 않으며 skip/xfail 추가는 없다.

대표 검증: 지정 포트 충돌 시 대체 포트 요청0, 다른 사용자/재사용 PID/다른 실행 경로·세션의 stop 요청0, 서명 신뢰 없음·잘못된 signer/time/purpose·manifest/ZIP 변조 차단, 다운그레이드·sequence 재사용·요구 migration 차단, UNC/ADS/Device/reserved/상위·중복 경로·링크·미등록 파일 차단, 업데이트 성공 시 원본 데이터·이전 slot 보존, health 실패 시 SQLite·설정·가짜 키·미디어와 pointer 복원, 중단 journal 보존·자동 재시도 차단·명시적 복구, 손상 백업 복구 차단.

최종 [JUnit](junit-final.xml)과 [기계 판정](RESULTS.json)을 함께 보존했다. 첫 실패의 원본 로컬 자료도 합성 테스트 폴더에 보존했으며 GitHub에는 host 식별자 없는 최종 XML과 요약만 등록한다. 실제 운영 사용자 이름/계정/키를 기록한 자료는 아니다.

## 5. 기존 증거·보호

- 기존 Windows CI45 PASS, 설치19 PASS, FFmpeg7 PASS는 **과거 증거**로 재사용했다. 신규 CI나 최신 BAT 전체 앱 결과로 표시하지 않는다.
- 전체 Python 회귀·Guard 보안 감사·V3 분석·샘플 바이너리 무결성/권리 감사를 반복하지 않았다.
- 기존 샘플12개 rightsVerified:false와 원본·사용자 복사본·매니페스트를 그대로 뒀다. 새 외부 전달 목록에는 샘플0개이며 ZIP validator도 sample payload를 거부한다.
- 런타임/제품이 든 최초·업데이트 ZIP은 **생성하지 않았다**. 단위 테스트의 합성 ZIP은 임시 파일이며 사용자 전달용이 아니다.
- 기존 EXE/Setup/Update 후보·FFmpeg source/notice 자료는 변경하지 않았다. 실제 서명·라이선스·재배포 권리 미완료 상태도 유지한다.
- 운영 앱/8765/DB/키/OAuth/설정/미디어/백업을 사용하거나 변경하지 않았다. 테스트 파일은 별도 합성 폴더이고 새로운 Windows 계정이나 DPI 변경도 없다.
- 실제 AI/OAuth/SNS·외부 사용자 전달0, V3 설정/예외/전역 ACL 변경0. 기존 미추적 `validation/`은 보존했다.
- 읽기 전용 Git 확인: main `aa2f056d78ceed24874d0b4c50c6033f7168bf4d`, 기존 EXE 브랜치 `66c80be58205a6c52e4428fc4fb9171fe9734f3f`. PR35는 open/Draft/미병합, head `75626f74cc1bfe750d24132e44019bcda478247b`이며 수정하지 않았다.

## 6. 남은 인수 조건

공식 보안 정책 해결 전 실제 앱을 이 BAT 경로로 실행하지 않는다. 이후 별도 승인된 단계에서만 정식 독립 런타임 및 전체 의존성/미디어 라이선스를 확보하고 실제 Windows profile/port/process backend, 로컬 인증, 건강 확인을 연결한다. 실제 publisher signature verifier와 별도 신뢰 앵커 확보 후 signed ZIP과 오프라인 업데이트·실패 복구를 검증해야 한다. 실제 앱 시작·종료, V3 활성 상태, 새로운 사용자/PC, GUI·DPI는 이번에 PASS가 아니다.

승인된 계약 구현·정적·합성 검증은 완료했고 **CONDITIONAL**로 제출한다. 실제 실행·업데이트 인수와 사용자 배포는 아직 허용/완료된 상태가 아니다. 추가 실행·운영 반영·PR 병합 없이 이 작업을 종료한다.
