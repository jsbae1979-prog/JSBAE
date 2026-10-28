# Windows 11 로컬 초기화 차단 3건 진단 및 최소 보정

2026-10-28 · **최종 판정: CONDITIONAL**

기존 3건의 초기화 차단은 해소됐다. 실제 Windows 11에서 Guard-first create_app과
로컬 HTTP, React 12개 화면 접근, 샘플 재생, 대표 저장·재조회까지 확인했다.
TOP3 이력 읽기와 일부 포인터 메뉴 이동, 실제 OS DPI는 별도 잔여 항목이다.

## 기준 및 실행 횟수

- 저장소: `jsbae1979-prog/JSBAE`
- 브랜치: `codex/newsflow-windows11-local-runner-20261028`
- 시작 HEAD: `58c5ccbfe2a4ed1d9775b1467f69cbf33b92b739` (원격과 일치 확인)
- 최종 코드·보고 커밋은 이 보고서를 보존한 브랜치의 Git 로그에 기록한다.
- Windows 11 Pro 64비트, build 26300, Python 3.14.7.
- **진단 1회 + 보정 후 정식 검증 1회**. 추가 앱 실행·재시작·우회 실행 없음.
- GUI 도구: Windows PC의 Codex IAB. 이번 결과를 별도 Chrome·OS DPI 결과로 확대하지 않는다.
- 기존 8 PASS와 Chrome 22/15, 샘플 API9/GUI21, CI59, FFmpeg4 PASS 재사용.
  전체 Python 회귀·기존 Guard 감사·샘플 원본 검사를 반복하지 않았다.

## 차단 3건의 정확한 원인

증거: [diagnostic-result.json](diagnostic-result.json),
[진단 당시 소스 고정값](DIAGNOSTIC_SOURCE_HASHES.json).
이 실행은 checkpoint에서 중단됐으며 HTTP와 합성 seed에는 진입하지 않았다.

| 차단 | 이벤트·직접 호출 | 대상·호출 시점 | 분류 |
|---|---|---|---|
| outside-fixed-read-roots 1 | `os.listdir`; `importlib.metadata.FastPath.children`, 표준 라이브러리 `Lib/importlib/metadata/__init__.py:744` | `C:/Codex/NewsFlowAI-IsolatedReview/integration-20261024/candidate/newsflow-ai/src`; 앱 import 초기화 | 선택적·불필요한 과거 개발본 metadata 탐색 |
| outside-fixed-read-roots 2 | `open`; `zipfile.ZipFile.__init__`, `Lib/zipfile/__init__.py:1462`; metadata `zip_children:750` 경유 | 같은 과거 개발본 디렉터리; 첫 조회 실패 후 ZIP 탐색 fallback | 선택적·불필요한 탐색 |
| link-creation | `os.link`; 설치 filelock `_strict.py:73`, `_probe_link_follow_symlinks`; import 시 `:79`에서 호출 | `<SYNTHETIC>/Temp/tmp.../probe-source → probe-link`, `follow_symlinks=False` | 선택적 기능 감지; 실제 잠금 획득 동작이 아님 |

첫 두 호출의 상위 호출자는 `pydantic.plugin._loader.get_plugins`, `_loader.py:39`다.
Python 환경의 editable-install이 추가한 예전 src 경로를 플러그인 배포 metadata
탐색이 열거한 것이다. 현재 제품은 별도로 지정한 최신 src에서 import된다.
예전 경로를 새로 허용할 필요가 없다. 두 조회는 Guard에서 막혔으며 파일 내용은 기록하지 않았다.

세 번째 호출은 filelock이 링크 지원 여부를 검사하기 위한 throwaway probe다.
패키지 코드는 OSError/NotImplementedError를 처리하여 보수적으로 False를 반환한다.
WindowsFileLock의 NtCreateFile/LockFileEx 잠금과 다른 경로다.
운영 경로나 외부 파일에 링크를 만들려던 호출로 확대 해석하지 않는다.

설치 소스 `_strict.py` SHA-256:
`41564e8e8253a0ac0ed146fdaebdbed94afa3f7d604bd6b0ce25410f8dc436df`.
진단·보정 후 동일하다. Pydantic `_loader.py` 확인값:
`8408e04a58e82211b1dc0569229baac3948fb6d04d35e181493aea48c9cd8899`.
두 설치 파일은 수정하지 않았다.

## 최소 보정

