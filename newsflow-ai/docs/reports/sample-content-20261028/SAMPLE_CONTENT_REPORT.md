# 기본 샘플 콘텐츠 12개 등록 및 최초 실행 UX

작성일: 2026-10-28 KST. 최종 판정: **CONDITIONAL**.

## 기준과 결과

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`.
- 시작 HEAD: `7c0bf7e89e29e54039a6594634d482ea62027786`.
- 최종 검증 코드: `b7870b9bb8ef1257f09c72b1dd0f12004ec7025d`. 보고서 커밋은 이 코드에 문서·합성 캡처만 추가한다.
- [샘플 Windows CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40600439451): **API 9 PASS / GUI 21 PASS / FAIL 0 / ERROR 0 / SKIP 0**, CI 전체 성공. 21개는 사용자 동선 11개와 5개 화면×두 viewport 10개다.
- [기존 제작실 GUI 집중 회귀](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40595192217): **18 PASS**, 코드 `46f5b7d`. 이후 샘플 접힘·활용 UX, 입력 주제 보존, 참조 선택 완료·표시 및 수동 업로드 전환 보완은 신규 21개 동선으로 검증했다. 기존 기본 업로드/생성/승인 계약은 보존한다.
- [최종 제작실 집중 CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40600439652): **59 PASS (정적/모델 58 + API 1)**. 전역 전체 회귀는 실행하지 않았다. 과거 전체 회귀·보안·디자인 감사 결과를 최신 실행으로 재표시하지 않는다.
- Python 3.14.7, Node 24.22.1, Playwright 1.64.1, 실제 Chrome 156.0.8078.48, GitHub Windows Server 2025 Runner. 로컬 TypeScript 검사/Vite 빌드 및 CI 타입·빌드 성공.

## 실제 첨부 파일 검증

ZIP SHA-256: `c6a508471bdd12be4241004a6e66e5e0405146624cd213f8b5cc0c6c01a7440b`. CRC PASS, 안전한 새 임시 폴더에 추출했으며 기존 파일을 덮어쓰지 않았다. **ZIP 전체 26개 파일**: 기본 샘플 12개, 보조 JPEG 9개, concat 텍스트 3개, 설명/원본 매니페스트 2개다. 첨부 바이너리를 수정하지 않았다.

- 독립 이미지 3, 뉴스 TOP3 이미지 3, 캐릭터 PNG 3, 뉴스 MP4 1, 캐릭터 MP4 2 = **12개**.
- PNG 9개 전체 디코딩 성공, **720×1080 RGB**. TOP3 예제도 1080×1350이 아니며 임의 확대/변환하지 않았다. 실제 TOP3 제작 엔진의 출력 계약은 유지한다.
- MP4 3개는 모두 **720×1280 · 12초 · H.264 · 오디오 스트림 없음**. PC의 격리 파일 검사에서 FFprobe 메타데이터와 FFmpeg 전체 디코딩을 확인했다. Windows Chrome에서 각 영상의 실제 재생·6초 지점 탐색도 성공했다.
- 캐릭터는 로봇/고양이/드래곤으로 파일명과 내용이 일치한다. 배경 제거 PNG가 아니다. Seedance 실제 공급사 호환성은 NOT VERIFIED이다.
- 영상은 무음 슬라이드 예제이며 **NewsFlow 편집 원본 프로젝트는 없다**. 보조 JPEG/concat은 ZIP에 보존되지만 앱의 편집 가능한 프로젝트 데이터인 것처럼 등록하지 않았다.
- 기본 샘플은 **6,850,339바이트**, 가장 큰 주 파일 862,718바이트. 일반 생성/사용자 MP4 제외 정책은 유지하고, 승인된 세 MP4 경로만 `.gitignore`의 정확한 등록 예외로 추가했다. 기존 LFS 정책 변경이나 무분별한 미디어 업로드는 없다.
- 12개 파일의 Git 등록 바이트와 첨부 SHA-256 일치. 전체 첨부 목록·지원 JPEG 정보는 [SAMPLE_FILE_AUDIT.json](SAMPLE_FILE_AUDIT.json)에 보존했다.

| 제목 | 패키지 내 상대 경로 | 바이트 | 실제 규격 | SHA-256 |
|---|---|---:|---|---|
| 로봇 캐릭터 | `characters/CHAR_S01_robot.png` | 567,227 | 720×1080 · PNG/RGB | `6832ac0a0828d3e819fa3a4105f7a7ba12fee6cfc4143dfd9caff9b42171f5bf` |
| 고양이 캐릭터 | `characters/CHAR_S02_cat.png` | 588,410 | 720×1080 · PNG/RGB | `18f5702917c7908e3f65a5dc937cc01cbb36ef60549d16fc74c2bd70979fe9c8` |
| 드래곤 캐릭터 | `characters/CHAR_S03_dragon.png` | 658,198 | 720×1080 · PNG/RGB | `a22daa60e3eb9ec7f062210ae0d4dfcf553cf8c8315ef9529835484cccccefac` |
| 도시 이미지 예제 | `images/standalone/IMG_S01_city.png` | 780,022 | 720×1080 · PNG/RGB | `c9608819f1b030d034af87c0f26064cead7fa2c4bf7e1b1785a21d99338369ea` |
| 고양이 이미지 예제 | `images/standalone/IMG_S02_cat.png` | 808,413 | 720×1080 · PNG/RGB | `462566d59e2eaac0f17edf4d11dee2433506bc47cd95e2bb4adaee74476a9acb` |
| 지구 이미지 예제 | `images/standalone/IMG_S03_earth.png` | 838,128 | 720×1080 · PNG/RGB | `dd781fe0c716cb746870bbc7c0309f64f62eb53d761a6e6d9d962045c2558e4a` |
| 가상 AI 뉴스 카드 | `images/news-top3/TOP3_S01_ai.png` | 862,718 | 720×1080 · PNG/RGB | `e28c902251e217d53672f5858fc095986c46dc1c8b75877ffc211cddc38a1474` |
| 가상 전기차 뉴스 카드 | `images/news-top3/TOP3_S02_ev.png` | 639,458 | 720×1080 · PNG/RGB | `1624c901b4108a647e7c87a602f3882edcc521be26862a0e6abbc71a1d22f341` |
| 가상 경제 뉴스 카드 | `images/news-top3/TOP3_S03_economy.png` | 644,958 | 720×1080 · PNG/RGB | `4f9aad8e4fc51052c90c9fd6e1b7a26ae270d82800c1eca673acc705e50588c6` |
| 로봇 쇼츠 미리보기 | `videos/character-shorts/SHORTS_CHAR_S01.mp4` | 148,539 | 720×1280 · 12초 · 오디오 없음 · H.264 | `7fda267e97d574426c5d1024185aa3a28265510790b77994c527294aa11bf8b0` |
| 고양이 쇼츠 미리보기 | `videos/character-shorts/SHORTS_CHAR_S02.mp4` | 151,040 | 720×1280 · 12초 · 오디오 없음 · H.264 | `9da45f543a4ab5b7ab737fd3128d0706a7b542ddaf91da133effbc4245742189` |
| 뉴스 쇼츠 미리보기 | `videos/news-shorts/SHORTS_NEWS_S01.mp4` | 163,228 | 720×1280 · 12초 · 오디오 없음 · H.264 | `3609e4c56a88d9a79df912991086bbbc1dd17945543623659085af394049f3b8` |

## 저장 및 최초 실행

공통 자산은 권장 구조를 Python 패키지 내부로 옮긴 `src/newsflow/assets/samples/`에 등록했다. `manifest.json`에 ID, 제목, 설명, 유형, MIME/형식, 경로, SHA-256, 실제 규격/길이/오디오, 출처·권리 상태, sample/version, 예제 프롬프트를 기록했다. 원본 설명·매니페스트도 함께 보존했다.

[샘플 매니페스트](https://github.com/jsbae1979-prog/JSBAE/blob/b7870b9bb8ef1257f09c72b1dd0f12004ec7025d/newsflow-ai/src/newsflow/assets/samples/manifest.json)와 [원본 설명](https://github.com/jsbae1979-prog/JSBAE/blob/b7870b9bb8ef1257f09c72b1dd0f12004ec7025d/newsflow-ai/src/newsflow/assets/samples/SOURCE_README.txt)을 함께 제공한다.

파일을 사용자 DB에 자동 복제하거나 생성 완료 이력을 삽입하지 않는다. 앱이 샘플 전용 로컬 카탈로그를 읽으므로 신규 사용자에게 바로 표시되고, 반복 실행·동일 버전 업데이트 시 자동 중복 등록 자체가 없다. 누락/손상 샘플은 경고와 함께 제외하며 기존 사용자 작업과 앱 초기화는 유지된다.

같은 합성 사용자 폴더로 실제 앱/서비스/SQLite 엔진을 종료·재초기화한 뒤 숨김, 복사본, 기존 파일과 생성 이력 비삽입이 유지됨을 확인했다. 실제 EXE·Windows 프로세스 재시작이나 설치 프로그램 업데이트 성공으로 확대하지 않는다.

명시적 복사 때만 사용자 데이터 폴더의 `sample-copies/v1/<sample-id>/<sha256>.<ext>`에 저장한다. 같은 샘플 복사는 멱등이고, 수정된 사용자 복사본은 덮어쓰지 않는다. 숨김 및 복사 상태는 기존 사용자별 SQLite의 전용 `AppSetting` 키에 저장한다. 새 DB 스키마나 migration은 없다. 실제 작업 참조로 쓸 PNG는 기존 ImageStudio의 검증·정규화된 사용자 자산 사본을 재사용한다. 공통 원본은 앱 API에서 읽기만 가능하다.

## 화면별 기능

| 화면 | 구현 및 신규 검증 |
|---|---|
| 독립 AI 이미지 | 샘플 3개·미리보기·명확한 샘플 표시·예제 프롬프트 확인. 예제를 현재 입력으로 복사한 뒤 사용자가 명시적으로 새 초안을 저장한다. 모델/비율/품질과 기존 생성 승인 흐름 유지. 실제 생성 결과로 위장하지 않음 |
| 뉴스 TOP3 이미지 | 가상 예제 3개를 실제 분석 결과/뉴스 3건과 분리. 실제 production-context의 TOP3에 샘플 0건인 것을 검증. 개별 뉴스 제작 모드 재노출 없음. 참조 파일로 복사/다운로드 가능 |
| 캐릭터 | 로봇·고양이·드래곤 3종 선택으로 새 작업의 로컬 PNG 참조만 연결. 입력 중인 주제 보존, 기존 PNG 업로드 전환과 참조 선택 충돌 방지. 별도 명시적 저장 전 작업/유료 생성 없음. 샘플 영상 2개는 재생/참조 저장과 연관 PNG 선택 지원 |
| 뉴스 쇼츠 | 샘플 MP4 1개 미리보기·실제 재생·참조 복사. 실제 최신 뉴스/완료 프로젝트로 등록하지 않음. 기존 TOP3·대본·Revision·영상 승인 엔진 유지 |
| 라이브러리 | 전체 / 내 콘텐츠 / 샘플 콘텐츠 구분. 실제 사용자 프로젝트는 기존 목록을 유지하고, 내 콘텐츠에는 명시적 샘플 참조 복사본만 별도 표시. 공통 샘플은 readonly 갤러리로 구분. 휴지 보관 기능 보존 |

전 화면에 미리보기, 이미지/영상 구분, 내 작업으로 복사, 참조 활용, 사용자별 숨김/다시 표시, 복사본 다운로드를 제공했다. 단순 MP4를 편집 프로젝트로 전환하는 기능은 없다. 샘플 이미지를 기반으로 한 유료 편집 생성도 새로 구현하지 않았다. 예제 프롬프트는 원본 제작 지시문이 아닌 예제로 명시한다.

샘플은 제작실에서 간결한 가로 목록과 접기/펼치기를 제공한다. 신규 사용자는 바로 볼 수 있고, 저장 자료가 있는 화면의 첫 로딩에는 기본 접힘으로 구성했다. 샘플을 입력에 활용하면 접혀 기존 편집/모델/비용/승인 영역으로 돌아간다. 캡처는 샘플 확인을 위해 펼친 상태이며 기존 제작 패널 구조를 보존했다. 새 전용 CSS는 `.sample-gallery`/`.sample-dialog` 및 그 내부로 제한했다. 1920×1080과 1366×768의 5개 화면 모두 가로 넘침 없이 확인했다. [캡처 모음](SAMPLE_UI_EVIDENCE.html)을 제공한다. 기존 승인 PNG 전체 비교 감사는 반복하지 않았다.

## 검증·수정 이력

샘플 9개 API 검사에서 최초 12개 표시·실제 생성 이력 비삽입, 전체 파일 해시/이미지 디코딩/영상 Range 응답, CSRF·Origin 거부, 반복 복사/사용자 파일 보존, 숨김·재개·사용자별 DB 및 파일 분리, 캐릭터 참조 연결, MP4 참조 전용 처리, 누락/손상 파일 처리, 수정된 개인 복사본 덮어쓰기 거부를 확인했다.

브라우저에서는 프롬프트 새 초안 저장, PNG 선택/새 캐릭터 작업, 기존 입력 보존과 수동 업로드 모드, 세 MP4 재생·탐색, 라이브러리 필터, 숨김/복원, 오프라인 컨텍스트 조회, 10개 viewport 동선을 검증했다. 통신은 **실제 React → 테스트용 파일 IPC → 실제 Python FastAPI TestClient ASGI/SQLite**다. API 성공 JSON을 단순 Mock으로 대체하지 않았다. 로컬 TCP 서버 또는 Windows 11 실제 창 검증으로 확대하지 않는다. 인터넷을 끊은 실제 Windows 세션 검증은 별도로 수행하지 않았다.

검증 중 발견한 기존 결함: 캐릭터 작업 0건일 때 `job?.referenceUrl` 비교의 우변에서 `job.id`를 읽어 TypeError가 발생했다. `job` 존재 확인만 추가하여 최초 빈 상태를 수정했다. 샘플 선택 시 입력 중인 주제를 보존하고 수동 PNG 업로드가 선택된 참조와 충돌하지 않도록 입력 상태만 보완했다. 실제 참조 소재 API의 문자열 목록을 Select 옵션에 매핑하여 선택값이 비어 보이던 기존 표시 오류도 수정했다. 참조 선택과 목록 갱신 중에는 충돌하는 캐릭터 저장/참조 동작을 비활성화하고 완료 후 허용한다. 정상 제작 엔진/모델/API 계약은 변경하지 않았다.

초기 커밋은 전역 MP4 제외 규칙으로 영상 3개가 누락되어 6 PASS/2 FAIL이었다. 정확한 파일 예외로 수정했다. 이후 빈 캐릭터 화면에서 UI 실패가 드러났고, 수정 뒤 21개 GUI 검사가 통과했으나 검증 도구의 진행 중 요청/종료 순서에서 IPC timeout 및 Route already handled 오류가 발생했다. 요청 처리를 완료한 뒤 종료하고 탐색 취소와 실제 전송 오류를 구분해 기록하도록 도구를 보완했다. 기존 브라우저 캡처의 offscreen 이미지 전체 decode 대기도 보이는 범위로 제한했다. 최종 성공 실행과 초기 실패/취소는 [EXECUTION_HISTORY.json](EXECUTION_HISTORY.json)에 별도로 남긴다. skip/xfail·단순 타임아웃 상향·실패 삭제는 없다.

최종 Python/Node 종료 코드 각각 0, 잔여 Chrome 0, 강제 정리 false, 잔여 IPC 요청 0, 앱 lifespan 정상 종료. 샘플 DB/사용자 복사본/프로필은 Runner TEMP 전용이며 업로드하지 않았다. GitHub 보존 산출물은 검증된 샘플, 소스, 검사 결과, 합성 캡처뿐이다. TestClient/httpx deprecation과 기존 Vite/lucide 경고는 유지하고 임의 의존성 교체는 하지 않았다.

## 보호 상태·변경 파일

- 원래 사용자 제작 데이터/기본값을 덮어쓰지 않으며 실사용 운영 DB·ledger·키·OAuth·설정·미디어·백업은 읽거나 변경하지 않았다. 운영 프로그램 종료/재시작, 8765 포트 사용, 유료 공급사/SNS 호출 없음. 새 운영 전수 해시 검사를 한 것은 아니다.
- 기존 Guard·CSP·Origin·CSRF·DPAPI·비용/게시 승인·결과 불명 보호 정책 유지. 샘플 복사나 선택은 생성 승인/비용 승인으로 취급하지 않는다. 실제 공급사 생성/모델 계정 권한은 미검증이며 샘플을 실제 공급사 결과로 표시하지 않는다.
- 홈/콘텐츠 제작 홈 보호 소스·공통 스타일·기존 명령 계약 파일은 변경 0. Workbench 변경은 샘플 컴포넌트 import, 라이브러리 상태 및 라이브러리 분기에 한정한다. 기존 보호 캡처 증거를 재사용하고 신규 픽셀 비교/전체 디자인 감사를 수행했다고 주장하지 않는다.
- PR #35 head `75626f74cc1bfe750d24132e44019bcda478247b`, Draft/open/unmerged 재확인. PR/main 변경 없음. 기존 `validation/` 보존, reset/clean/stash/force push 없음.
- 주요 변경: `src/newsflow/assets/samples/`, `src/newsflow/samples/`, `main.py` 라우터 등록 2줄, `pyproject.toml` 패키지 데이터, 정확한 MP4 `.gitignore` 예외, `SampleGallery.tsx`/`samples.css`, 네 제작실의 샘플 연결 및 라이브러리 분기, 샘플 집중 테스트/CI와 기존 GUI 테스트 도구 종료 순서.

## 남은 제약과 최종 판정

1. **Windows 11 로컬 실제 GUI는 NOT VERIFIED.** 실제 OS DPI 검증도 새로 수행하지 않았다. Windows Server CI의 headless Chrome 결과를 대체 증거로 과장하지 않는다.
2. **사용권·상업적 이용·재배포 권한은 미확정.** 사용자 승인 개발 브랜치에 등록했지만 일반 사용자 제품 배포 전 원본 권리 확인이 필요하다. 설치파일 공개나 SNS 게시를 하지 않았다.
3. **신규 EXE 재빌드/설치·업데이트·제거 실검증은 미실행.** setuptools 패키지 데이터에 포함했고 기존 PyInstaller의 패키지 non-Python 자산 수집 경로도 재사용 가능하지만, 기존 기술 EXE가 이번 샘플을 이미 포함한다고 표시하지 않는다.
4. 사용자별 DB·폴더 분리는 합성 프로필 기준이며 Windows 복수 계정의 실제 설치/권한 실증은 미실행이다. 기존 PowerShell identity 조회 CI 시간 초과 1건도 이번 범위와 무관하여 재검증하지 않았다.
5. 무음 12초 슬라이드·RGB 참조 PNG·편집 프로젝트 없음은 첨부의 실제 한계이며 임의의 완성형 AI 쇼츠로 대체하지 않았다. 실제 유료 생성·참조 이미지 외부 전송·SNS 게시 성공 검증 없음.

개발 및 허용된 집중 검증은 완료했다. **CONDITIONAL**은 위 미검증·권리/배포 조건을 남긴 판정이다. 운영 배포·PR 병합·추가 기능 개발 없이 중단하고 다음 지시를 기다린다.
