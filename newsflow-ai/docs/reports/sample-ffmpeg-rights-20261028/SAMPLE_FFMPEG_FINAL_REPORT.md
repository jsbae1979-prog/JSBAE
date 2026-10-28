# 샘플 권리 및 FFmpeg 배포 차단 해결 결과

2026-10-28 · **최종 판정: BLOCKED — 현재 제품의 일반 사용자 공개 배포 기준**

신규 샘플12개를 실제 제작했고, exact source에서 빌드한 별도 FFmpeg 후보가
변경하지 않은 제품 제작 엔진과 호환됨을 확인했다. 다만 현재 제품의
원래 샘플/Gyan binary는 그대로이고, 권리 최종 증빙과 새 후보의 배포 통합이
남는다. MP4의 GitHub 등록은 자동 승인 심사에서 거절되어 로컬에 보존했다.
준비/기술 검증 성공을 실제 공개 배포 조건 완료로 확대하지 않는다.

## 1. 기준과 브랜치

- 시작 baseline: f44f65de1c4dcb74a6037ce5063cd44455a8e373.
- 작업 브랜치: codex/newsflow-sample-ffmpeg-rights-20261028.
- FFmpeg 검증 code: 88bdfbbd1cf4327f80fd6d155f96b87819211e39.
- 신규 자산/생성 기록 checkpoint: d846351. 최종 보고 HEAD는 Git 로그 참조.
- 별도 브랜치를 사용했고 기존 untracked validation/과 완료 브랜치를 보존했다.
- 변경 범위는 tools의 별도 빌드/자산 제작 도구, 후보 자산 및 보고서뿐이다.
  제품 src/frontend/기존 build/installer/운영 실행 경로는 수정하지 않았다.

## 2. 기존 샘플12개 권리

이전 file-level audit/해시/생성·가공 기록을 재사용했다. 원래 ChatGPT 생성
대화·원본 콜라주·입력 권리·상용 설치 재배포 허락의 추가 증빙은 없었다.
이미지9개와 무음 MP4 3개 모두 rightsVerified:false를 유지한다.

각 원본 ID/경로/SHA/구체적 위험과 새 대응 ID는
../../artifacts/sample-replacement-candidates-v2-20261028/FILE_RIGHTS_MATRIX.md에
12행으로 정리했다. 기존 샘플 재해시/디코딩/전체 감사는 반복하지 않았다.
원래 파일·매니페스트·사용자 복사본·실제 생성 이력은 변경하지 않았다.

## 3. 신규 자산 실제 제작

| 종류 | 실제 제작 | 규격/내용 |
|---|---:|---|
| 캐릭터 참조 | 3PNG | 로봇/고양이/드래곤,720×1080 RGBA |
| 독립 이미지 | 3PNG | 가상 도시/고양이/환경 개념,720×1080 |
| TOP3 이미지 | 3PNG | AI/전기 이동/경제 개념,1080×1350 |
| 뉴스 미리보기 | 1MP4 | 새 TOP3 이미지3개×4초,1080×1920/30fps/12초/무음 |
| 캐릭터 미리보기 | 2MP4 | 새 로봇/고양이 참조 이미지의 정지영상 preview, 같은 영상 규격 |

내장 imagegen 스킬/도구로 실제10회 생성했다. 입력은 새 텍스트 prompt뿐이며
원래 샘플·사진·기성 캐릭터·음원·실제 뉴스/운영 데이터는 입력하지 않았다.
전기차 초기 결과의 식별 불명 표식/제품 외관 위험을 제외하고 차량 없는
추상 배터리/충전 도형으로 다시 생성했다. 최종 이미지9개와 rejected1개를 구분한다.
운영 키/외부 유료 REST·SDK0, 실제 product Provider 연동 성공으로 표시하지 않는다.
도구가 공개하지 않은 model ID는 추측하지 않았다.

raw PNG9개·exact prompt·출력 hash·규격화 과정·MP4 input hashes·렌더 명령을
보존했다. 원본 raw는 수정하지 않고 FFmpeg scale/crop/PNG export로 규격화했다.
영상은 외부 음원/음성 없이 로컬 FFmpeg로 제작했고 실제 AI 장면 움직임이나
편집 가능한 원본 프로젝트가 아니다. 모든 영상에 샘플/무음 안내를 넣고
프레임으로 확인했다. SIL OFL 고지와 사용한 기존 Noto Sans KR 파일을 보존했다.

## 4. 신규 권리 근거와 교체 준비

