# 핵심 제작실 5개 Windows GUI 최종 검증

작성일: 2026-10-28 KST. 최종 판정: **CONDITIONAL**.

## 기준 및 신규 결과

- 브랜치: `codex/newsflow-core-studios-rebuild-20261027`.
- 시작 HEAD: `d4a47060c8ec4b04f48bb43b50dfc8c7238e61a1`.
- 이번 검증 코드 HEAD: `b98925f702a518dd3f8c501ce0194d1ec3558bd5`.
- [최종 Windows Actions](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40591562445): **18 PASS / 0 FAIL / 0 SKIP**, 브라우저 pageerror 0, 백엔드 오류 0. 8개 기능 동선 + 5개 화면 × 2 viewport 검사이며 전체 Python 회귀가 아니다.
- React Vite 빌드 성공. Python 3.14.7, Node 24.22.1, Playwright 1.64.1, Chrome 156.0.8078.48. 실제 실행 OS는 GitHub Windows Server 2025 Runner이다. **현재 PC Windows 11 로컬 전체 GUI는 NOT VERIFIED**.
- 최종 산출물 ZIP SHA-256: `0b6a98bfe382f32ccad0e08585289ce0336928b0ae801ac313019d58e3f20d26`. Artifact ID `12774068492`. CI 공개 digest와 다운로드 바이트를 비교했다.

## 실제 연결 범위

기존 승인된 `test_full_app_forms.client`의 합성 프로필·SQLite·Fake Provider를 재사용했다. 실제 React JS/CSS가 Chrome에서 실행되고 실제 `create_app` 라우트/서비스가 DB에 저장한다. 모든 앱 요청은 **Playwright → 임시 파일 IPC → FastAPI TestClient ASGI**로 연결한다. 네트워크 TCP 서버나 Windows 11의 실제 서버 프로세스/OS 입력을 검증한 결과로 확대하지 않는다. 18765는 테스트 origin이며 TCP listener를 열지 않았다. 운영 8765는 사용하지 않았다.

파일 업로드는 CDP multipart의 파일 바이트 생략을 확인하여, 사용자가 선택한 합성 DOM File 358바이트를 검증 후 실제 동일 POST 라우트의 multipart로 전달했다. 합성 원본과 바이트가 같은 경우만 허용한다. 이는 테스트 전송 보완이며 **실제 TCP multipart 전송 자체는 미검증**이다. 앱/API 응답을 임의 성공 JSON으로 대체하지 않았다.

## 화면별 사용자 동선과 디자인

| 화면 | 신규 기능 동선 결과 | 승인 PNG 시각 판정 | 차이·미검증 |
|---|---|---|---|
| 뉴스 쇼츠 | PASS: TOP3·출처 표시, 실제 대본 편집·저장·재조회, 동시 Revision 변경 시 409 및 입력 보존, 단계 번호 없음, 제작 승인 창 별도·미체크 기본값 | MINOR | 글꼴·발광·간격은 원본과 작은 차이. 영상 없는 합성 작업은 빈 미리보기로 표시. 이번에 실제 영상 생성·재생은 하지 않음 |
| 캐릭터 쇼츠 | PASS: 참조 PNG 실제 등록, 새 주제 작업 저장, 저장 스토리·3장면·상태 표시, 결과 불명 작업의 장면 생성 버튼 차단 | FUNCTIONAL_CONSTRAINT | 1366에서 3열을 세로 재배치하므로 스토리보드/견적은 스크롤 필요. 실제 720p 생성 계약과 1080×1920 최종 합성 구분. Claude·Seedance 생성·FFmpeg 새 실행은 미실행 |
| 독립 AI 이미지 | PASS: 프롬프트·품질 초안 저장·재열기, 승인 체크 후 Fake 생성, 성공 파일 디코딩·미리보기, 재사용 검토 창, 완료 결과 재생성 버튼 차단 | MINOR | 스타일 타일은 사진 대신 텍스트/아이콘. 참조 기반 유료 편집 미구현 안내 유지. 실제 재사용 저장 확정·다운로드 OS 동작은 이번 검사 범위 밖 |
| 뉴스 TOP3 이미지 | PASS: 완료 분석 명시 선택·작업 저장, 기존 대본/요약 재사용, Fake 3개 독립 결과 각각 1080×1350, 개별 제작 UI 없음, 검토·생성 분리, 완료 작업 재생성 버튼 차단 | FUNCTIONAL_CONSTRAINT | 지원하지 않는 날짜/로고 선택은 추가하지 않음. 출처·권리·AI 표시 검토 유지. 좁은 화면에서 문구/이력 영역은 스크롤 필요 |
| 뉴스 스튜디오 | PASS: 보관 뉴스 검색·출처·기존 분석 확인·뉴스 쇼츠 이동, 동선 전후 분석 수 1 유지 | FUNCTIONAL_CONSTRAINT | 실제 제공 필드만 표시. 미지원 추천·즐겨찾기·가상 지표 없음. 이번에는 실제 뉴스 수집/유료 분석을 실행하지 않음 |

최신 승인 PNG 5개와 기존 비교 자료를 재사용하고 새 실제 ASGI 연결 캡처를 확인했다. 예시 인물·뉴스·가상 금액 차이는 디자인 결함으로 세지 않았다. 기존 공통 사이드바/헤더는 보존했다. **새 MAJOR 레이아웃 결함은 확인되지 않았지만 픽셀 단위 일치 또는 사용자 최종 디자인 인수를 의미하지 않는다.** [비교 자료](visual-comparison.html), [판정 JSON](SCREEN_VERDICTS.json).

