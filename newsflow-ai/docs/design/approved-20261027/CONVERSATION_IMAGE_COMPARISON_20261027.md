# NewsFlow AI — 대화 생성 이미지와 GitHub 후보 이미지 대조 (2026-10-27)

상태: **PARTIAL PROVENANCE MATCH / NOT FINAL APPROVAL**.

현재 대화 작업 공간에 남아 있는 이미지 생성 결과 PNG와 GitHub `candidate-assets`의 동일 이름 후보 파일을 바이트 단위로 비교했다. 다음 6개는 파일 바이트가 일치한다.

| 대상 | 대화 생성 이미지 파일명 | 비교 |
|---|---|---|
| 캐릭터 쇼츠 4차 | `a_polished_dark_neon_ui_mockup_for_a_newsflow_ai.png` | BYTE_MATCH |
| 뉴스 기반 이미지 2차 | `a_widescreen_ui_dashboard_screenshot_in_a_dark_neo.png` | BYTE_MATCH |
| 자동화 센터 1차 | `wide_detailed_screenshot_of_a_dark_futuristic_ui.png` | BYTE_MATCH |
| 라이브러리 2차 | `a_detailed_ui_screenshot_mockup_of_a_dark_mode.png` | BYTE_MATCH |
| 게시 스튜디오 4차 | `a_wide_high_resolution_dark_neon_cyber_ui_dashbo.png` | BYTE_MATCH |
| 성과·비용 4차 두 번째 | `a_wide_detailed_ui_dashboard_screenshot_in_a_dark.png` | BYTE_MATCH |

다음 5개는 현재 후보와 추적한 대화 이미지 파일이 서로 다르다.

| 대상 | 대화 생성 이미지 파일명 | 비교 |
|---|---|---|
| 뉴스 쇼츠 2차 | `a_detailed_ui_mockup_screenshot_a_dark_neon_glas.png` | DIFFERENT |
| 독립 AI 이미지 2차 | `a_detailed_clean_ultra_modern_dark_themed_ui_scr.png` | DIFFERENT |
| TOP 3 자동 피드 3차 | `a_detailed_ui_screenshot_digital_dashboard_scene.png` | DIFFERENT |
| 뉴스 스튜디오 2차 | `a_detailed_ui_mockup_screenshot_of_a_dark_themed_d.png` | DIFFERENT |
| 설정·관리 2차 | `a_wide_high_resolution_dark_ui_dashboard_screensh.png` | DIFFERENT |

**주의:** 비교에 사용한 대화 이미지 파일명은 대화에 남아 있는 생성 이미지와 화면 내용을 바탕으로 추적한 것으로, 최종 승인 원본 식별의 독립 증명은 아니다. BYTE_MATCH를 곧바로 VERIFIED로 승격하지 않는다.

**TOP 3:** 후보 `top3_feed_v3.png`가 라이브러리 화면으로 잘못 연결된 점은 기존 Codex 보고와 일치한다. 후보를 삭제하거나 덮어쓰지 않는다.

## 다음 조치
1. 6개 BYTE_MATCH 대상은 해당 이미지 생성 직후의 사용자 승인 메시지와 연결하여 승인 근거를 확인한다.
2. 5개 DIFFERENT 대상은 대화 생성 이미지와 기존 후보를 나란히 제시하고 사용자 승인 버전을 확정한다.
3. 정확한 원본 PNG만 `approved-assets`에 별도 등록한다. 후보 파일은 보존한다.
4. 기능 감사·회귀·운영 코드/PR #35 변경은 하지 않는다.