현재 세션의 생성·입력·가공 이력과 공식 OpenAI 출력물 약관을 연결했다.
약관상 OpenAI-사용자/고객 간 Output 소유권 근거와 제3자 권리·비유일성은
구분한다. 실제 배포 주체에 적용되는 계약/사용 권한 확인 기록은 제공되지
않았으므로 신규 후보도 rightsVerified:false/CONDITIONAL을 유지한다.
일반 약관만으로 배타적 저작권·상표 clearance를 완료했다고 선언하지 않는다.

후보는 모두 고유 -v2 ID, contentRevision2, 별도 immutable hash를 갖는다.
기존 loader의 schema1을 따르는 호환 manifest를 작성하고, 변경하지 않은
Samples.catalog가 로컬 후보12개를 읽는 것을 확인했다. 원본 provenance는
PROVENANCE_MANIFEST.json에 분리했다. 제품 catalog를 새것으로 전환하지 않았다.
따라서 기존 숨김/복사/프로젝트 참조를 덮지 않는다. 실제 새 그림이 없는데
제작 완료로 표시한 항목은 없다.

상세: 후보 폴더의 RIGHTS_BASIS.md/GENERATION_RECORDS.json/PROCESSING_COMMANDS.json.

## 5. 신규 자산 검증 및 원격 등록 제한

Windows Python3.14.7의 새 자산 집중 검사 **28 PASS /0 FAIL**:
이미지9개 decode/규격,raw9개 생성 원본 동일성,MP43개 format/duration/audio/full
decode9개,기존 loader12개 로딩1개다. 영상은12초/H.264/yuv420p/30fps/무음이며
실제 browser playback은 이번 신규 실행에서 NOT VERIFIED다.

이미지9개(raw9+규격화9),poster3개와 생성/권리/해시 기록은 GitHub에 보존했다.
MP43개는 자동 승인 심사가 Git stage를 바이너리 업로드 제한으로 거절했다.
처음 거절 뒤 경로·해시·합성 무음 media 형식을 확인하고 사용자 승인 범위/
EXE와의 차이를 설명해 재검토했으나 같은 거절이 유지됐다.
다른 API·압축/파일명 변경·인코딩/간접 실행으로 업로드를 우회하지 않았다.

MP4는 로컬 두 위치에 보존하고 GitHub에는 해시/크기/preview/검증 결과만
남겼다. MEDIA_UPLOAD_STATUS.json 참조. 따라서 원격 repository에12개 media가
모두 등록됐다고 주장하지 않는다. 로컬12개 loader PASS와 원격 보존 범위를
분리한다. MP43개만의 명시적인 GitHub 등록 승인 또는 승인된 artifact 저장소가
필요하다. 제품 EXE/DLL/Setup 공개 배포 승인은 요청하지 않는다.

## 6. FFmpeg A/B 비교와 실제 검증

현재 제품은 기존 Gyan9.0.2/GCC16.2.0 Rev3/GPLv3 static을 유지한다.
기존 source3개와55개 구성요소 목록을 재사용했으며 vendor의 완전한 정적
dependency/patch/toolchain recipe가 새로 확보된 것은 아니다. A는 미완료다.

B는 FFmpeg/x264/libass/FreeType/FriBidi/HarfBuzz/zlib의 고정 source7개에서
별도 Windows 후보를 빌드했다. GNU GPL 구성이고 LGPL 명칭만으로 준수를
판정하지 않았다.13개 source license,FTL 고지,GCC runtime exception 및
MinGW/CRT/winpthreads 고지,compiler/package/config/import 증거를 확보했다.
source byte patch0,Windows source directory flattening과 build/install 명령만
기록했다. 기존 VideoAdapter/character.compose/음성·저장·승인 정책은 무변경이다.

[CI40658108667](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40658108667)
**SUCCESS /22 PASS /0 FAIL**. Windows Server native UCRT64/GCC16.2.0 Rev4,
Python3.14.7. 소스 archive7개와 각각의 SHA를 실제 빌드에 사용했다.
libx264/AAC/PNG,ASS/xfade/overlay 및 필요한 필터,제품 preflight,
실제 뉴스30초/캐릭터30초 합성·full decode,합성 AI clip overlay가 PASS다.
실제 공급사 API·실계정 입력/모든 가능한 codec까지 검증한 것은 아니다.
외부 runtime DLL 없이 Windows/UCRT system imports만 확인했다.

첫 run40657031044는 HarfBuzz 명령줄 길이 때문에 실패했고 source 경로만
짧게 하여 해결했다. skip/xfail·Guard 변경 없이 이 이력을 유지한다.