| 파일 | 변경 |
|---|---|
| `local_policy.py` | 거절 이벤트·모듈·함수·줄·비민감 경로·시점 기록. 내용·토큰·전체 인자는 기록하지 않음 |
| `launch.py` / `runner.py` | HTTP 시작 전 종료하는 진단 모드 추가. 기존 Guard-first 및 누적 거절 checkpoint 유지 |
| `runtime_fixes.py` | 기존 읽기 roots 밖의 불필요한 모듈 검색 경로 제거. 실제 제거 1개 |
| `runtime_fixes.py` | 해시 고정된 filelock의 정확한 선택적 probe에만 미지원 반환. 실제 링크 syscall 생략 |
| `test_initialization_fixes.py` | 이번 수정의 새 집중 계약 8개 |
| `SOURCE_HASHES.json` / README | 검증 전용 소스 고정값 및 현 상태 갱신 |

읽기 허용 roots, DLL·심볼, PID·handle, SQLite, 네트워크, 비용·게시 승인 권한은
넓히지 않았다. 일반 링크 호출은 여전히 Guard에서 거부한다. filelock을 사전 import하지
않았고 CI 변수를 위조하지 않았다. 설치 패키지·제품·운영 Guard를 변경하지 않았다.

## 집중 검사 및 정식 앱 결과

[새 집중 검사](focused-fix-tests.log): **8 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
기존 실행기 8 PASS는 이전 증거이며 이번 8개와 다른 검사다.
새 검사는 검색 경로 제한, 합성 읽기, probe 무링크 처리, 일반 링크 차단,
외부 경로·운영 경로 차단, source 불일치 거부, 누적 거절 중단을 다룬다.
Python 파일 8개 구문 검사 PASS. UI 소스가 바뀌지 않아 React 전체 빌드·회귀는 반복하지 않았다.

[fixed-run-result.json](fixed-run-result.json): 실제 create_app **PASS**, Guard-first **PASS**,
HTTP 준비 **PASS**, 정책 거절 `[]`, Guard 거절 `[]`, gate 거절 `{}`.
선택적 링크 probe 1회 생략, 오래된 모듈 검색 경로 1개 제거.
ASGI lifespan·scheduler·background 유료 작업은 시작하지 않았다.
accepted ASGI 응답 90건: 200 응답 83, MP4 Range 206 응답 6, 대본 저장 303 응답 1.
이 목록은 실행기 자체가 거절한 URL까지 포함하는 전체 HTTP access log는 아니다.

## 실제 GUI 12개 화면

[GUI 결과 목록](captures/GUI_RESULTS.json) · 캡처는 아래 이름의 `.jpg`, 접근성 기록은 `.txt`.
**PASS는 화면 접근·명시한 관찰 범위만 의미한다. 모든 기능·공급사 성공을 뜻하지 않는다.**

| 화면 | 접근 | 실제 확인 범위 | 캡처 |
|---|---|---|---|
| 홈 | PASS | 합성 프로젝트·키 미설정·대시보드 | [화면](captures/01-home.jpg) |
| 콘텐츠 제작 홈 | PASS | 제작실 시작·승인 안내 | [화면](captures/02-create.jpg) |
| 뉴스 쇼츠 | PASS | TOP3·저장 대본·간편 설정·Revision | [화면](captures/03-shorts.jpg) |
| 캐릭터 쇼츠 | PASS | 참조 PNG·샘플3·저장 스토리·결과 불명/승인 차단 | [화면](captures/04-character.jpg) |
| 독립 AI 이미지 | PASS | 프롬프트·모델·비율·품질·샘플3; 유료 생성 없음 | [화면](captures/05-images.jpg) |
| 뉴스 TOP3 이미지 | PASS | 화면·모델·샘플3; 실제 작업 이력 읽기는 BLOCKED | [화면](captures/06-top3.jpg) |
| 뉴스 스튜디오 | PASS | 저장 기사·TOP3·출처·분석·제작실 연결 | [화면](captures/07-news.jpg) |
| 자동화 센터 | PASS | 예약0/활성0·저장과 활성화 분리; 예약 실행 없음 | [화면](captures/08-automation.jpg) |
| 라이브러리 | PASS | 내 합성 작업과 샘플12 구분·썸네일 | [화면](captures/09-library.jpg) |
| 게시 스튜디오 | PASS | 4개 플랫폼·계정 미등록·최종 승인 차단 | [화면](captures/10-publishing.jpg) |
| 성과·비용 | PASS | 미수집·미확정·실제 청구 미확인 표시 | [화면](captures/11-analytics.jpg) |
| 설정·관리 | PASS | 공급사 키 미설정·합성 저장 경로·플랫폼 미연결 | [화면](captures/12-settings.jpg) |