## 화면 크기·승인 창·DPI

- 1920×1080, 1366×768의 5개 화면 캡처 총 10개: 문서 가로 넘침 0. 주요 버튼의 실제 click 및 스크롤 동선을 검증했다. 버튼 위치 기록도 GUI_RESULTS에 보존했다. 모든 버튼/모든 오류 상태를 완전 검증했다고 주장하지 않는다.
- 1366×768의 뉴스 제작 승인 창, 캐릭터 등록 창, 이미지 재사용 검토 창 3개: viewport 내부 경계 검사 PASS. 추가 캡처 3개 포함. 창 높이 각각 691.2 / 600.2 / 441.4px.
- **실제 Windows OS DPI 100% / 125% / 150% / 200%: 모두 NOT VERIFIED.** 현재 운영 사용자 세션을 바꾸거나 로그아웃하지 않았다. viewport·devicePixelRatio·CSS zoom을 OS DPI 결과로 사용하지 않는다.

## 안전 정책·보존

- 실제 유료 AI·OAuth·SNS 호출 0. 앱 외부 요청 기록 0, 백엔드 외부 네트워크 차단 유지. Chrome 자체의 백그라운드 통신 전체를 OS 수준에서 증명한 것은 아니므로 그 범위는 NOT VERIFIED이다.
- 분석 레코드 수 1, Fake 이미지 호출 4(독립 1 + TOP3 3). 저장 분석을 새로 유료 호출하지 않았다. 완료 결과 자동 재요청 차단·결과 불명 캐릭터 차단을 확인했다. TOP3 부분 실패·중단 복원·unknown 요청 보호의 상세 테스트는 기존 앱/API 7 PASS 증거를 재사용했다.
- 실제 계정 모델 접근·가격·잔액·Claude/Seedance 생성 성공은 검증하지 않았다. 합성 모델 목록 표시를 실제 계정 권한으로 확대 해석하지 않는다.
- Python app lifespan 정상 종료, Python 프로세스 종료, 잔여 Chrome 0, 강제 정리 false. 임시 DB/이미지는 Runner TEMP 전용이며 GitHub artifact/소스에 포함하지 않았다. Runner 폐기 전 합성 DB 파일 자체가 0개라는 별도 검사는 하지 않았다.
- 제품 `src/`, React `frontend/`, 기존 native/Guard 검증 계층은 시작 HEAD 대비 Git diff 0. 홈·콘텐츠 제작 홈을 포함한 보호 화면의 JSX/CSS/라우트는 변경하지 않았다. 기존 소스/캡처 보호 증거 재사용, 이번에 보호 화면 신규 캡처를 다시 만들지 않았다.
- 운영 앱·DB·설정·키·OAuth·미디어·백업은 테스트 입력으로 사용하거나 수정하지 않았다. 운영 상태 전수 해시를 새로 검사한 것은 아니며 전역 불변을 추정하지 않는다. 운영 프로세스 종료·재시작·배포 없음.
- PR #35 head `75626f74cc1bfe750d24132e44019bcda478247b`, Draft/open/unmerged 확인. PR/main 변경 없음. 기존 로컬 `validation/` 보존, reset/clean/stash/force push 없음.

## 검증 도구 보완 및 실패 이력

제품·Guard 변경 없이 `.github/workflows/newsflow-five-studios-gui.yml`, `tools/studio_v3/integration/windows_gui_bridge.py`, `tools/studio_v3/integration/windows_gui.browser.cjs`만 추가했다. 기존 fixture의 프로세스 차단은 유지하면서 Popen class 상속 호환성을 보존했다. 사전 filelock import·import 순서 변경·운영 Guard 완화는 하지 않았다.

첫 시도는 fixture Popen 타입 문제로 GUI 실행 전 실패했다. 두 번째 13 PASS/5 FAIL은 선택자/필수 입력/분석 선택 절차 문제, 세 번째 16 PASS/2 FAIL은 CDP 업로드 바이트 생략과 이미지 decode 대기 문제였다. 최종 시도는 18 PASS/0 FAIL이다. 이력·원래 CI 링크는 [EXECUTION_HISTORY.json](EXECUTION_HISTORY.json)에 보존했다. 실패를 skip/xfail·단순 timeout 상향·제품 계약 변경으로 처리하지 않았다. **신규 제품 FAIL/ERROR는 관찰되지 않았지만 미실행 기능 전체에 결함이 없다는 뜻은 아니다.**

## 기존 증거 재사용 및 남은 조건

기존 앱 초기화 9 PASS, 집중 CI 59 PASS, 합성 브라우저 42 PASS, 앱/API 7 PASS, 기존 1080×1920 30초 MP4·프레임 및 보호 캡처를 과거 증거로 유지한다. 이번 18개와 합산하여 새 전체 회귀 결과로 표시하지 않는다. 기존 전체 Python 회귀·보안 감사·네이티브 어댑터 개발을 반복하지 않았다.

남은 항목은 Windows 11의 정식 허용된 로컬 TCP 앱/GUI 실행, 운영 세션에 영향을 주지 않는 실제 OS DPI 환경, 실제 유료 생성·새 MP4 합성·SNS 실전송이다. 이번 작업에서 새 Guard 개발/전체 회귀/보안 사전 단계는 제안하지 않는다. 이 보고서의 CONDITIONAL은 해당 미검증 범위와 MINOR/기능 제약을 남긴 판정이며 운영·배포 승인 아니다.

검증 완료 후 운영 배포·PR 병합·추가 개발 없이 중단한다.
