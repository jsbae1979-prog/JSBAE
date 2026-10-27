# 참고 화면 기능 확장 — 로컬 구현·검증 보고

작성: 2026-10-19 KST. 판정 제안: **CONDITIONAL — 로컬 구현·합성 자동 검증 완료, 실계정 운영 활성화 전**.

- 브랜치: `codex/newsflow-ux-video-app`
- 시작: `8b2295f` / clean
- 최종 검증 코드: **`74f1c70a06be09dcd82bd355d6711255115f317b`**
- PR #35는 변경하지 않음. push·PR 편집·신규 PR·merge·force push·운영 배포 없음. 원격 상태를 이번 작업에서 재조회하거나 변경하지 않았으며 기존 Draft 보존 지시를 유지함.
- 기존 전체 회귀 **57 FAIL 기록 유지**. 이번 범위 테스트의 PASS를 전체 회귀 PASS로 확대하지 않음.

## 구현 결과

| 항목 | 결과 | 실제 동작과 경계 |
|---|---|---|
| 6개 참고 화면 | PASS · 범위별 | 기존 뉴스/대본/영상 화면과 배타적 설정 탭 유지. 게시 허브 4플랫폼/달력, 성과 분석 화면·메뉴를 실제 라우트에 연결. 이미지의 모든 가상 기능을 제공한다고 표시하지 않음 |
| TikTok·Facebook Adapter | PASS · Fake/HTTP 계약 | init→파일 전송→상태, Facebook finish, TikTok creator/privacy/음악·브랜드 동의 검사. 기본 실전송 차단 |
| 공식 HTTPS 전송 코드 | PASS · 메모리 HTTP | 호스트/메서드/경로 허용목록, TLS 검증, timeout, 제한된 응답 읽기, stream, redirect/retry 금지. 운영 activation=False 고정 |
| 통합 게시 | PASS · Fake | 기존 YouTube/Instagram과 4플랫폼 조합, 독립 결과·부분 완료·처리 대기·불명·계정 변경·중복/재시작 차단. 신규 합성 결과는 실제 성공으로 기록하지 않음 |
| 게시 캘린더 | PASS · 로컬/Fake | KST 월 이동·일정 저장/재진입/수정/해제, revision CAS, 승인 snapshot, missed/unknown 복구. 실제 예약 전송은 비활성, GUI에 작동하는 척하는 실행 버튼 없음 |
| 성과 수집·저장 | PASS · Fake | 공식 4플랫폼 요청/응답 계약, 권한/계정/게시 영상 binding, 누락값/기간/단위·합성 구분, 재조회 갱신·실패 시 이전 수치 보존 |
| 게시 시각 추천 | PASS · 합성 계산 | YouTube의 동일 계정·완전한 첫 7일 성과·충분한 표본으로 KST별 중앙값 비교. 자료 부족은 추천 안 함. 미래 조회수 예측/보장 아님 |
| 데이터 유지 | PASS · 임시 DB | additive 0014, 기존 migration 0001~0013 불변. 복사본의 예약 승인 해제/일시 중지. 기존 설정·영상·OAuth 모델 유지 |

새 화면:
- `/queue`: 네 플랫폼, 게시 초안, KST 달력과 일정 목록.
- `/analytics`: 플랫폼/계정별 KPI·일별 차트·영상 성과 기록·근거 기반 추천. 기존 `/?show=tasks` 제작 활동은 별도 버튼으로 계속 접근 가능.
- `/publishing/platforms`: TikTok·Facebook 계정 자격/권한/준비 상태.
- `/publishing/calendar/{id}`: 일정 재조회·시간 변경, 변경 시 승인 초기화.

설정 첫 화면의 기존 6개 배타적 탭과 한 곳에서 저장하는 동작은 보존했다. 게시 계정 탭에 추가 플랫폼 준비 경로만 연결했다. 기존 AI 기본값, 키, 비용 한도, 음성 선택을 변경하지 않았다.

## 최종 테스트

환경: **Cloud Linux / Python 3.12.14 / Chromium 151.0.7922.173**. 임시 DB·Fake OAuth/게시/성과 응답·합성 키 사용.

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
  .venv/bin/python tools/verify_social_scope.py \
  --junitxml /tmp/newsflow-social-release-results.xml
