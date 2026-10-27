# NewsFlow AI — 사용자 승인 UX/UI 기준 및 Codex 감사 참고자료

기준일: 2026-10-27 KST
상태: APPROVED DESIGN DECISIONS / IMAGE IDENTITY PENDING
원본 코드 기준: PR #35, 당시 확인 HEAD `75626f74cc1bfe750d24132e44019bcda478247b` (작업 시 최신 HEAD 재확인)
목적: 진행 중인 Codex 읽기 전용 감사를 지원하는 참고 문서. 이 문서는 새로운 구현 승인이나 제품 변경 지시가 아니다.

## 사용자 승인 디자인 (13개 화면·모드)

| 화면 | 승인 기준 | 주의 |
|---|---|---|
| 홈(대시보드) | 현재 구현 유지 | JSX/CSS/이미지/동선 직접·간접 변경 금지 |
| 콘텐츠 제작 홈 | 현재 구현 유지 | JSX/CSS/이미지/동선 직접·간접 변경 금지 |
| 뉴스 쇼츠 제작실 | 2차 시안 | 기사·대본·장면·음성·9:16 미리보기 |
| 캐릭터 쇼츠 제작실 | 4차 간편 제작 시안 | 참조 PNG → Claude 스토리 → Seedance 장면 → 검토/승인 → FFmpeg |
| 독립 AI 이미지 | 2차 시안 | 프롬프트·생성 결과·이력; 참조 이미지 유료 편집 미구현 |
| 뉴스 기반 이미지 | 2차 시안 | 개별 뉴스 이미지·문구·출처 검토 |
| TOP 3 자동 피드 | 3차 수정 시안 | 뉴스 3건별 이미지/상태; 제작 모드 번호 제거, 뉴스 순위는 유지 |
| 뉴스 스튜디오 | 2차 시안 | 뉴스 수집·검색·출처·분석; 영상 편집 중복 금지 |
| 자동화 센터 | 1차 시안 | 예약 저장/활성화 분리, 실행 기록·결과 불명 보존 |
| 라이브러리 | 2차 시안 | 검색·유형 필터·썸네일·미리보기·제작실 이동·휴지 보관 |
| 게시 스튜디오 | 4차 시안 | 플랫폼별 계정·검토·권한·승인·결과 기록 |
| 성과·비용 | 4차 시안의 **두 번째** 디자인 | 4개 플랫폼, Instagram 다중 계정, 실제 성과·AI 사용량·비용 구분 |
| 설정·관리 | 2차 시안 | 기능별 탭, API·모델·계정·뉴스 출처·Windows·시작 가이드 |

## 기존 구현/정책과의 대응
- 실제 메뉴 및 기능은 최신 React/Python 코드를 우선 확인한다. UI 이미지의 장식 버튼·수치·가상 계정명은 구현 요구사항이 아니다.
- 플랫폼: Instagram Reels, YouTube Shorts, TikTok, Facebook Reels. Instagram의 실제 연결 계정 수/명칭은 검증된 메타데이터만 사용한다.
- TikTok/Facebook 실전송 및 실계정 성과 수집은 별도 활성화/승인 전 차단. 합성 검증을 실제 성공으로 표시하지 않는다.
- 청구액, 추정 비용, 토큰 사용량, 미수집 지표를 구분한다. 알 수 없는 값은 0으로 대체하지 않는다.
- 기존 데이터·API 키·OAuth/DPAPI·게시/유료 승인·성공/결과 불명 재시도 방지 정책 유지.
- Windows DPI/실계정/API 검증은 수행하지 않았다면 NOT VERIFIED.

## 승인 PNG 원본 식별 상태
- 사용자와 ChatGPT 대화에서 선택한 개별 시안은 11개 변경 대상 화면/모드에 해당한다.
- 기존 대화에서 수집한 11개 PNG 후보 패키지는 존재하나 **승인 메시지와 PNG의 1:1 대응은 아직 검증되지 않았다.**
- 특히 뉴스 쇼츠 2차 시안의 정확한 원본 식별이 미완료다.
- 따라서 이 문서 자체를 'PNG 11개 최종 승인 원본'의 증거로 사용하면 안 된다.
- GitHub에 없는 시안은 ASSET_NOT_AVAILABLE/NOT VERIFIED로 기록하고 임의의 다른 이미지를 최종 시안으로 대체하지 않는다.
- 마스터 PNG 및 v2.4 HTML은 기준 참고자료이지, 이후 승인된 모든 개별 시안의 대체품이 아니다.

## Codex 현재 감사와의 관계
- 이미 진행 중인 감사 지시를 대체하거나 재시작하지 않는다.
- 최신 PR HEAD, 실제 메뉴/라우트, JSX/CSS, Python 서비스/명령, 시안별 구현 가능 여부, 미지원 요소를 대응표로 보고한다.
- 기존 검증 근거를 재사용하고 불필요한 전체 회귀는 반복하지 않는다.
- **이번 단계는 읽기 전용 감사**: 제품 코드 수정, GitHub push, PR 변경/병합, 운영 앱 재시작, 유료 API/SNS 실전송 금지.
- Codex 감사 결과 보고 후 사용자 승인에 따라 구현 지시를 별도로 작성한다.

## GitHub 기존 기준 자료
- `newsflow-ai/docs/design/studio-v3.0/prototypes/NewsFlow_Master_Experience_v2.4.html`
- `newsflow-ai/docs/design/studio-v3.0/assets/master_dashboard_reference.png`
- `newsflow-ai/docs/design/studio-v3.0/Design_Baseline_v3.0.md`
- `newsflow-ai/frontend/src/main.tsx`
- `newsflow-ai/frontend/src/studio/Workbench.tsx`
- `newsflow-ai/frontend/src/studio/workbench.css`
- `newsflow-ai/docs/design/social_platform_operations.md`

## 보고 상태
- 사용자 디자인 선택: 확인됨
- 승인 PNG 전체 원본 식별: NOT VERIFIED
- 최신 코드 실제 UX/UI 반영: NOT EXECUTED
- 제품/운영 코드 변경: NONE

## 2026-10-27 바이너리 등록 후속 상태

이번 사용자 지시에 따라 지정 문서 브랜치의 `newsflow-ai/docs/design/approved-20261027/candidate-assets/`에 후보 PNG 11개와 원본 ZIP을 등록했다. 위 읽기 전용 감사 단계의 GitHub 업로드 금지 문구는 과거 단계의 범위다. 이번 승인도 제품 구현·PR #35 변경 승인은 아니다.

후보 파일의 원격 SHA-256·크기·해상도·URL 검증은 12/12 PASS다. **승인 PNG 원본 식별은 여전히 미완료이며 11개 모두 CANDIDATE**다. 특히 뉴스 쇼츠 2차는 원본 대조가 우선 필요하다. 세부 링크와 근거는 [등록 결과 보고서](../approved-20261027/DESIGN_ASSET_UPLOAD_REPORT_20261027.md)를 참조한다. 홈·콘텐츠 제작 홈의 변경 금지는 유지한다.