대표 저장: 합성 대본 장면1 수정 → 실제 `/ai/drafts/1` POST/303 → Revision 1→2 →
화면 reload 후 편집 문장과 Revision 2 보존 **PASS**.
기록: [저장 응답](captures/news-save-result.txt), [재열기](captures/news-reopen.txt).
실제 CSRF/Origin middleware를 경유했다. 이 성공을 충돌·모든 모드 저장 성공으로 확대하지 않는다.

## 이미지·MP4

라이브러리 DOM의 12개 이미지가 모두 실제 디코딩됐다:
샘플 PNG 9개 + MP4 poster 3개. 실제 생성 이력과 구분한다.
[자연 해상도 기록](captures/library-images.json). 일부 다른 화면의 초기 0 해상도는
캡처 당시 lazy loading 상태로, 최종 라이브러리 12개 디코딩과 구분한다.

| 샘플 MP4 | 재생·일시정지·시간 탐색 | 실제 메타데이터 |
|---|---|---|
| news-short | PASS | HTTP, 12초, 720×1280, 오류 null |
| character-short-robot | PASS | HTTP, 12초, 720×1280, 오류 null |
| character-short-cat | PASS | HTTP, 12초, 720×1280, 오류 null |

각 영상은 실제 native 컨트롤로 조작했다. 재생 시 paused=false/currentTime>0,
일시정지 시 paused=true/ended=false, 탐색 후 currentTime 변화가 관찰됐다.
[뉴스 영상](captures/news-video-playback.jpg), [로봇 영상](captures/robot-video-playing.jpg),
[고양이 영상](captures/cat-video-playing.jpg) 및 각 `*-video-*.json` 참조.
제품 FileResponse의 실제 206 응답 6건을 기록했다. file: 재생·보안 제한 해제 없음.
무음 12초 슬라이드 예제이며 완성형 AI 음성 쇼츠나 편집 원본 프로젝트가 아니다.
새 FFmpeg 제작은 실행하지 않았으며 기존 4 PASS만 재사용한다.

## 남은 제한과 판정 범위

1. **TOP3 이력 읽기 BLOCKED.** 화면에 “TOP 3 제작 기록을 불러오지 못했습니다.”가 표시됐다.
   `frontend/src/studio/TopThreeFeeds.tsx:83`의 GET `/api/feed-batches`가 실행기의 읽기
   허용 목록에 없다. 코드 대조상 실행기 403 경로다. 자체 403은 현 access 기록에 남기지
   않으므로 실제 해당 상태 응답의 별도 서버 로그 증거는 없다. 자동 허용·재실행하지 않았다.
2. **포인터 메뉴 이동 원인 NOT VERIFIED.** 좁은 기본 IAB 화면에서 “이미지 제작” 클릭 후
   뉴스 스튜디오, “자동화 센터” 클릭 후 라이브러리에 도착한 관찰 각 1회가 있었다.
   키보드 Enter로 같은 메뉴 이동은 정상이다. 도구 좌표/반응형 배치/제품 원인은
   확정하지 않았고 제품 결함 또는 신규 회귀로 단정하지 않는다. UI 코드는 변경하지 않았다.
3. **OS DPI 100/125/150/200% 모두 NOT VERIFIED.** 운영 세션 설정·로그아웃·배율 변경 없음.
   기본 IAB responsive 화면 검증을 OS DPI 또는 1920/1366 검증으로 바꾸어 표시하지 않는다.
4. 실제 공급사 호출, 생성 전체 동선, 캐릭터 쓰기/worker FileLock, 모든 승인/충돌 경우,
   운영 진입점/lifespan은 미검증이다. 기존 native/thread/잠금 제한은 그대로 남아 있다.

## 정리·보호

[환경 및 정리](environment-and-cleanup.json): 진단·검증 프로세스 정상 종료,
강제 종료 없음. 18765 listener 없음. 운영 8765 PID **55740** 유지.
Windows venv launcher의 소유 부모 PID와 실제 HTTP PID는 따로 기록한다.
native handle/CRT descriptor/buffer/unresolved 각 0, SQLite 0, 테스트 thread 0,
Rtl 할당/해제 7/7, FileLock 획득/해제 7/7, cleanup error 0.
운영 DB·키·OAuth·DPAPI·설정·미디어·백업 사용/복호화/수정 없음.
보호 UI12개·샘플 원본·기존 Guard/CI/adapter·filelock 설치 파일 변경 없음.
기존 `validation/` 보존. reset/clean/stash/force push 없음. PR35·main 변경 없음.

기존 초기화 차단 3건 해소와 실제 로컬 HTTP/GUI 대표 검증은 완료했다.
잔여 제한 때문에 최종 인수는 **CONDITIONAL**이다. 추가 권한 확대·실행·제품 수정·
운영 적용·PR 병합·실제 유료 API·SNS 게시 없이 보고 후 종료한다.
