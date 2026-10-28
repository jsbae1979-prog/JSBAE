# FFmpeg 실제 빌드에 연결되는 소스 확보 결과

**업스트림 소스3개 확보 PASS / 전체 정적 빌드의 대응 소스 적합성 BLOCKED.**

실제 사용 빌드9.0.2 GPLv3/static/libx264/libx265 및 기존 바이너리 해시는 이전 검증 증거를 재사용했다. [공식 Gyan release](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2), [build 페이지](https://www.gyan.dev/ffmpeg/builds/), 기존 실제 README를 확인했다.

| 구성요소 | 실제 확보한 upstream commit | archive bytes | archive SHA-256 |
|---|---|---:|---|
| ffmpeg | `946fcce07b6dcd0331c8cc609192aeff5e1924f8` | 17,333,895 | `0aa2b1de2a5698b20a23e93d539a9a8e82ca0117496c5bdf05d198805f42bb3b` |
| x265 | `116b87573ed0cec20b75ccacd5641bf06f6e57bd` | 2,077,215 | `2d53caffd91f6a1409f56ca2268e86484c405feb482cedf02f56dd57d2929bef` |
| x264 | `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee` | 1,048,654 | `2ee0208201a22e4637462c566b0fc853da85dbda77533b8b7389a7f38fb1da04` |

FFmpeg 소스는 Gyan이 명시한946fcce07b를 공식 FFmpeg 저장소에서 전체 SHA로 해석한 것이다. x265는 README의g116b875를 개발사 Multicoreware 저장소의 전체 SHA로 확인했다. x264는 공식 VideoLAN 저장소를 bare clone하여 X264_BUILD165와 전체 revision count3223, version.sh의 산출 규칙을 확인했다. README의0.165.3223과 맞는 업스트림 후보이며 Gyan의 사적 패치까지 일치한다고 단정하지 않는다.

archive는 새 로컬 증거 폴더에 보존한다. tar 경로 목록/라이선스·configure·CMake 존재만 확인했고 소스 스크립트 실행/빌드/후크 실행은 하지 않았다. x264는 고정 commit을 git archive했으며 프로젝트 원본 Git에는 gc/prune/강제 변경을 하지 않았다. source index에는 원본 URL·commit·hash·크기와 나머지 외부 라이브러리 상태를 기록했다. 소스 묶음은 아직 공개하지 않았다.

## 미완료 범위

- 실제 README의 다른 정적 외부 라이브러리 전체의 정확한 소스·패치·license 및 recipe.
- MSYS2/UCRT64/컴파일러·링커·옵션·생성 파일·패치의 해당 binary 버전 연결.
- upstream과 배포 binary가 정확히 대응한다는 검토 및 실제 소스 제공 체계.
- Gyan 지원 저장소는 루트README/.github와 binary release를 제공한다. 지원 저장소의 자동 Source code ZIP을 FFmpeg 전체 소스로 잘못 등록하지 않았다.

## 제공 방식 준비

공개 배포 전 `sources/upstream`, `sources/dependencies`, `sources/patches`, `build-recipes`, `licenses`, `SOURCE_INDEX.json`을 정확한 binary hash에 연결한다. GPL에 부합하는 동봉/네트워크 제공 등의 방식을 선택하고, 실제 이행 준비 없이 소스 제공 약속을 공개하지 않는다. 기존 Python/React/폰트/아이콘 고지 수집 결과는 [기존 검토](../distribution-gates-20261028/LICENSE_REVIEW.md)를 재사용한다. 이번에 라이선스 문구나 원본 파일을 바꾸지 않았다.

## LGPL 대안

Gyan의현재essentials/full은 GPL 구성이므로 이름만 바꿔 LGPL이라고 표시하지 않는다. GPL 요소를 제외한 확인 가능한 빌드·툴체인·소스를 별도로 선정하고, libx264 의존 출력 계약을 Media Foundation 등의 허용 인코더로 바꾸는 호환성 검증이 필요하다. 같은 최종 MP4/자막/9:16 품질을 미검증인 채 드롭인 대체하지 않는다. 사용자 동의 없는 엔진 교체·유료 라이선스 구매·업체 연락은 하지 않았다.

시스템 라이브러리/SDK의 예외가 적용될 수 있으므로 외부 구성요소37개 모두에 동일한 소스 전달 의무가 있다고 단정하지 않는다. 각 요소의 실제 링크 형태·라이선스·예외 범위를 확정한 뒤 그 빌드에 필요한 대응 자료를 완성해야 한다.
