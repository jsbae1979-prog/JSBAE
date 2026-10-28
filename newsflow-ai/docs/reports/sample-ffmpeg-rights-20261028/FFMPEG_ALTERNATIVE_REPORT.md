# FFmpeg GPL 대응 및 별도 소스 빌드 후보 검증

2026-10-28 · **대체 후보 기능 PASS / 제품 교체·공개 배포 미실행**

## A. 현재 Gyan GPL static 유지안

기존 f44f65d의 실제 binary 확인, source archive3개 및 구성요소55개 목록을
재사용한다. 현재 제품의 ffmpeg.exe SHA256은
`3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec`,
ffprobe.exe는
`f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52`다.
버전9.0.2-essentials/GCC16.2.0 Rev3/GPLv3 static, x264/x265 포함 증거를 유지한다.

FFmpeg/x264/x265 upstream archive를 확보했다는 사실만으로 이 Gyan binary의
전체 정적 의존성·private patch·toolchain recipe 대응이 완료되지는 않는다.
새 vendor build 자료는 제공되지 않았으며55개 전체를 다시 다운로드하거나
감사하지 않았다. **A의 exact corresponding-source closure는 여전히 미확인**이다.
기존72개 고지와 source 제공 준비 문서를 유지한다.

## B. 직접 빌드한 제한 구성 GPL static 후보

불명확한 vendor patch 집합 대신 exact source7개에서 새 Windows 후보를 빌드했다.
이는 LGPL이라는 명칭만 바꾼 빌드가 아니며 x264 때문에 GPL 구성이다.
제품의 명령/코덱/필터/저장/승인 엔진은 수정하지 않았다.

| 소스 | 고정 commit | 선택 license/역할 |
|---|---|---|
| FFmpeg | 946fcce07b6dcd0331c8cc609192aeff5e1924f8 | GPLv3 configured / 본체·기본 codec/filter |
| x264 | 0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee | GPL2-or-later / H.264 encoder |
| libass | 4a05d8127f525943ebf45fdc6497c9e665947f0d | ISC / ASS 자막 |
| FreeType | 0a0221a1347e2f1e07c395263540026e9a0aa7c7 | FTL 선택 / 글꼴 rasterization |
| FriBidi | 68162babff4f39c4e2dc164a5e825af93bda9983 | LGPL2.1-or-later / text direction |
| HarfBuzz | 36cb489cb02ce4b92099669ba9f9bea348eff93f | MIT 및 file-level notices / shaping |
| zlib | 51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf | Zlib / PNG decode/encode 지원 |

archive URL/SHA는 tools/ffmpeg_source_candidate/sources.json,
실제로 받은 bytes/소스 위치는 ci-evidence/SOURCE_INPUTS.json 참조.
다운로드는 digest 불일치 시 중단하고 wrap-mode:nodownload,
FFmpeg disable-autodetect를 사용했다. 테스트 자료는 전부 합성이다.
upstream source byte patch0이며 Windows 명령줄 제한을 피하는 source directory
flattening만 수행했다. zlib static archive의 설치 별칭은 build script에 기록한다.

기본 source archive7개와13개 핵심 license 파일을 확보했다. 실제 GCC16.2.0
Rev4/MSYS2 UCRT64의 package 목록·compiler configure 및 runtime notice도 보존한다.
GCC runtime exception과 MinGW/winpthreads 고지는 원문대로 제공한다.
빌드 도구에 설치된 curl/OpenSSL 등까지 FFmpeg에 정적 포함됐다고 주장하지 않는다.
검증한 실행파일의 DLL import는 Windows/UCRT 시스템 DLL뿐이고,
libgcc/libstdc++/winpthread/libass/zlib 등의 외부 runtime DLL 의존은 없었다.

## 실제 빌드 및 기능 검증

[Windows CI40658108667](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40658108667)
**SUCCESS /22 PASS /0 FAIL**, 검증 code88bdfbbd1cf4327f80fd6d155f96b87819211e39.
Windows Server native UCRT64/GCC build이며 Docker/WSL/Linux 배포가 아니다.
Python3.14.7에서 변경하지 않은 실제 product command builders/composer를 호출했다.

