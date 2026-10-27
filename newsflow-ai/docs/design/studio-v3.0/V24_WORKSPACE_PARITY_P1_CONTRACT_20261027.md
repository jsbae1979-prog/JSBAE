# NewsFlow AI — v2.4 제작실 원본 배치 복원 P1 구현 계약

기준: 2026-10-27 KST
베이스: 56c859bff2806c29bb0f44cab490e3a527005fa7
상태: DESIGN CONTRACT ONLY — React 미수정, 시각 검증 미실행

## 불변 범위
- 대시보드 및 콘텐츠 제작 홈의 JSX/CSS/자산/동선 변경 금지.
- main, PR #35, 운영 코드·데이터·키·DB·배포 및 앱 재시작 변경 금지.
- 기존 API, 승인, 비용, result_unknown, 재시도 차단, 미디어 URL 계약 유지.
- 기존 완료 보정(뉴스 쇼츠 sticky 장면 탭, 9:16 제한, 캐릭터 참조 PNG 상단, 이미지 두 탭, 썸네일 빈 상태, 공급사 키 버튼) 유지.

## 원본 기준
- docs/design/studio-v3.0/prototypes/NewsFlow_Master_Experience_v2.4.html
- docs/design/studio-v3.0/assets/master_dashboard_reference.png (색상·표현 기준, 홈 수정 불가)
- 기존 frontend/src/studio/Workbench.tsx 및 workbench.css

## 공통 제작실 정보 구조
1. 상단: 현재 프로젝트, 제목, 저장/상태. 기존 명령 및 상태와 연결.
2. 본문 좌측: 기사/캐릭터/이미지 자료와 선택 가능한 소재.
3. 본문 중앙: 편집 및 실제 검증된 미디어 캔버스.
4. 본문 우측: 작업 설정, 비용, 검토, 승인, 결과 불명.
5. 본문 하단: 장면 스토리보드/타임라인 또는 이미지 결과·소재 목록.
실제 지원하지 않는 드래그 레이어·BGM 믹싱·가상 앵커 기능을 동작하는 것처럼 표현 금지.

## 화면별 매핑
- shorts: 기존 stage-rail, script-editor, scene-tabs, voice-options, ai-scenes, preview(currentMedia), timeline의 state/handler 보존. 장면 선택과 실제 영상 시점 이동 유지. 장면 타임라인을 독립 하단 영역으로 표시하되 같은 상태와 action을 재사용.
- characters: 참조 PNG 첫 화면 표시 보존. 좌측 참조·자료, 중앙 스토리·장면, 우측 고정 모델·공식 견적·승인, 하단 스토리보드. 미생성 영상은 명시적 빈 상태.
- images: 독립 AI 이미지/뉴스 이미지 게시물 두 탭 및 선택 상태 보존. 좌측 소재·대상, 중앙 입력·캔버스, 우측 속성·검토, 하단 검증된 결과/자료. 참조 기반 유료 편집 미구현 안내 유지.

## 반응형/접근성
- 1920×1080: 3영역 + 하단 타임라인 우선.
- 1366×768: 중앙 캔버스/주요 동작 가시성 우선. 3열 강제 금지; 필요시 좌측 자료 패널 접기 또는 영역 순차 배치.
- 실제 Windows DPI 100/125/150/200%는 별도 실기기 검증 전 NOT VERIFIED.
- keyboard focus, tab order, aria-pressed, 44px 수준 주요 버튼 목표, reduced motion 유지.
- 이미지 로딩/404, 미연결, 생성 중, 실패, 결과 불명 구분. 합성 데이터로 실제 성공 표시 금지.

## 구현 순서 및 증거
1. 격리 브랜치에서 3개 제작실만 JSX/CSS 재배치. 신규 서비스·데이터 변경 금지.
2. TypeScript/Vite 빌드 및 해당 컴포넌트 테스트.
3. 동일 합성 데이터/브라우저에서 1920/1366 캡처: 최초 v2.4 원본, 변경 전, 변경 후를 화면별 나란히 기록.
4. 뉴스 쇼츠 대본 수정/장면 이동, 캐릭터 참조/견적, 이미지 두 탭/미리보기/실패 상태의 주요 사용자 동선 검사.
5. 결과: 디자인/기능/보안/Windows를 각각 PASS/FAIL/NOT VERIFIED로 분리. 테스트 미실행을 PASS로 쓰지 않음.
6. 사용자 시각 승인 전 PR #35 반영·main 병합·운영 재시작 금지.

## 이번 커밋
문서만 작성. UI 구현, 빌드, 캡처, 실계정 검증 미실행.
