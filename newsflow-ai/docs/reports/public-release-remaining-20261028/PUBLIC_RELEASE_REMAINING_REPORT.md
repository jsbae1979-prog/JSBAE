# 공개 배포 잔여 차단 사항 집중 해결 결과

2026-10-28 · **최종 판정: BLOCKED — 일반 사용자 공개 배포 기준**

이번 결과는 준비 문서 완료와 실제 공개 배포 조건 충족을 구분한다.
FFmpeg 정확한 대응 소스 전체·샘플 상업 재배포 증빙·Windows11 신규 사용자
설치 환경이 아직 확보되지 않았고, 실제 배포자 인증서는 외부 확보 대상이다.
원본·권리·실제 계정을 코드나 flag로 만들어내지 않았다.

## 1. 브랜치·변경 범위

- 시작 기준: `3103560e62c12f73d65c4832f99b3b3831808d93`.
- 작업 브랜치: `codex/newsflow-update-recovery-final-20261028`.
- 기존 `codex/newsflow-release-evidence-final-20261028`는 시작 HEAD 그대로 보존.
- 검증 코드 SHA 및 최종 보고 HEAD는 CI_EVIDENCE.json과 이 보고서 포함 Git 로그 참조.
- 제품의 최소 변경: packaged desktop의 `--no-browser` 옵션(인증 유지),
  앱 정리 뒤 console KeyboardInterrupt를 정상 종료로 처리,
  PyInstaller frozen interpreter의 UTF8 옵션.
- 추가: CI 전용 Inno slot 정의/실제 다른 제품 update probe, 집중 entry tests,
  source closure/샘플 재제작·서명 준비 자료/비교 recipe 참고 원본.
- UI/제작 엔진/API/데이터 schema/운영 Guard/설치된 filelock은 변경하지 않음.
- 기존 미추적 `validation/` 보존. reset/clean/stash/force push 없음.

## 2. FFmpeg

실제 binary `-version`에서9.0.2-essentials/GPLv3/static 및 GCC16.2.0 Rev3를
확인했다. 기존 공식 upstream source3개/20,459,764bytes의 경로·크기·해시·
버전 증거를 재사용하며 로컬 파일 존재를 확인했다. x264/x265 source 확보가
최종 Gyan binary의 private patch·build recipe 대응까지 증명하지는 않는다.

기존 build README의 활성 외부 구성요소/hardware interface55개를 매트릭스로
작성했다. 버전 미기록18개는 시스템 interface/SDK와 실제 라이브러리 여부를
각각 검토해야 하며, 정적 link map/간접 dependency closure도 미확보다.
정확한 compiler package/patch·dependency build flags·전체 source 제공 자료가
부족하므로 **완전한 GPL 대응 소스 적합성은 NOT VERIFIED/공개 배포 BLOCKED**다.

source/binary hash별 immutable 제공 구조와 GPLv3 대응 자료 checklist를
작성했다. 기존72개 고지 자료를 보존했다. BtbN의 공개 recipe/reference4개를
고정 commit `b4a2b1d7cc241786eb8e2b588a7ade40cad48bbd`로 확보하고
원본 license·URL·SHA와 함께 보존했다. script 실행·대체 binary 도입은 없다.
GPL variant는 호환성/소스 closure 인수 후 비교할 후보이며, x264/x265 없는
LGPL variant는 현 libx264 엔진의 drop-in 대체가 아니다.

상세: [대응 소스 제공 준비](FFMPEG_CORRESPONDING_SOURCE_PLAN.md),
[구성요소55개](FFMPEG_COMPONENTS.md), `FFMPEG_CLOSURE_MATRIX.json`.

## 3. Windows11 신규 사용자 설치

현재 PC OS는 Windows11 Pro10.0.26300이다. 기존 운영 console1세션만
확인됐고 별도 허용된 신규 사용자 세션/깨끗한 테스트 Win11 VM·PC는
확보되지 않았다. 실제 Win11 신규 설치·최초 실행·다른 SID DB/API/DPAPI·
포트 동시 실행은 **NOT VERIFIED**다. 운영 계정/키·DB를 대용하지 않았다.
OS DPI100/125/150/200%도 이번에 변경/검증하지 않았다.

