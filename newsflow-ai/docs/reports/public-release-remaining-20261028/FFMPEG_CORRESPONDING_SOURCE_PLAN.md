# FFmpeg 정확한 대응 소스 제공 준비

2026-10-28 · **전체 적합성 NOT VERIFIED / 공개 패키지 배포 BLOCKED**

## 실제 바이너리와 확보한 자료

기존 고정 바이너리를 읽기 전용 `-version`으로 확인했다. 버전은
`9.0.2-essentials_build-www.gyan.dev`, 컴파일러는
`gcc 16.2.0 (Rev3, Built by MSYS2 project)`다. `--enable-gpl`,
`--enable-version3`, `--enable-static`, `--disable-w32threads`,
`--disable-autodetect`, `--enable-libx264`, `--enable-libx265`를 확인했다.
다른 빌드/엔진으로 변경하지 않았다.

기존 `SOURCE_ACQUISITION_INDEX.json`의 공식 업스트림 archive3개,
전체 commit/SHA-256/파일 크기와 확인한 license/source member 기록을 재사용한다.
새 다운로드·동일 해시 전수 검사를 반복하지 않았다. Gyan support 저장소의
자동 Source ZIP을 FFmpeg 소스로 간주하지 않는다.

| 소스 | 고정 commit | 소스 archive SHA-256 |
|---|---|---|
| FFmpeg | 946fcce07b6dcd0331c8cc609192aeff5e1924f8 | 0aa2b1de2a5698b20a23e93d539a9a8e82ca0117496c5bdf05d198805f42bb3b |
| x264 | 0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee | 2ee0208201a22e4637462c566b0fc853da85dbda77533b8b7389a7f38fb1da04 |
| x265 | 116b87573ed0cec20b75ccacd5641bf06f6e57bd | 2d53caffd91f6a1409f56ca2268e86484c405feb482cedf02f56dd57d2929bef |

이들은 upstream source와 버전 대응 근거다. 해당 Gyan binary의 모든
private patch·build recipe와 일치한다는 증거는 아니다.

`FFMPEG_CLOSURE_MATRIX.json`/`FFMPEG_COMPONENTS.md`는 기존 build README의
일반 외부 라이브러리 및 hardware interface55개를 정리한다. 기존37개
버전 목록과 alias를 대응했으며 미기록 버전은 UNRECORDED로 유지한다.
정적 링크의 간접 의존성(예: font shaping/TLS/compression runtime)은
archive/link map·pkg-config static closure가 없으므로 목록 완성을 주장하지 않는다.
Windows 시스템 interface와 SDK headers를 전부 정적 링크 라이브러리로
단정하지 않고 System Library 예외와 헤더 license를 각각 검토해야 한다.

## 필요한 정확한 빌드 자료

1. 배포 binary와 연결되는 각 source revision/원본 archive 및 SHA-256,
   적용 patch 전체 또는 명시적 no-patch 기록.
2. FFmpeg 및 각 외부/간접 dependency configure/CMake/Meson 옵션,
   빌드 순서·환경·정적 link flags·최종 link map.
3. GCC16.2.0 Rev3의 정확한 MSYS2 package revision/hash,
   mingw-w64/UCRT/runtime/libgcc/libstdc++/winpthreads·binutils·NASM·SDK 버전,
   재현에 필요한 script/environment. 모든 SDK 소스 제공 의무를
   일률적으로 단정하지 않고 적용 license/예외를 확인한다.
4. 해당 소스와 패치에서 빌드한 산출물이 배포 binary와 대응한다는
   확인 기록. bit-for-bit 동일성 여부와 기능/설정 재현 여부는 구분한다.

현재 공식 공개 자료에서 이 **정확한 Gyan 빌드의 완전한 recipe/patch closure**를
확보하지 못했다. 연락/권리 계약/메일 전송은 이번에 수행하지 않았다.
고지 파일만 추가하거나 FFmpeg 본체 소스 URL만 연결해서 완료 처리하지 않는다.

