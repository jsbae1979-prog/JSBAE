# FFmpeg·포함 구성요소 배포 라이선스 검토

2026-10-28. **판정: CONDITIONAL / 공개 배포 권리 해소는 BLOCKED**.
고지 파일 수집과 최종 재배포 적합성은 서로 다르다.

## 이번에 확보한 자료

- 이전 실제 payload의 Python 모듈에 대응하는 설치 배포판 30개를 조사했다.
  각 배포판에서 저작권·LICENSE/COPYING/NOTICE 문서 **64개**를 수집했다.
- 브라우저 런타임 React 19.3.1, ReactDOM 19.3.1, scheduler 0.28.0의 MIT,
  Lucide 1.61.0의 ISC LICENSE를 원문으로 보존했다.
- 기존 Noto 계열 폰트의 SIL OFL 고지와 FFmpeg n9.0.2의 `COPYING.GPLv3` 원문을
  포함했다. 기존 Python runtime LICENSE도 기존 spec에서 계속 포함한다.
- 경로: `src/newsflow/assets/distribution/licenses/`. 새 onedir 빌드의
  `_internal/newsflow/assets/distribution/licenses/` 안에 실제 포함했다.
- `THIRD_PARTY_INVENTORY.json`은 패키지 버전·메타데이터·수집 문서 목록이다.
  완전한 SBOM/대응 소스/상용 권리 보증으로 표시하지 않는다.
- Node/Vite/TypeScript는 빌드 도구이며 Node 런타임을 사용자 payload로 복사하지
  않는다. 브라우저에 포함되는 코드의 라이선스는 별도로 포함했다.

## FFmpeg 실제 구성과 의무

현재 해시 고정 바이너리: `9.0.2-essentials_build-www.gyan.dev`.
`--enable-gpl --enable-version3 --enable-static`, libx264/libx265가 포함된다.
이를 LGPL 전용 바이너리로 배포하면 안 된다.
Gyan 공식 페이지는 현재 9.0.2 release와 upstream commit `946fcce07b`를
연결한다. 이는 upstream 식별 단서이며 각 외부 라이브러리의 정확한 빌드
소스/패치까지 확보했다는 증거는 아니다.

이번에 공식 release ZIP의 README/LICENSE도 추출했다. ZIP SHA-256은
`60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`이며
CI의 해시 고정된 실제 도구를 추출한 archive와 일치한다. README는 GPLv3,
static/shared 설정·각종 구성과 x264 `v0.165.3223`, x265 `4.3-45-g116b875`를
명시한다. 원문은 `FFMPEG_BUILD_README.txt`에 보존했다. 이 자료를
확보했어도 외부 라이브러리 전체 소스/패치/재현 recipe 확보와는 별개다.

일반 사용자에게 전달하기 전 필요한 자료:

1. 실제 배포 FFmpeg/FFprobe 각각의 해시와 build configuration.
2. 선택한 GPL 버전에 맞는 저작권·라이선스·수정 고지.
3. 정확한 FFmpeg 및 정적 링크 외부 라이브러리의 대응 소스·버전·패치·빌드
   스크립트/설정, 그리고 GPL이 요구하는 방식의 소스 전달/제공 체계.
4. 실제 제공 능력·유효기간을 갖추지 않은 형식적인 소스 제공 약속 금지.
5. x264/x265 등의 별도 상용 라이선스 또는 코덱·특허 조건이 필요한지 검토.

이번에는 GPLv3 텍스트를 확보했다. **GPL 텍스트 한 장과 upstream 링크만으로
전체 대응 소스 의무가 충족됐다고 판정하지 않는다.** 대응 소스 묶음과 배포
체계는 미확보다. 파일을 subprocess로 호출하는 현재 구조만으로 NewsFlow의
전체 앱 라이선스를 자동으로 GPL/비GPL이라고 단정하지 않는다.

## 대체 구성안 — 아직 적용하지 않음

- **안 A:** 현재 검증된 GPL 빌드를 유지하고 정확한 대응 소스·빌드 자료와 고지,
  소스 제공 체계를 확보한다. 기존 libx264 렌더 계약을 보존할 수 있다.
- **안 B:** GPL 옵션/라이브러리를 제외한 재현 가능한 LGPL 빌드를 선정하고
  Windows Media Foundation 등 허용 인코더로 변경을 검토한다. 현재 엔진의
  libx264 선택·품질·9:16 MP4·호환성 검증이 추가로 필요하므로 드롭인 대체라고
  표시하지 않는다. 기존 렌더 엔진을 이번 작업에서 임의 변경하지 않았다.

## Python·PyInstaller·폰트·아이콘

PyInstaller 6.22.3의 예외는 상용 번들을 허용하지만 포함 의존성의 의무를
면제하지 않는다. Python 고지 및 런타임 패키지 고지를 모았다. LGPL 등
메타데이터만으로 판단하기 어려운 의존성/정적 구성은 실제 파일 기준으로
최종 검토해야 한다. SIL OFL의 고지·이름 제한을 보존하며 폰트를 판매용
단독 자산으로 취급하지 않는다. Lucide ISC의 저작권·허용 문구도 유지한다.

## 음성·그 밖의 자산

- Windows SAPI는 OS 설치 음성을 사용한다. Microsoft 음성 파일을 복사해
  설치 패키지에 재배포하지 않았다. 현재 PC 음성 사용 가능성과 타 PC에
  한국어 음성이 설치돼 있다는 보장은 별개다.
- Supertonic/ONNX 선택 모듈과 실제 가중치는 이번 payload에 없다. 모델
  라이선스·전체 파일·해시·오프라인 설치 계약을 확보하기 전 포함 완료로
  표시하지 않는다. 자동 다운로드/유료 호출은 하지 않았다.
- 기존 studio-concepts provenance에는 사용자 ZIP/ChatGPT 컨셉 아트 및
  WebP 변환 이력이 있으나, 생성 계정·입력 권리·재배포 허락의 원본 증거와는
  다르다. 승인 디자인 자체가 상용 권리 확인을 대신하지 않는다.
- 샘플 12개는 별도 `SAMPLE_RIGHTS_REVIEW.md` 참조. 원본을 교체하지 않았다.

## 공식 근거

- [FFmpeg 라이선스 안내](https://ffmpeg.org/legal.html)
- [Gyan build·source 식별](https://www.gyan.dev/ffmpeg/builds/)
- [FFmpeg n9.0.2 GPLv3 원문](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/COPYING.GPLv3)
- [x265 라이선스](https://x265.readthedocs.io/en/master/introduction.html#licensing)
- [PyInstaller 라이선스](https://pyinstaller.org/en/stable/license.html)

배포 고지 준비는 진전됐으나 샘플 권리와 정확한 GPL 대응 자료가 없으므로
일반 사용자 설치 패키지 공개는 계속 차단한다.

## 수집 문서의 해시와 패키지 파일 해시

THIRD_PARTY_INVENTORY의 notice SHA-256은 수집 당시 설치 배포판의 고지 원문을 식별한다. Git checkout의 텍스트 줄바꿈 정규화 등으로 실제 패키지 파일 해시는 달라질 수 있다. 실제 배포 파일의 무결성 기준은 각 빌드의 payload-manifest이며 원문 식별 해시와 혼동하지 않는다. 샘플 PNG/MP4의 기존 바이너리 해시는 이 텍스트 처리와 별개이고 원본을 변경하지 않았다.