기존 Windows Server 표준 사용자2개 실제 SID 격리PASS,
Windows11 GUI12화면/MP4 3개/SAPI 및 이전 설치CI를 재사용한다.
Server에서 새로 수행한 이번 candidate test를 Win11 인수로 확대하지 않는다.
[실제 환경 범위](WINDOWS11_TEST_SCOPE.md) 참조.

## 4. 실제 다른 제품의 업데이트 실패 복구

이전 product source9a54ec8과 최신 후보의 실제 Python entry/auth/profile/port
코드가 다르며 각기 EXE를 빌드했다. 동일 payload의 Setup 버전명 변경을
실제 제품 업데이트라고 표시하지 않는다. 이전 Python product source는
유지하고 두 후보의 packaging UTF8 옵션만 같은 보정으로 적용했다.
따라서 과거 배포 EXE 그대로의 byte-identical 재현 검증이라고 주장하지 않는다.

신규 CI는 실제 Inno 신규 설치→이전 앱HTTP 기동→합성 사용자 데이터 생성→
신제품 복사 중 실제 파일 잠금 오류 주입→이전 slot/data 보존·재기동→신제품 설치→
activation 전환 실패/이전 pointer 복구·재기동→신제품 정상 전환/기동/재시작→
제거/데이터 보존을 검사한다. 현재 서명 public updater는 활성화하지 않았다.

**최종 CI 결과는 아래 검증 결과 절과 CI_EVIDENCE.json/recovery-results.json에
기록한다. 실행 완료 전의 계획을 PASS로 합산하지 않는다.**

이번 실패는 신제품 최초 기동/DB migration 전이다. post-migration DB rollback,
전원 중단·실행 중 파일 교체·기본 profile 경로 migration·실제 서명 public apply는
별도 **NOT VERIFIED**다. 현재 실제 public updater는 배포되지 않았으며,
검증용 active pointer를 이미 사용자 제품의 자동 업데이트 기능으로 설명하지 않는다.
[정확한 구현/검증 범위](REAL_UPDATE_RECOVERY_SCOPE.md) 참조.

## 5. 새로 발견한 패키징 문제와 최소 수정

초기2개 CI run의 이전 frozen 앱은 UnicodeEncodeError로 HTTP 준비 전에
실패했다. PYTHONUTF8 환경변수만으로는 frozen interpreter가 바뀌지 않아
PyInstaller 공식 `X utf8` 옵션을 spec에 추가했다. 그 다음 run에서 실제
HTTP/React 응답은 성공했지만 정상 종료 코드 검사가 실패했다.

정상 종료를 강제 종료나 단순 허용 코드 확대만으로 PASS 처리하지 않는다.
역사적 후보는 새 server_stop 기록과 정확한 KeyboardInterrupt-only 종료를
확인하고, 최신 entry는 Uvicorn lifespan 정리 후 재전파되는 사용자 종료 신호를
정상 종료로 처리한다. 다른 RuntimeError는 계속 전파하며 timeout15초는 유지한다.
실패4회 원본 결과는 CI_FAILURE_HISTORY.json/CI_THIRD_RUN_FAILURE.json/
CI_FOURTH_RUN_FAILURE.json에 보존한다. 네번째 run은 실제 이전 앱의
정상 정리를 확인했으나 ssPostInstall 예외가 Setup exit0을 반환해 실패
주입으로 인정하지 않았다. 이후 합성 candidate 대상의 실제 Windows
sharing violation으로 복사 오류를 주입하도록 변경했다.

## 6. 샘플12개

실제 ChatGPT 원본 생성 대화/참조 입력 권리/파일별 상용 설치 재배포 허락의
추가 증빙이 없다. **12개 모두 rightsVerified:false**이며 원본/manifest와
기존 사용자 복사본은 변경하지 않았다. 샘플 미디어 검사를 반복하지 않았다.

