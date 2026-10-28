# Windows 11 최종 잔여 문제 해결 및 제품 인수

2026-10-28 · **최종 판정: CONDITIONAL**

TOP3 이력 조회와 포인터 메뉴 이동 문제는 해결했다. 실제 OS DPI별 검증은
운영 세션을 변경할 수 없는 이번 범위에서 NOT VERIFIED로 유지한다.
전체 제품 출시·운영 전환·실계정 API 성공을 승인하는 보고서는 아니다.

## 1. 브랜치 및 범위

- 저장소: `jsbae1979-prog/JSBAE`
- 작업 브랜치: `codex/newsflow-windows11-local-runner-20261028`
- 시작 로컬/원격 HEAD: `4a3e998d398a739f199528ea7315fafed40a65e9`
- 최종 HEAD는 이 보고서를 포함한 브랜치 Git 로그/완료 메시지에 기록한다.
- 환경: 기존 Windows 11 PC / Python 3.14.7 / 합성 DB·설정·미디어 / 127.0.0.1:18765.
- 테스트 앱 실행 1회. 같은 실행 중 CSS 빌드 후 페이지를 다시 로드했다. 운영 재시작 없음.
- 기존 12개 화면 접근, MP4 3개, 대본 저장·재열기, Chrome22/15, API9/GUI21,
  CI59, FFmpeg4 PASS는 이전 증거로 재사용했다. 이번에 다시 검증한 결과로 합산하지 않는다.

## 2. TOP3 제작 이력 조회 — PASS

실제 프런트 요청은 `TopThreeFeeds.tsx:83`의 GET `/api/feed-batches`다.
제품 `src/newsflow/gui/creation_routes.py:106`의 `feed_batches`는 서비스의
`recent()`, `view()`, `defaults()`를 호출한다. 현재 앱 sessions의 SELECT와
저장 결과 검증만 수행하고, 생성·저장·상태 복구·예약·게시는 호출하지 않는다.
성공 항목의 파일 검증도 해당 합성 data_dir 내부에서만 수행된다.

조치: 검증기 `http_surface.py`에서 **정확한 GET `/api/feed-batches`만** 추가했다.
HEAD/POST/PUT/DELETE/OPTIONS, 하위 `/step`, `/change`, `/review`, `/file`,
`/defaults` 경로는 새로 허용하지 않았다. 기존 로컬 저장 목록은 그대로다.
제품 API·Origin·CSRF middleware·DB 접근 계약은 변경하지 않았다.

합성 초기 데이터에 실제 `TopThreeFeeds.create`로 작업 #3을 저장했다.
이는 로컬 초안 준비이며 HTTP 생성 API 허용·공급사 호출이 아니다.
3개 항목은 pending, 성공 파일은 0개다. 가짜 생성 성공/완성 이미지를 만들지 않았다.

- 실제 GET: **200**, batch #3 / status saved / revision 1 / ranks [1,2,3].
- GUI: 작업 #3, TOP1/2/3 대기 결과, 모델·출처·문구, 최근 작업 이력 표시.
- 기존 “TOP 3 제작 기록을 불러오지 못했습니다.” 메시지 사라짐.
- 조회 전후 논리 상태·revision·세 항목 상태 동일: **true**.
- 이번 HTTP POST 요청 **0건**, 생성·게시·외부 호출 **0건**.

증거: [실행 결과](runner-result.json), [조회 화면](captures/top3-history.jpg),
[DOM 기록](captures/top3-history.txt), [집중 결과](captures/RESULTS.json).

## 3. 포인터 메뉴 이동 — 제품 CSS 결함 확인·보정 PASS

키보드 Enter 정상이라는 기존 결과는 재사용했다. 도구 문제로 단정하지 않고
545px viewport에서 DOM rect, hit-test, 화면 및 실제 좌표 클릭을 조사했다.

### 수정 전 재현

캐릭터 화면의 “이미지 제작” 버튼 rect는 x=274.453125, y=12,
width=21.8125, height=34였다. CSS `white-space:nowrap` 텍스트가 버튼보다
넓은데 flex 항목은 축소되어 이웃 라벨이 겹쳤다.
버튼 중앙의 `document.elementFromPoint(...).closest('button')`는
**“뉴스 스튜디오”**였다. 실제 viewport 좌표 **(285,29)**를 클릭하자
URL이 `/studio/news`로 이동하여 기존 문제를 재현했다.

display:flex, pointer-events:auto, position:static, z-index:auto였다.
중앙의 실제 DOM 대상 자체가 이웃 버튼이므로 event 전파나 모델 상태보다
레이아웃 hit 영역의 문제다. React 핸들러는 기존 key로 onNavigate를 호출하며 변경하지 않았다.

증거: [수정 전 수치](captures/pointer-char-before.json),
[수정 전 화면](captures/pointer-char-before.jpg),
[실제 좌표 및 잘못된 이동](captures/pointer-char-before-click.json).

### 최소 제품 수정

제품 변경은 `frontend/src/studio/core/core-studios.css` **4개 추가 줄**뿐이다.

```css
.core-studio .core-navigation-links { min-width: 0; }
.core-studio .core-navigation-links > button { flex-shrink: 0; }
```

기존 선언 안에 min-width를 추가하고, 위 자식 버튼 규칙을 추가했다.
기존 작은 화면의 가로 스크롤을 사용한다. 색상·글꼴·카드·본문 배치·메뉴 목록·
라우트·이벤트를 재설계하지 않았다. 홈/콘텐츠 홈/관리 화면에는 이 selector가 적용되지 않는다.

