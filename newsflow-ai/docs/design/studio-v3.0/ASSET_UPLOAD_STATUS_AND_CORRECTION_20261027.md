# NewsFlow AI — PNG 등록 정정 및 실제 업로드 게이트

2026-10-27 KST

## 중요 정정
기존 `CANDIDATE_PNG_MANIFEST_20261027.md`의 11개 SHA-256은 **로컬 후보 파일**의 값이며, GitHub에 해당 PNG가 업로드되었다는 증거가 아닙니다.

기존 패키지에서 `news_shorts_v2.png`로 표기된 파일의 원본명은 `a_wide_high_resolution_ui_mockup_screenshot_of_a.png`입니다. 이 이미지는 **뉴스 쇼츠 2차 시안 원본이라고 확정할 수 없으므로**, 파일명을 근거로 승인 처리하면 안 됩니다. `ASSET_NOT_VERIFIED`로 분류합니다.

다른 10개 PNG 역시 사용자가 승인한 시안과 1:1 대조한 기록이 없어 **후보**입니다. GitHub의 승인 원본 디렉터리에 넣지 마세요.

## 업로드 현황
- 승인 결정 문서: GitHub 등록 완료
- 후보 PNG 파일명 및 해시 문서: GitHub 등록 완료
- 실제 PNG 바이너리: GitHub 업로드 미완료
- ZIP 바이너리: GitHub 업로드 미완료
- 원본 승인 대조: 미완료

## Codex 현재 감사와의 관계
진행 중인 읽기 전용 기능 감사는 중단하거나 다시 시작하지 않습니다. 감사 보고서에서 디자인 파일의 `ASSET_NOT_AVAILABLE` 또는 `ASSET_NOT_VERIFIED`를 구분합니다.

## 향후 실제 파일 업로드
1. 로컬 ZIP 파일을 접근할 수 있는 PC에서 열어 11개 PNG가 들어 있는지 확인합니다.
2. 승인 메시지와 개별 이미지 원본을 육안 대조합니다.
3. 원본 미확정 이미지는 `candidate-assets/`로, 확인된 이미지만 `approved-assets/`로 등록합니다.
4. 바이너리 업로드 후 GitHub 실제 blob URL과 SHA-256을 재확인합니다.
5. 사용자 승인 전 운영 코드·PR #35·main은 변경하지 않습니다.

이 문서는 구현 승인이나 코드 수정 지시가 아닙니다.
