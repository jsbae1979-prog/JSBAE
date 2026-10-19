# 생성 이미지 적용 — 2026-10-19 KST

검증 코드: `ee9b4ce80dc671189639e7793346075608b09d20`.
시작 코드: `75339b3`. 브랜치 `codex/newsflow-ux-video-app`의 로컬 작업만 수행했다.

사용자의 이미지 생성·적용 요청에 따라 디자인용 이미지 생성 도구를 **1회** 사용했다. 입체적인 지구, 도시 불빛과 파란 네트워크 빛을 표현한 2172×724 PNG(약 2.3 MiB)를 생성했다. 이 이미지는 장식이며 실제 뉴스 사진·현재 지구 관측·서비스 연결 상태를 나타내지 않는다.

- 생성 원본은 `/workspace/generated_images/exec-6875b320-80a7-4c96-8473-62fa5a451498.png`에 보존했다.
- 앱에는 `src/newsflow/static/images/newsflow-earth-generated.png`로 복사했다. 이전 단순 SVG는 참조가 없음을 확인하고 제거했다.
- 홈 배너와 사이드바에 같은 로컬 이미지를 사용한다. 제목·버튼·선택란은 실제 HTML이며 이미지에 합쳐 넣지 않았다.
- CSS의 이미지 배치와 문구 뒤 명암을 조정했다. 외부 이미지 URL·CDN·새 패키지·엔진·DB 변경 없음.
- 앱은 이미지 파일을 로컬로 제공한다. 이번 디자인 이미지 생성과 제품의 유료 뉴스·음성·영상 API 실행은 별개이며, 제품의 실공급사 API·OAuth·SNS 실행은 0건이다.

## 검증

최종 코드에서 Cloud Chromium 실제 브라우저 테스트:

```bash
NEWSFLOW_TEST_BROWSER_EXECUTABLE=/usr/bin/chromium \
NEWSFLOW_BLUE_STUDIO_EVIDENCE=/tmp/newsflow-generated-art/browser \
.venv/bin/python -m pytest -q -rs tests/test_blue_studio_browser.py \
 --junitxml=/tmp/newsflow-generated-art/browser.xml
```

**4 passed / 0 failed / 0 skipped**, 22.60초. 기존 Starlette/httpx deprecation warning 1건. [로그](evidence/generated-earth/browser.log), [JUnit](evidence/generated-earth/browser.xml).

1366×768 / 1920×1080 / 390×844에서 빈 화면·합성 기록, 제작 선택값, 키보드 이동, 보관 기사 검색, 장면 선택·편집, 무음 MP4 재생과 게시 준비 경계를 검증했다. 추가 홈·제작·설정 GET 9개는 HTTP 200 / 가로 넘침 없음 / 외부 브라우저 요청 0건이었다. [레이아웃 기록](evidence/generated-earth/layout.json).

이미지 로딩과 크롭, 데스크톱·모바일 문구 가독성은 실제 캡처로 확인했다. 전체 접근성 인증이나 Windows 배율·실제 음질 검증을 의미하지 않는다.

- [데스크톱 1366](evidence/generated-earth/home-1366.png)
- [데스크톱 1920](evidence/generated-earth/home-1920.png)
- [모바일 390](evidence/generated-earth/home-390.png)

앞선 변경 범위 130 PASS는 이전 `f7a25a2` 코드 결과다. 이번 이미지 교체에 동일한 범위 전체를 반복하지 않았다. 기존 전체 회귀 57 FAIL과 별도 기존 UI 실패 기록은 유지한다. 전체 PASS로 보고하지 않는다. Windows PC, Windows Actions, 실제 AI·음성·영상 품질, OAuth·SNS 실게시: **NOT VERIFIED**.

운영 데이터·키·설정·기존 영상은 사용하지 않았다. 격리된 합성 데이터 및 테스트 서버만 사용했다. 원격 push·PR 수정·main 병합·운영 반영 없음. 검증용 서버 종료 후 작업을 마친다.
