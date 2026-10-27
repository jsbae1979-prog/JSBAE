# NewsFlow AI — 승인 시안 후보 PNG 등록 대장 (후보 바이너리 등록 완료)

기준: 2026-10-27 KST. 상태: **CANDIDATE BINARIES UPLOADED / REMOTE INTEGRITY VERIFIED / APPROVAL IDENTITY PENDING**.

이 표는 로컬 인수 패키지의 파일명·SHA-256을 기록한 목록이며, 후속 사용자 승인으로 실제 PNG 11개와 ZIP 원본도 지정 후보 폴더에 등록했다. 원격 바이트 대조는 12/12 PASS다. **사용자 승인 이미지와 1:1 식별은 아직 미검증**이며, 특히 뉴스 쇼츠 2차는 추가 대조가 필요하다.

| 시안 후보 | 파일명 | SHA-256 |
|---|---|---|
| 뉴스 쇼츠 2차 (식별 미완료) | news_shorts_v2.png | 7413c4f3228174bdc69ee9e8fdaafa581a38b12200dd2b01e21533476d31f79a |
| 캐릭터 쇼츠 4차 | character_shorts_v4.png | f0e5154f096676ba9ac626e6c6312e6ee114ed467968e38559002a564c0350ec |
| 독립 이미지 2차 | standalone_image_v2.png | a840c068a0d51dcbdf28bde6c08a42f327a09bf62d159edd79ce8598b73b8f2a |
| 뉴스 이미지 2차 | news_image_v2.png | c8a704d76ffa432cc5781fbf2535697899b159099820e2a487f911c50bb42398 |
| TOP 3 3차 | top3_feed_v3.png | 0a55c9380d1d4823f362d010f4780d1d910850b8fd8cb937bd37e141f16aca5a |
| 뉴스 스튜디오 2차 | news_studio_v2.png | abb03c0173d09b6ffbe0248c1a7d2d159c9c78a2b5d464cf0a500ca20b1d0b63 |
| 자동화 1차 | automation_v1.png | bc0dcd1e05e6d87cea78e230ebe14b05595d0b550d6496b96056b9e696b3a299 |
| 라이브러리 2차 | library_v2.png | 019422eca6db623e0483a2865730347397b5badc95619895606d37727a87e36a |
| 게시 4차 | publishing_v4.png | cd25bfa116fe1013646bad0a590512f06cd3f7326e0c5cb6a8b9071b2166e4a8 |
| 성과·비용 4차 두 번째 | analytics_v4_option2.png | e3cf05889a6409b01b0c912972fd1697cd0fbba904cbd8ed1bc734993477ccb3 |
| 설정 2차 | settings_v2.png | d2f03e521a004ba5faad0a5b3486851ad51d2bd4cbd5cf6ff9fe816d786c0e82 |

모두 후보 이미지 해상도 1536×1024. 사용자 승인 버전의 최종 원본 판정은 별도.

## 안전한 등록 절차
1. Codex PC에서 로컬 인수 ZIP의 `newsflow_handoff/approved_mockups/`를 확인한다.
2. 각 PNG의 SHA-256을 이 표와 비교하고, 승인 메시지의 실제 시안과 육안 대조한다.
3. 미확인 시안은 승인 확정 폴더가 아닌 `candidate-assets/`에만 등록한다.
4. 등록한 PNG의 GitHub URL과 원격 blob SHA를 확인한다.
5. ZIP은 후보임을 명시하여 별도 등록하거나 Release asset으로 제공한다.
6. 운영 코드·PR #35·main·사용자 DB/키는 변경하지 않는다.

현재 문서 브랜치는 Codex의 진행 중인 읽기 전용 감사와 독립적이다.

## 실제 등록 결과

바이너리 커밋: `a4a4fee713439cd7b9436d96ee10bf4a0646dd74`. 모든 PNG는 1536×1024이며 표의 SHA-256과 로컬·원격 모두 일치했다. 원본 ZIP SHA-256: `8e13a2fc686051729a50e41c2eca69916f3cfb61b6d9e9f82f3562dab0cd366e`.

**11개 모두 CANDIDATE이며 승인 원본 VERIFIED가 아니다.** 개별 GitHub 링크·바이트 수·확인 방법은 [통합 등록 보고서](../approved-20261027/DESIGN_ASSET_UPLOAD_REPORT_20261027.md)에 기록했다. 승인 원본 판정이나 React 구현은 수행하지 않았다.
