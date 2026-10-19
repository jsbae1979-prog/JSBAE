# 설정 화면 실제 탭 분리

- 기준: `6898a85` / 검증 코드: `7512498a3d8406674ea56910d76eab9966929d12`
- 기존 상단 링크는 위치 이동용이라 모든 설정이 보였음. 이제 뉴스·대본 AI / 기본 음성 / AI 영상 / 비용 / 게시 계정 / 운영 관리는 선택한 패널만 표시.
- 예약 제작은 기존 별도 화면으로 이동하는 링크로 유지.
- 하나의 기존 기본값 저장 폼 유지. 숨긴 탭의 값도 제거·비활성화하지 않아 입력 중 값과 저장값을 보존. 키·비용 승인은 기존 별도 저장/승인 경로 유지.
- 선택 탭은 해당 브라우저 세션에서 복원. 기존 `#selected-voice`, `#selected-video`, `#youtube`, `#instagram`, 비용 대화상자 등의 직접 링크는 해당 패널을 열도록 처리.
- 키보드 좌우/Home/End 및 뒤로/앞으로 이동 지원. 다른 탭의 필수 입력 검증 오류가 발생하면 해당 탭을 열어 수정 가능.
- 개발 중 기존 계정 섹션이 중첩된 카드인 점 때문에 직접 링크가 잘못된 패널을 여는 결함을 재현하고, 실제 최상위 탭 패널에 매핑하도록 수정.

## 최종 검증

Cloud Python 3.12 / Chromium, 임시 DB와 합성 키 사용. **29 passed / 0 failed / 0 skipped / 1 warning** (기존 Starlette/httpx 안내), 42.36초. Ruff PASS.

```bash
NEWSFLOW_SETTINGS_EVIDENCE=/tmp/newsflow-settings-tabs-evidence \
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m pytest -q -rs \
 tests/test_settings_streamlined_browser.py tests/test_settings_simplification.py tests/test_studio_pages.py
```

6개 탭 × 1366×768 / 1920×1080 / 390×844에서 한 패널만 표시되고 가로 넘침이 없는지 검사. 실제 저장·재진입, 제작 기본값 반영, 키 비노출/보존, 개별 비용 승인 미체크 유지, 관련 기존 링크 및 영상 화면 회귀 확인. 탐색 동작에서 POST 없음. 외부 브라우저 요청/JS 오류 0. [로그](evidence/settings-tabs/pytest.log) · [JUnit](evidence/settings-tabs/pytest.xml)

## 실제 화면

- [뉴스·대본 AI](evidence/settings-tabs/tab-connections-1366.png)
- [기본 음성](evidence/settings-tabs/tab-quality-1366.png)
- [AI 영상](evidence/settings-tabs/tab-video-settings-1366.png)
- [비용 관리](evidence/settings-tabs/tab-costs-1366.png)
- [게시 계정](evidence/settings-tabs/tab-accounts-1366.png)
- [운영 관리](evidence/settings-tabs/tab-advanced-1366.png)
- [모바일 기본 음성](evidence/settings-tabs/tab-quality-390.png)

Windows 실환경은 NOT VERIFIED. 기존 전체 회귀 57 FAIL 기록 유지; 이번 29건의 통과를 전체 PASS로 확대하지 않음. 실제 유료 API/OAuth/SNS 호출, 운영 데이터 변경, 원격 push/PR 변경/병합 없음.

원본 이미지의 실제 기능까지 구현하는 다음 범위는 [별도 검토안](reference_parity_development_scope.md)에 정리. 신규 플랫폼·성과 수집·게시 추천 개발은 아직 착수하지 않았으며 별도 범위 확인 후 진행.