파일별 교체 사양12개, 자체 도형·벡터 authoring brief/원본·입력·tool·출력 hash/
권리 허락·review 기록 양식을 작성했다. MP4 3개는 자체 원본 3장면×4초,
1080×1920/30fps/무음 preview 재제작안이다. 로고·기성 캐릭터·사진·음원은
도입하지 않는다. 새 자산 생성0·교체0이며 계획을 권리 증빙으로 표시하지 않는다.
후속 승인 후 별도 catalog-v2/새ID만 사용하고 v1·사용자 복사본/숨김 상태를
보존하는 조건을 명시했다.
[샘플 권리·재제작](SAMPLE_RIGHTS_AND_REMAKE.md) 참조.

## 7. 코드 서명

인증서는 외부 확보 대상으로 분리했다. 새 인증서 저장소/개인 키 조회·
시험 인증서 설치·unsigned update 예외는 없다. EXE→Setup→manifest 순서,
SHA256·신뢰 timestamp·배포자 pin·체인/EKU 검증 절차와 서명 대상을 정리했다.
기존 `publisher-trust.json`은 pin 없음/updatesEnabled:false로 유지한다.
[서명 대상·절차](PUBLISHER_SIGNING_TARGETS.md) 참조.

## 8. 검증 결과

최종 새 실행 집계/CI 링크는 CI_EVIDENCE.json에 기록한다.
로컬 Windows Python3.14.7 entry 집중 테스트는 **7 PASS /0 FAIL /0 SKIP**다.
기본 browser 동작, no-browser, 미지원 operation/unfrozen/tampered media 거부,
정상 console interrupt, 다른 runtime 오류가 은폐되지 않음을 검사했다.
syntax5파일/diff-whitespace 및 문서12행9이미지+3영상 정합성을 확인했다.
이 검사는 실제 Windows11 신규 설치/GUI 테스트가 아니다.

기존 사용자 보안28 PASS/네이티브6/실제 두 SID 격리/설치CI/GUI12화면/
샘플MP4/SAPI는 과거 증거로만 재사용했고 새 PASS에 합산하지 않았다.
전체 Python 회귀/Guard 감사/디자인/샘플 원본 무결성 검사는 반복하지 않았다.

## 9. 보호 상태 및 남은 배포 조건

프런트엔드 Git tree와 샘플 원본 tree는 기준3103560과 동일하다.
실행기/패키징 최소 수정 이외의 제작 엔진·API·DB schema·비밀값 저장 정책·
업데이트 verifier/publisher trust는 무변경이다. 원래 완료 브랜치·PR35 Draft·
main을 유지한다. 운영8765 listener/PID55740을 읽기 전용으로만 확인했다.
운영 DB/ledger/키/OAuth/설정/미디어/백업은 열람·복호화·쓰기하지 않았다.
따라서 운영 파일의 전후 hash 감사까지 수행했다고 주장하지 않는다.
운영 재시작·실제 유료 API·OAuth/SNS·공개 배포0이다.

공개 배포 전 남은 조건:

1. 현 FFmpeg의 정확한 대응 소스/patch/build closure·제공 체계 인수,
   또는 승인된 대체 빌드의 실제 호환성/소스 제공 인수.
2. 기존 샘플의 파일별 권리 증빙 또는 승인된 자체 원본의 실제 제작·검토·등록.
3. 별도 Windows11 신규 표준 사용자/깨끗한 환경의 설치·최초 실행·분리 검증.
4. 실제 배포자 인증서 확보/EXE·Setup·manifest 서명 및 서명된 apply 인수.
5. 기술 후보로 확인하지 않은 default-path 이동·schema 변경 후 rollback 및
   실제 public updater 경계의 적용/복구 인수.

**최종 BLOCKED는 공개 배포 판정이다.** 완료된 개발/기술 후보 검증과 외부
증빙·환경 미확보를 구분해 보고하며 추가 운영 전환/PR 변경 없이 종료한다.
