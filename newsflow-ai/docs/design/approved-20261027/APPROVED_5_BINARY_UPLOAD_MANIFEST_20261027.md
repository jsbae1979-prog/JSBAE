# NewsFlow AI — 사용자 최종 선택 이미지 5개 전송 명세

기준: 2026-10-27 KST. 사용자 승인: 비교표 오른쪽 이미지 5개를 최종 기준으로 사용.

## 업로드할 파일
로컬 패키지: `NewsFlowAI_Approved_5_Images_20261027.zip` (9,238,814 bytes, ZIP 무결성 PASS)

대상 브랜치: `docs/newsflow-approved-design-handoff-20261027`

대상 폴더: `newsflow-ai/docs/design/approved-20261027/approved-assets/`

| 파일명 | SHA-256 |
|---|---|
| news_shorts_v2.png | 738db2ba3bfc03084758c9209679b21dcaed1436fedc8b9d2f754fb6341aaea0 |
| standalone_image_v2.png | 60f6ae67f45fd1c30b3a7cbc19d9090136b40741e18f41f82ac3addc1e706cf4 |
| top3_feed_v3.png | 4ddf7d94886312b5541dae87a949579d0cd14ef5f1e3f61eaf71b75a74348b6b |
| news_studio_v2.png | 2fe099e812fdac82c69504fe143af8db80e2d71ef921513b34d03960fe124e0f |
| settings_v2.png | 34df44fbb0c636263111430aa1f375939ac4c9b153c8332fd389a737880389cc |

## 상태
- 이 문서만 GitHub에 등록됨.
- **실제 PNG 5개와 ZIP 바이너리는 아직 GitHub에 업로드되지 않음.**
- 기존 candidate-assets는 보존. 특히 기존 top3_feed_v3.png는 잘못된 라이브러리 이미지로 매핑되었으므로 사용 금지.
- 바이트 일치한 기존 후보 6개는 유지하며, 승인된 이미지로의 승격 시 원본·승인 메시지 근거를 함께 보존.
- React/CSS/Python, PR #35, main, 운영 앱 변경 없음.

## 업로드 후 검증
원격 PNG 5개에 대해 SHA-256, 파일 크기, 해상도, GitHub URL을 확인하고 승인 매핑 문서를 갱신한다. 기존 기능 감사/전체 회귀 반복 금지.

## 최종 업로드·검증 완료 기록

최종 PNG 5개를 `4daadfc6432b9dc7c99d0a05c8167aca345c784f`의 `approved-assets/`에 등록하고 원격 SHA-256·크기·해상도·GitHub URL을 모두 확인했다. 표의 해시와 모두 일치하며 화면 유형도 확인했다. 새 TOP 3 원본은 뉴스 순위 및 이미지 결과 3개가 있는 자동 제작 화면이다.

위 '아직 업로드되지 않음'은 전송 전 상태다. **현재 PNG 5개 업로드 완료**, 새 ZIP은 로컬 원본 보존이며 이번에 원격 등록하지 않았다. 기존 후보 6개도 동일 바이트로 승인 폴더에 복사하여 전체 11개 구성을 완료했다.

[최종 승인 매니페스트](approved-assets/APPROVED_DESIGN_MANIFEST.md) · [등록 결과](APPROVED_DESIGN_REGISTRATION_REPORT_20261027.md). 제품 코드·PR #35·main·운영 앱은 변경하지 않았다.
