# NewsFlow AI — PR #35 UX/UI 검증 자료

최종 실행 코드 SHA: `dbd4ba446c3f13705ac207a37cddbdd5339e6baa`.

**[최종 검증 보고서](ux_video_app_final_validation.md)**에서 전체 회귀 수치, 동일 조건의 기준 비교, 정확한 실패 ID, UI 및 Cloud 브라우저 결과를 확인하세요. 전체 회귀에 실패가 남아 있으므로 전체 PASS가 아닙니다.

[전후 화면 비교 HTML](ux_video_app_review.html) · [스크린샷·상세 보고서·증거 ZIP](ux_video_app_review.zip) · [최종 실패 ID 비교](evidence/ux-video-app/final-validation/regression-comparison.json).

이전 `42d1717`의 전체 회귀와 후속 `e401d9e`의 UI 전용 검사는 **최종 코드 전체 회귀가 아닌 역사 자료**입니다. 당시 서로 다른 Chrome/Chromium 조건의 비교로 신규 실패 없음이 확정됐다는 해석을 철회하고, 이번 동일 조건 비교로 대체합니다. 기존 보고서는 [원래 커밋의 역사 보고서](https://github.com/jsbae1979-prog/JSBAE/blob/0813490056ea9001ac1f528397cb01acb22d397d/newsflow-ai/docs/reports/ux_video_app_report.md)에 보존되어 있습니다. 이전 `after/`와 이전 회귀 JSON도 역사 자료이며 최종 판정에는 `final-validation/`만 사용합니다.

Windows 사용자 PC, 실제 음성·자막 싱크·API 콘텐츠 품질·OAuth·SNS 게시 성공은 NOT VERIFIED입니다. 실제 유료 API/OAuth/SNS 실행은 하지 않았습니다. 기존 Draft PR #35를 유지하며 추가 기능 개발·main 병합은 하지 않습니다.