## 대응 소스 제공 체계 — 준비안, 아직 공개하지 않음

배포 binary digest별 immutable 경로로 다음을 함께 보관한다.

```text
source/<ffmpeg-binary-sha256>/
  MANIFEST.json       # binary/source/patch hashes, versions, license, source URL
  NOTICE.txt         # contributors, modified status, source location
  licenses/          # GPLv3 and dependency notices/licenses
  upstream/          # exact source archives incl. required transitive components
  patches/           # complete ordered patch series or explicit none records
  build/             # toolchain/package pins, recipe, config, reproducibility notes
  verification/      # source/build-to-binary correspondence results
```

배포 시 GPLv3 §6의 실제 선택한 제공 방식에 맞춰 binary 수령자가 동일한
배포 위치에서 필요한 대응 소스를 추가 비용 없이 확보할 수 있도록 구성한다.
단순 임의 외부 URL·불완전한 support ZIP·유효기간 불명 다운로드를 소스 제공
완료로 표시하지 않는다. 소스 접근과 해시·license 파일을 실제 다운로드로
인수한 뒤 공개 조건을 해제한다. 이번에는 공개 릴리스/다운로드 서버를 만들지 않았다.

기존72개 Python/JS/font/FFmpeg 고지 및 license inventory는 그대로 보존한다.
FFmpeg 실행파일을 별도 프로세스로 포함한다는 사실만으로 Python 앱의 모든
코드가 GPL이라고 단정하지 않으며 결합/배포 방식과 각 license를 따로 검토한다.

## 대체 빌드 비교 — 교체하지 않음

| 선택 | 기술/소스 장점 | 남은 조건 |
|---|---|---|
| 현 Gyan9.0.2 GPL static 유지 | 기존 FFmpeg4 PASS/제작 엔진 증거 재사용 | 위 exact dependency/patch/toolchain closure 확보 필요 |
| BtbN 고정 release GPL build | 공개 scripts.d·patches·Docker recipe·dependency commit pins. x264 포함 가능 | 정확한 binary/release+build-repo commit+image digest+모든 source/patch를 고정·확보한 후 호환성/대응 소스 검증 필요. 현 Gyan 소스 증빙의 대체가 아님 |
| BtbN LGPL variant | GPL-only x264/x265 제외 | 현재 libx264 사용 엔진의 drop-in 대체가 아님. encoder 변경/품질/비용/회귀 별도 작업 필요 |
| 자체 최소 GPL build | 필요한 의존성만 포함하고 recipe/source를 직접 보유 가능 | 새 빌드·재현·재배포 의무와 호환성 인수 필요. 이번에 엔진 변경/빌드하지 않음 |

공식 근거:
[Gyan build/source/설정](https://www.gyan.dev/ffmpeg/builds/),
[BtbN build 방법·GPL/LGPL 구분](https://github.com/BtbN/FFmpeg-Builds),
[BtbN x264 고정 source/옵션](https://github.com/BtbN/FFmpeg-Builds/blob/master/scripts.d/50-x264.sh),
[BtbN x265 source·patch·빌드 옵션](https://github.com/BtbN/FFmpeg-Builds/blob/master/scripts.d/50-x265.sh).
BtbN master는 이동하므로 실제 채택 시 commit을 고정해야 한다.
GPLv3 원문은 기존 bundled COPYING.GPLv3를 재사용한다.

대체 recipe 참고 snapshot은 b4a2b1d7cc241786eb8e2b588a7ade40cad48bbd로
고정했고 README/x264/x265 script/MIT LICENSE4개를 보존했다.
ALTERNATIVE_RECIPE_REFERENCE.json의 URL/hash/크기를 참조한다.
script는 실행하지 않았으며 전체 dependency closure나 실제 대체 binary
빌드·license 적합성을 완료한 것으로 처리하지 않는다.