```

**975 passed / 1 skipped / 1 warning / 0 failed — 225.27초.**

- skip: 기존 `test_youtube_connection.py:351`, 실제 Windows current-user DPAPI가 필요한 테스트. 임의 추가 skip 없음.
- warning: 기존 FastAPI/Starlette TestClient httpx deprecation.
- Ruff: PASS. pip check: PASS (`No broken requirements found`). git diff --check: PASS.
- Python 3.14, Windows Actions/Chrome/DPAPI: **NOT VERIFIED**. 현재 실행 환경이 Linux이고 원격 push/PR/워크플로 변경은 금지되어 있어 새 Actions를 실행하지 않았다.
- 기존 전체 회귀를 다시 돌려 57건을 숨기거나 PASS로 바꾸지 않았다. 이번 범위 밖 전체 신규 실패 여부는 재판정하지 않았다.
- 초기에 발견한 실패는 아래처럼 수정/갱신한 뒤 위 최종 명령으로 다시 확인했다. 중간 실패 결과를 최종 PASS로 혼합하지 않았다.

테스트 증거: [원본 출력](evidence/social-platforms/pytest-final.txt), [JUnit](evidence/social-platforms/pytest-final.xml).

검증 범위: 새 플랫폼/HTTP/달력/성과/GUI + 기존 YouTube/Instagram 게시·인증, publishing foundation, DB, CSRF/SSRF/TLS 관련 검사, 제작 scheduler, AI 영상 설정/migration, intelligence, 작업실·장면 편집·설정·뉴스/소스 화면. 실행 목록은 `tools/verify_social_scope.py`에 고정되어 있다.

Windows 준비 명령(실행한 것으로 표시하지 않음): 기존 개발 의존성과 Chrome 준비 후 Python 3.12 및 3.14 각각의 격리 가상환경에서 `python tools/verify_social_scope.py --junitxml <새 임시 결과 파일>` 실행. Playwright 브라우저 경로는 기존 `NEWSFLOW_TEST_BROWSER_EXECUTABLE` 방식 사용. 사용자 DB/설정/영상 경로를 인수로 전달하지 않는다. 운영 run.bat, Task Scheduler, 계정 로그인을 실행하지 않는다.

## 브라우저와 화면 증거

**21개 페이지×뷰포트 검사 PASS**, 실제 Chromium. 1920×1080, 1366×768, 390×844. HTTP 200, 가로 넘침/입력 버튼 화면 이탈/JS 오류/외부 브라우저 요청 0. Windows 화면 배율 검증이 아니다.

추가 실제 동선 테스트: 플랫폼/계정 조회, 빈 성과 표시, 키보드 Enter 제출, 달력 다음 달, 계정 설정→추가 플랫폼 조건, 설정 탭 전환/재진입, 일정 POST 저장→이동→재진입→수정→stale revision 거부→해제, 기존 장면 선택/편집/뉴스 필터. CSRF 없는 변경 요청은 거부했다.

| 화면 | 이전 화면 (기존 증거 재사용) | 최종 실제 앱 화면 |
|---|---|---|
| 뉴스 수집 | [이전](evidence/reference-studios/news-1920.png) | [1920](evidence/social-platforms/news-1920.png) · [1366](evidence/social-platforms/news-1366.png) · [390](evidence/social-platforms/news-390.png) |
| AI 대본 편집 | [이전](evidence/reference-studios/editor-1920.png) | [1920](evidence/social-platforms/script-1920.png) · [1366](evidence/social-platforms/script-1366.png) · [390](evidence/social-platforms/script-390.png) |
| 영상 제작 | [이전](evidence/reference-studios/video-1920.png) | [1920](evidence/social-platforms/video-1920.png) · [1366](evidence/social-platforms/video-1366.png) · [390](evidence/social-platforms/video-390.png) |
| 게시 허브 | [이전](evidence/reference-studios/publish-1920.png) | [1920](evidence/social-platforms/publish-1920.png) · [1366](evidence/social-platforms/publish-1366.png) · [390](evidence/social-platforms/publish-390.png) |
| 성과 분석 | [이전 제작 활동](evidence/reference-studios/activity-1920.png) | [1920](evidence/social-platforms/analytics-1920.png) · [1366](evidence/social-platforms/analytics-1366.png) · [390](evidence/social-platforms/analytics-390.png) |
| 설정 | [이전](evidence/reference-studios/settings-1920.png) | [뉴스·대본 탭](evidence/social-platforms/settings-1920.png) · [계정 탭](evidence/social-platforms/accounts-1920.png) · [모바일 계정 탭](evidence/social-platforms/accounts-390.png) |

[뷰포트/재생 검사 JSON](evidence/social-platforms/browser-audit.json), [스크린샷별 상태·SHA256](evidence/social-platforms/screenshots.json).

캡처의 수치·계정·기사·영상은 **합성 데모**다. 일반 앱 화면은 합성 성과를 제외한다. 작은 화면에서 긴 메뉴가 꺾이던 것을 “성과 분석”으로 정리했고, 원래 제작 활동은 성과 화면의 명확한 버튼으로 남겼다. 그림과 기능 범위가 완전히 동일하거나 실제 사용자가 편의성을 승인했다고 주장하지 않는다.

데모 MP4 3개: 실제 FFmpeg 합성, 1080×1920/H.264/AAC/30초, **무음·10fps 화면용 자료**. 브라우저 재생 확인. [ffprobe 증거](evidence/social-platforms/demo-mp4-probe.json). 플랫폼 게시 규격 전체 검증이나 실제 한국어 음질·자막 싱크·최종 영상 품질 검증으로 간주하지 않는다.

재현: `python tools/social_ui_preview.py --data-dir <새 TEMP 하위 경로> --port 47966` 및 `python tools/capture_social_ui.py --origin http://127.0.0.1:47966 --out <새 캡처 폴더> --browser <Chromium 경로>`. 데모는 기존 데이터를 열지 않고, 외부 연결·인증·게시를 차단한다. Cloud의 실행 환경을 Windows 운영 기능으로 바꾸지 않았다.