### 수정 후

| 범위 | 실제 전송한 viewport 좌표 | hit-test / 이동 | 결과 |
|---|---|---|---|
| 545px, 캐릭터→이미지 | (254,29) | 이미지 제작 → `/studio/images` | PASS |
| 545px, 이미지→자동화 | (227,29) | 자동화 센터 → `/studio/automation` | PASS |
| 1366px, 캐릭터→이미지 | (834,35) | 이미지 제작 → `/studio/images` | PASS |
| 1366px, 이미지→자동화 | (996,35) | 자동화 센터 → `/studio/automation` | PASS |

보정된 이미지 메뉴 폭은 72.5625px, flex-shrink=0이다. 좁은 화면에서는
메뉴를 가로 스크롤해 중앙 대상이 자기 버튼임을 확인한 뒤 클릭했다.
1366px에서는 메뉴 10개 중앙 모두 자기 버튼과 일치했다.
이동 후 이미지 제작 및 자동화 센터의 `aria-current="page"`도 확인했다.

nominal viewport는 545×860 및 1366×768, 실제 문서 clientWidth는 scrollbar를
제외한 530/1351이다. root CSS zoom=1이었다. 이 값을 OS DPI로 사용하지 않았다.
좌표는 실제 도구에 전달한 viewport 논리 좌표이며 OS 물리 좌표나 event clientX를
별도 native hook으로 가로채지는 않았다.

증거: `captures/pointer-*-after-*.json/.jpg/.txt`,
[1366px 메뉴 전체 hit-test](captures/pointer-wide-nav.json),
[데스크톱 화면](captures/pointer-wide-nav.jpg),
[활성 이미지 메뉴](captures/active-image-nav.json),
[활성 자동화 메뉴](captures/active-automation-nav.json).

## 4. 실제 Windows OS DPI — NOT VERIFIED

| 실제 OS 배율 | 12개 화면·메뉴·미리보기·승인 모달·샘플 갤러리 |
|---|---|
| 100% | NOT VERIFIED |
| 125% | NOT VERIFIED |
| 150% | NOT VERIFIED |
| 200% | NOT VERIFIED |

현재 제공된 도구에서 Settings/Display 대상 창이나 별도 테스트 desktop/session을
확보하지 못했다. 다른 세션의 존재를 전수 조사한 결과라는 뜻은 아니다.
운영 사용자 세션의 배율·로그아웃·OS 설정은 변경하지 않았다.
브라우저 viewport는 포인터 문제 재현용으로만 사용하고 종료 전 reset했다.
OS DPI 전체 검증 조건은 운영 환경에 영향을 주지 않는 실제 Windows 테스트 세션이다.

## 5. 신규 집중 결과

- URL 허용 계약: **5 PASS / 0 FAIL / 0 ERROR / 0 SKIP**.
- 실제 GUI 집중 항목: **5 PASS** (TOP3 이력 1 + 두 폭의 포인터 이동 4).
- 수정 전 기존 결함 재현 1건은 위 수정 전 증거로 보존; 보정 후 잔여 FAIL 아님.
- TypeScript PASS, Vite PASS. 기존 runtime font 경로, lucide `use client`,
  500kB 초과 chunk 안내는 남아 있다. 관련 없는 빌드 재구성은 하지 않았다.
- Guard/gate/파일 정책 거절 0. OS DPI 4개 배율은 미검증.
- 허용 범위 밖 `/news/{1,2,3}/thumbnail` 9개 요청은 HTTP 403으로 계속 거절했다.
  합성 기사에는 실제 대표 이미지가 없으며 기존 “미리보기 없음” 대체 표시를 유지했다.
  새 기사 이미지 권한을 추가하거나 이 거절을 숨기지 않았다.

전체 Python 회귀·기존 Guard 감사·디자인 재구축·원본 샘플 검사는 반복하지 않았다.

## 6. 데이터·운영 보호 및 변경 파일

제품 파일: `frontend/src/studio/core/core-studios.css`만 변경.
제품 Python/API/JSX/라우트·저장 schema·인증·비용·게시 계약 변경 0.
검증기 파일: `runner.py`, `seed.py`, `http_surface.py`, `test_feed_read_surface.py`,
`SOURCE_HASHES.json`, README 및 이번 보고서/증거.

[환경·정리](environment-cleanup-dpi.json): 소유 launcher 및 HTTP 프로세스 종료,
18765 listener 없음, 강제 종료 없음. native/CRT/buffer/unresolved/SQLite/thread
각 0, 잠금/해제 8/8, Rtl 할당/해제 8/8, cleanup error 0.
운영 8765 PID **55740** 유지. 운영 파일·DB·키·OAuth·DPAPI·설정·미디어·
백업을 테스트에 사용하거나 변경하지 않았다. 반복 전수 해시 감사는 수행하지 않았다.
샘플 12개 원본, 기존 완료 브랜치, PR35·main, 미추적 `validation/` 보존.
실제 유료 API·SNS·예약 실행·운영 배포·병합 없음.

## 최종 인수 조건

이번 잔여 작업 중 TOP3 이력과 포인터 메뉴는 PASS다. 실제 OS DPI별 검증은
NOT VERIFIED이므로 최종 판정은 **CONDITIONAL**이다.
기존의 실제 API·운영 전환·배포에 대한 별도 승인 조건은 유지한다.
추가 기능 개발·권한 확대·운영 실행 없이 종료한다.
