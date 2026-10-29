# 상단 중복 전체 메뉴 제거 및 단일 사이드바 적용

**최종 판정: ACCEPTED — 요청된 탐색 메뉴 정리·집중 UI 검증·운영 무재시작 반영 범위.**

브랜치 `codex/newsflow-bat-distribution-prep`, 시작 HEAD `fa27bf8f1b301d9232751228ff032bb2af1eadc0`.

## 변경 내용

- 제작실의 `CoreNavigation` 전체 메뉴와 제작실 전환 드롭다운을 제거했다. 화면 제목·새로고침·저장자료 표시·기능 탭·제작/검토/승인 동작은 유지했다.
- 관리 화면의 상단 전체 메뉴와 중복 내부 사이드바를 제거하고 앱의 기존 공통 사이드바를 사용한다. 기존에 공통 사이드바를 숨기던 제작실/관리 화면 전용 CSS만 제거했다.
- 전체 이동은 공통 사이드바의 기존8개 항목으로 통일했다. 세 제작실은 기존 '콘텐츠 제작 → 카드 → 선택 대화상자 → 제작실' 동선을 그대로 유지한다.
- 이미지의 'AI 이미지 생성 / 뉴스 기반 이미지'와 설정의7개 기능 탭은 유지했다. 화면별 패널·카드·색상·아이콘·미리보기·버튼 이벤트의 기존 코드를 재설계하지 않았다. 메뉴 제거에 따른 상단 높이 회수와 공통 사이드바 폭 적용만 발생한다.
- 홈/콘텐츠 제작 홈의 JSX·공통style.css는 변경하지 않았다. 승인 PNG·샘플 원본·제작 엔진·Python API·DB schema·보안 코드는 변경0.

## 신규 집중 검증

| 항목 | 결과 |
|---|---|
| TypeScript --noEmit | PASS |
| Vite build | PASS |
| 단일 사이드바·중복메뉴0·제목·가로넘침 | **24/24 PASS**,12화면×1920×1080/1366×768 |
| 사이드바8경로 + 기존 선택 대화상자 통한3제작실 | **11/11 PASS**,합성 자료 |
| 이미지 기능 탭2개 + 설정 탭7개 | **9/9 PASS**,합성 자료 |
| 전후 기능 버튼/disabled상태·기능 탭 유지 | **14/14 비교 PASS** |
| 홈·콘텐츠 제작 홈 전후 기하 배치 | **4/4 PASS**,2해상도 |
| 보호 소스 | 기존33파일 중 요청된6파일만 변경/삭제,다른27파일 불변 |
| 운영 Chrome 새로고침 후 메뉴 표시 | **PASS — 사용자 직접 '정상 표시됨' 확인** |

자동화 미리보기에 쓰인 오래된 fixture의 weekdays가 빈 문자열이라 전후 모두 렌더 오류가 있었다. 실제 ProductionSchedule 모델은 JSON list다. 분리된 미리보기의 복사본만 []로 정리하고 해당 화면을 다시 검사했다. 제품·원본fixture·운영 예약은 수정하지 않았다. 브라우저의 요청 크기와 실제 innerWidth를 대조해 불일치 측정은 제외하고 최종24개 모두 실제 해상도 일치를 확인했다.

이번 브라우저 증거는 운영 Chrome을 조작하지 않는 별도 in-app 합성 브라우저다. 엔진·DB·키를 사용하지 않았고 모든 쓰기 요청을 거절하는 미리보기에서 기존 UI를 렌더했다. 샘플 수량/유료 생성/실제 API/OS DPI의 신규 검증으로 확대 해석하지 않는다. 실제 운영 Chrome의 Ctrl+F5 결과는 사용자 확인으로 별도 기록했다.

기존 승인된 저장·Revision·비용·SNS 승인·결과 불명 보호 증거를 재사용했다. 전체 회귀·보안 감사·디자인 PNG 감사·샘플 원본 검사는 반복하지 않았다. 기존 폰트 런타임 경로/use-client/500KB 묶음 경고는 그대로이며 빌드 실패는 아니다.

## 운영 반영과 재시작

**운영 재시작 불필요·실행0회.** 기존 FileResponse/StaticFiles는 같은 정적 경로의 현재 파일을 읽으므로 새 JS/CSS를 먼저 추가하고 index를 마지막에 원자적으로 교체했다. 이전 해시 자산은 열려 있는 탭과 복구를 위해 삭제하지 않았다. layout은 index의 크기/SHA와 새 JS/CSS2개 항목만 갱신해 다음 시작의 무결성 검사를 유지했다.

- 운영 PID **35844**,주소 `http://127.0.0.1:18768`,실행 경로 `C:/NewsFlowAI` 그대로.
- 현재 소유 세션 marker·launch 설정 bytes 불변. 토큰·쿠키 조회/출력/이전0,Chrome 재인증 필요 없음.
- 새 index SHA `569585a0e2586cba3ecdca4713174a3bb44d4e02c360c0a867982c1165572504`.
- JS `index-B0EXIKkr.js`,CSS `index-3Y7SYDU5.css`. 파일별SHA는 `STATIC_APPLY_RESULT.json`.
- index/layout 원본bytes와ACL,변경 전 테이블 메타데이터를 별도 비공개 `C:/Codex/NewsFlowAI-IsolatedReview/sidebar-ui-apply-20261029/`에 보존했다. 실패하면 원본 index/layout으로 복원하는 경로를 구현했으며 실패/복원 실행은 없었다.
- 사용자 직접 Ctrl+F5 확인 완료: **“정상 표시됨”**.

## 데이터·보안 보호

적용 전후 **47개 테이블의 모든 내용hash·건수 동일**,기존 기사169건·AI처리48·대본6·영상프로젝트7·이미지게시물3건 보존. 암호문6개·미디어20개 총26파일SHA 동일. 기존169원본과 백업A/B DB의 기존SHA도 모두 동일했다. DB/키/미디어/백업에 대한 쓰기·복원·migration·복호화0.

적용한 index/layout의ACL 유지,인증 없는 GUI와 새 JS 요청은 모두403으로 계속 거절된다. LocalAccess/CSRF/Origin/DPAPI/비용·게시 승인/결과 불명 보호/무서명 업데이트 정책을 변경하지 않았다. 실제 유료API/OAuth/SNS/자동화 실행0. main/PR35/외부 배포/기존 프로그램 삭제0.

미리보기 탭3개·테스트 서버2개 포트를 정리했고 운영 프로세스는 유지했다. 기존 미추적validation/자료도 보존한다. 비공개 설정·프로필·DB·키·미디어·백업은Git에 넣지 않았다.

## 변경 파일과 비교 자료

- frontend/src/studio/core/shared.tsx
- frontend/src/studio/core/CoreStudios.tsx
- frontend/src/studio/core/CoreNavigation.tsx 삭제
- frontend/src/studio/core/core-studios.css
- frontend/src/studio/management/Management.tsx
- frontend/src/studio/management/management.css

[전후 비교](visual-comparison.html),captures/10개 합성 캡처,UI_METRICS.json,NAVIGATION_FLOWS.json,FEATURE_TABS.json,COMPARISON_RESULT.json,PROTECTED_SOURCE_RESULT.json 및 운영 적용/보존 결과를 함께 보존한다. 새 생성·게시·배포·추가 개발 없이 현재 운영을 유지하고 종료한다.