## 발견·수정한 문제

1. 기존 YouTube/Instagram GUI 호출에 불필요한 확장 옵션이 전달되던 회귀: 추가 플랫폼이 있을 때만 새 옵션을 전달하도록 수정.
2. 0014 DB를 기존 데이터 복사 도구가 거부: 새 버전 허용과 복사본 예약 무력화 추가. 기존 migration 내용은 그대로 유지.
3. 새 schema head 때문에 이전 테스트의 `0013` 기대값 실패: migration 보존 assertions를 유지하면서 head만 `0014`로 갱신. 테스트 삭제/skip 없음.
4. 새 성과 필터의 명확한 입력 이름: 플랫폼/계정 aria-label 추가, 키보드 제출 확인.
5. 검토 이후 새 플랫폼 계정 identity 변경: 고정한 identity와 실행 직전 binding 비교, 다른 기존 플랫폼도 전송 전에 차단.
6. 신규 달력 테스트 fixture가 Alembic 이력 없이 ORM로 생성된 점: 합성 백업에 해당 fixture의 실제 schema version을 명시. 제품의 버전 검사를 완화하지 않음.
7. 메뉴 경로가 성과 분석으로 바뀐 부분은 새 목적지 기대값으로 갱신하고, 기존 제작 활동 화면의 직접 접근 테스트를 유지.

## 공식 조건과 NOT VERIFIED

상세 근거: [설계·공식 API 조사](../design/social_platform_operations.md), [문서 GET 및 해시](evidence/social-platforms/official-documents.json).

- **TikTok**: 내부/개인·팀 계정 전용 업로드 유틸리티가 공개 Direct Post 심사에 부적합할 수 있다. 앱 목적/배포 대상의 공급사 확인이 선행되어야 한다. 정책을 우회하지 않는다. 실제 Login Kit/공개 게시/계정 조건은 NOT VERIFIED.
- **Facebook**: Page 전용 CREATE_CONTENT와 scopes, 공개 Reels 승인 필요. Instagram 권한만으로 Facebook 게시 권한이 있다고 가정하지 않는다. 실제 앱 심사·계정·Reels 세부 미디어 호환성은 NOT VERIFIED.
- 성과: 실제 계정 read/monetary 권한 및 원격 콘텐츠 ID 매핑을 검증하지 않았다. 운영 binding은 차단 상태. Fake 수집을 실제 수집으로 표시하지 않는다.
- 예약: 실제 무인 전송은 비활성이다. 실제로 실행하려면 별도 코드 활성화·계정/권한/동의 검토가 필요하다. TikTok 무인 예약 미지원. Windows 종료/절전/재부팅 실사용은 NOT VERIFIED.
- 추천: YouTube 관찰 비교만 구현. 다른 플랫폼의 시간대 추천, 인과 예측, 수익 보장, 실제 사용 성과는 NOT VERIFIED/미지원.
- 원본의 가상 뉴스 앵커, BGM·임의 효과 트랙, 지리 지도, 전 플랫폼 수익 등은 승인된 범위 검토안의 제외/조건부 항목이다. 새 유료 엔진·가짜 데이터로 채우지 않았다.
- 실제 Windows 11, 한국어 청취, 공급사 품질, RSS/유료 AI, 실계정 OAuth·업로드·게시: **NOT VERIFIED**.

## 외부 호출 및 보존

실제 유료 API **0건**, 실제 OAuth/토큰 발급 **0건**, 실제 계정·성과 API **0건**, 실제 MP4 외부 전송·SNS 게시 **0건**. 공식 문서는 공개 GET으로만 조사했다. 새 공식 transport는 운영 활성화가 항상 False이고 테스트는 합성 토큰·메모리 connection. 브라우저는 loopback 외 요청을 차단했다. 운영 DB/키/설정/기존 MP4·운영 앱에는 접근하거나 변경하지 않았다. 테스트용 앱만 생성·종료했다.

최종 원격 변경 없음. 다음 단계는 사용자 검토 후 별도 운영 활성화/Windows 검증 범위를 정해야 한다. 이번 작업 이후 추가 개발·실호출은 중단한다.