- libx264/AAC/PNG encoders, ASS/xfade/scale/crop/overlay/apad/amix/tpad/zoompan/drawbox.
- product FFmpeg preflight.
- 실제 뉴스 RenderPlan3장면30초,1080×1920 H.264/AAC/yuv420p와 full decode.
- 실제 character.compose의3장면30초/xfade/한글 ASS/font/final MP4와 full decode.
- 실제 AI clip overlay command path. 입력 clip은 합성 로컬 미디어이며
  Higgsfield API·실계정 compatibility를 검증한 것은 아니다.
- 정적 구성/외부 network protocol 비활성 및 외부 runtime DLL 없음.

후보 ffmpeg.exe SHA256:
`081ad1c10cdf530d9ce47f03934dbd1a4343dce1d617af3f1030a9eb098b1569`.
후보 ffprobe.exe SHA256:
`cc7955c6bd13d9ab82fba80cf513e85b301fdb18f9d04f3172ec86bd14363e1f`.

범위 밖: 실제 공급사 입력의 모든 codec/format, 실제 Windows11 fresh install,
동일 source의 byte-for-byte rebuild, 새 후보를 포함한 EXE/installer 통합,
실제 publisher signing/업데이트. 이번에 이를 PASS로 확대하지 않는다.

최초 CI40657031044는 HarfBuzz generated-source 명령줄 길이로 실패했다.
허용 경로나 Guard를 바꾸지 않고 source directory만 짧게 하여 해결했다.
실패 이력은 보존하며 skip/xfail·정책 완화·제품 코드 수정은 없다.

## 대응 소스 제공 자료와 남은 배포 조건

실제 archive7개를 묶은 source artifact12802589292와 evidence artifact12803497630을
다운로드해 원격 ZIP SHA와 일치함을 확인했다. source ZIP의 예상7개 archive를
각각 sources.json SHA와 대조했다. 실행파일/installer·사용자 DB/키를 올리지 않았다.
source archive ZIP은 약62.4MB이며 Source ZIP은 제품 실행 바이너리가 아니다.

- source artifact SHA256:
  `5c9f86612852d547c21672c7ea06541d4e686cb835364993e1e13a4a38662d45`.
- evidence artifact SHA256:
  `5b071b1beb505efdc65aa4a79cd4b0b133b07c67874ae20480937f9048ef9877`.

CI artifact는2027-01-26 만료 예정이므로 공개 배포 때의 영구 소스 제공처로
간주하지 않는다. 실제 배포 binary hash에 연결된 source/recipe/license/runtime
고지를 같은 배포 위치에서 함께 제공하도록 다음 구성을 준비한다.

```text
ffmpeg-<binary-sha>/
  binary-index.json       # executable hash/version/config/license
  sources.json            # seven exact archives and URLs/hashes
  sources/*.tar.gz        # corresponding inputs, unchanged upstream notices
  build_candidate.sh     # complete commands/flags, no undisclosed patch
  prepare_candidate.py   # digest verification/extraction
  licenses/              # upstream licenses + FTL acknowledgement
  runtime-licenses/      # GCC exception, MinGW/CRT/winpthreads notices
  evidence/              # compiler/packages/config/imports/functional results
```

FreeType 고지: Portions of this software are copyright © The FreeType Project
(www.freetype.org). All rights reserved. FTL/GPL 대안 중 이 후보는 FTL을 사용한다.
전체 source/재빌드·재링크 설명을 보존하며 원래 소프트웨어의 GPL/LGPL 권리를
자체 EULA로 제한하지 않는다. GPL FFmpeg를 별도 실행파일로 포함한다는 사실만으로
독립 Python 앱 전체의 license가 자동 변경됐다고 단정하지 않는다.

**권장: B를 후속 패키지 후보로 선택할 기술 근거는 확보했다.** 그러나 현재
제품 binary pin과 설치본은 그대로다. 배포용 package에 이 후보/고지/대응 source를
함께 통합하고 영구 제공 위치·설치 compatibility를 인수하기 전까지
기존 Gyan을 새 후보로 교체했다고 표시하지 않는다. 공개 제품 배포도 수행하지 않는다.