source artifact62.4MB/증거 artifact를 실제 다운로드해 ZIP digest를 확인했고,
source ZIP의 예상7개 archive SHA도 각각 고정 manifest와 일치했다.
현재 artifact는2027-01-26 만료 예정이므로 영구 공개 source 제공처가 아니다.
소스·recipe·license·runtime notices·binary hashes를 함께 제공하는 구조를
준비했으며 실제 배포 때 binary와 연결된 영구 제공/동봉이 필요하다.

**B는 후속 배포 후보로 선택할 기술 근거를 확보했다.** 그러나 제품 media pin/
설치 payload는 교체하지 않았다. 새 FFmpeg를 포함한 패키지 통합과 source
제공 체계의 최종 인수는 남는다. FFMPEG_ALTERNATIVE_REPORT.md 및 ci-evidence 참조.

## 7. 검증 집계 및 보호

| 항목 | 신규 결과 | 범위 |
|---|---|---|
| 신규 샘플 |28 PASS/0 FAIL | Windows11 로컬 파일·원본/규격/decode/호환 catalog |
| FFmpeg 후보 |22 PASS/0 FAIL | Windows Server native source build/product command compatibility |
| MP4 원격 등록 |BLOCKED | 자동 승인 심사2회 거절,로컬 보존/해시 공개 |
| 최종 상용 sample rights |NOT VERIFIED | 기존·신규 rightsVerified:false 유지 |
| 현재 Gyan full source closure |NOT VERIFIED | 기존 source3/구성55 증거 재사용 |
| 새 후보 포함 EXE/installer·영구 source 제공 |NOT VERIFIED | 아직 제품에 교체하지 않음 |

업데이트/복구42 PASS,패키징7 PASS,사용자 보안28 PASS,실제 Windows 계정2개,
Windows11 GUI12화면/기존 MP4 3개 재생은 과거 증거로 재사용하고 새 결과에
합산하지 않았다. 전체 Python 회귀/Guard 감사/디자인 감사를 반복하지 않았다.

제품 src/frontend/기존 assets/samples·API/DB schema·video engine·기존 packaging
도구와 operating entry는 무변경이다. 운영8765 상태를 읽기 전용으로 확인했고 DB/키/OAuth/설정/미디어/백업은 열거나 복호화/수정하지 않았다.
운영 파일의 전후 cryptographic hash 감사까지 수행한 것은 아니다.
PR35 Draft·main·완료 브랜치 보존,reset/clean/stash/force push 없음,
운영 재시작/유료 REST·SDK/OAuth/SNS/공개 배포0이다.

## 8. 남은 조건 및 판정

1. 원래 sample 권리 증빙을 확보하거나,신규 생성 output의 배포 주체 적용
   계약/사용 권한을 확인하여 권리 확인된 새 catalog만 선택한다.
2. 새 source-built FFmpeg를 패키지에 통합하고 license/runtime notices 및
   정확한 source/recipe를 binary와 함께 영구 제공/동봉하는 절차를 인수한다.
   기존 Gyan을 유지하려면 별도로 exact vendor source closure가 필요하다.
3. MP43개 원격 보존은 자동 승인 심사에서 차단됐으므로 해당 media만의
   명시적 승인 또는 승인된 저장소가 필요하다.

실제 publisher certificate/서명,Windows11 신규 사용자 설치 등의 이전 외부
배포 조건은 이 두 영역 작업으로 해소됐다고 표시하지 않는다.

**공개 배포 가능 여부: NO /최종 BLOCKED.** 이번에는 실제 새 원본/영상과
빌드 과정을 추적할 수 있는 source-built 후보를 확보했다. 완료한 기술 작업과 미확인 권리/
패키지 제공·플랫폼 승인 조건을 구분해 보고하고,운영 전환·병합 없이 종료한다.

## 최종 운영 상태 관찰

작업 중간 조회에서는8765/PID55740이 보였으나, 최종 Get-NetTCPConnection
조회는 정상 수행되면서 해당 listener가 없었고 이전 PID도 없었다.
이번 작업의 운영 종료/재시작 명령은0이며, 미실행 원인은 확인되지 않았다.
실행 상태까지 무변경이라고 주장하지 않는다. 운영 데이터/키를 열거나 앱을
임의 재시작하지 않았고, 이번 샘플/FFmpeg 수정과의 관련성도 확정하지 않았다.
FINAL_EVIDENCE_INDEX.json 참조. 운영 진단/재시작은 이번 범위 밖으로 유지한다.