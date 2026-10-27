# NewsFlow AI — 최종 승인 디자인 매니페스트

기준일: 2026-10-27 KST  
문서 브랜치: `docs/newsflow-approved-design-handoff-20261027`  
승인 PNG 등록 커밋: [`4daadfc6432b9dc7c99d0a05c8167aca345c784f`](https://github.com/jsbae1979-prog/JSBAE/commit/4daadfc6432b9dc7c99d0a05c8167aca345c784f)  
**디자인 자산: VERIFIED 11/11. 실제 React 반영·제품 기능 인수·운영 전환 승인은 별도다.**

## 승인 근거와 해시 구분

- 사용자의 이번 명시적 지시: 기존 일치 후보 6개 유지, 비교표 오른쪽 최종 원본 5개 선택 및 제공한 SHA-256으로 등록.
- [최종 사용자 선택 기록](https://github.com/jsbae1979-prog/JSBAE/blob/0fc3da0578dfd3ce4af8a12994e7e7a330139fc1/newsflow-ai/docs/design/approved-20261027/FINAL_USER_SELECTION_20261027.md).
- [대화 이미지 비교 기록](https://github.com/jsbae1979-prog/JSBAE/blob/0fc3da0578dfd3ce4af8a12994e7e7a330139fc1/newsflow-ai/docs/design/approved-20261027/CONVERSATION_IMAGE_COMPARISON_20261027.md).
- [새 5개 전송 명세](https://github.com/jsbae1979-prog/JSBAE/blob/0fc3da0578dfd3ce4af8a12994e7e7a330139fc1/newsflow-ai/docs/design/approved-20261027/APPROVED_5_BINARY_UPLOAD_MANIFEST_20261027.md).
- 파일명이나 BYTE_MATCH만으로 승격한 것이 아니다. 사용자 최종 선택 근거와 각 원본의 바이트 일치를 함께 확인했다.
- 아래 SHA-256은 원본 바이트 해시다. Git blob SHA(별도 Git 객체 식별자)와 다르다. Git blob ID로 SHA-256 검사를 대체하지 않았다.
- 전체 PNG는 **1536×1024**, 원격 파일 GET·SHA-256·크기·해상도·GitHub URL 검증 **11/11 PASS**.

## 최종 PNG 11개

기본 경로: `newsflow-ai/docs/design/approved-20261027/approved-assets/`. 아래 링크는 등록 커밋으로 고정했다.

| 화면 | 승인 버전 | 최종 PNG 경로·URL | SHA-256 | 해상도 | 승인 근거 | 기존 후보와 관계 | 자산 판정 | 실제 기능 대응(기존 감사) |
|---|---|---|---|---|---|---|---|---|
| 뉴스 쇼츠 제작실 | 2차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/news_shorts_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/news_shorts_v2.png) | `738db2ba3bfc03084758c9209679b21dcaed1436fedc8b9d2f754fb6341aaea0` | 1536×1024 | 오른쪽 원본 선택 사용자 승인 + 첨부 원본/지정 해시 | 기존 candidate를 보존하고 새 승인 바이트를 별도 경로에 등록 | VERIFIED | PARTIAL |
| 캐릭터 쇼츠 제작실 | 4차 간편 | [newsflow-ai/docs/design/approved-20261027/approved-assets/character_shorts_v4.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/character_shorts_v4.png) | `f0e5154f096676ba9ac626e6c6312e6ee114ed467968e38559002a564c0350ec` | 1536×1024 | 기존 일치 6개 유지 사용자 승인 + 비교 기록 | 기존 candidate와 동일 바이트 복사 | VERIFIED | PARTIAL |
| 독립 AI 이미지 제작 | 2차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/standalone_image_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/standalone_image_v2.png) | `60f6ae67f45fd1c30b3a7cbc19d9090136b40741e18f41f82ac3addc1e706cf4` | 1536×1024 | 오른쪽 원본 선택 사용자 승인 + 첨부 원본/지정 해시 | 기존 candidate를 보존하고 새 승인 바이트를 별도 경로에 등록 | VERIFIED | PARTIAL |
| 뉴스 기반 이미지 제작 | 2차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/news_image_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/news_image_v2.png) | `c8a704d76ffa432cc5781fbf2535697899b159099820e2a487f911c50bb42398` | 1536×1024 | 기존 일치 6개 유지 사용자 승인 + 비교 기록 | 기존 candidate와 동일 바이트 복사 | VERIFIED | PARTIAL |
| TOP 3 자동 피드 | 3차 수정 | [newsflow-ai/docs/design/approved-20261027/approved-assets/top3_feed_v3.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/top3_feed_v3.png) | `4ddf7d94886312b5541dae87a949579d0cd14ef5f1e3f61eaf71b75a74348b6b` | 1536×1024 | 오른쪽 원본 선택 사용자 승인 + 첨부 원본/지정 해시 | 기존 candidate를 보존하고 새 승인 바이트를 별도 경로에 등록 | VERIFIED | PARTIAL |
| 뉴스 스튜디오 | 2차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/news_studio_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/news_studio_v2.png) | `2fe099e812fdac82c69504fe143af8db80e2d71ef921513b34d03960fe124e0f` | 1536×1024 | 오른쪽 원본 선택 사용자 승인 + 첨부 원본/지정 해시 | 기존 candidate를 보존하고 새 승인 바이트를 별도 경로에 등록 | VERIFIED | IMPLEMENTED |
| 자동화 센터 | 1차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/automation_v1.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/automation_v1.png) | `bc0dcd1e05e6d87cea78e230ebe14b05595d0b550d6496b96056b9e696b3a299` | 1536×1024 | 기존 일치 6개 유지 사용자 승인 + 비교 기록 | 기존 candidate와 동일 바이트 복사 | VERIFIED | PARTIAL |
| 라이브러리 | 2차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/library_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/library_v2.png) | `019422eca6db623e0483a2865730347397b5badc95619895606d37727a87e36a` | 1536×1024 | 기존 일치 6개 유지 사용자 승인 + 비교 기록 | 기존 candidate와 동일 바이트 복사 | VERIFIED | PARTIAL |
| 게시 스튜디오 | 4차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/publishing_v4.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/publishing_v4.png) | `cd25bfa116fe1013646bad0a590512f06cd3f7326e0c5cb6a8b9071b2166e4a8` | 1536×1024 | 기존 일치 6개 유지 사용자 승인 + 비교 기록 | 기존 candidate와 동일 바이트 복사 | VERIFIED | PARTIAL |
| 성과·비용 | 4차 두 번째 | [newsflow-ai/docs/design/approved-20261027/approved-assets/analytics_v4_option2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/analytics_v4_option2.png) | `e3cf05889a6409b01b0c912972fd1697cd0fbba904cbd8ed1bc734993477ccb3` | 1536×1024 | 기존 일치 6개 유지 사용자 승인 + 비교 기록 | 기존 candidate와 동일 바이트 복사 | VERIFIED | PARTIAL |
| 설정·관리 | 2차 | [newsflow-ai/docs/design/approved-20261027/approved-assets/settings_v2.png](https://github.com/jsbae1979-prog/JSBAE/blob/4daadfc6432b9dc7c99d0a05c8167aca345c784f/newsflow-ai/docs/design/approved-20261027/approved-assets/settings_v2.png) | `34df44fbb0c636263111430aa1f375939ac4c9b153c8332fd389a737880389cc` | 1536×1024 | 오른쪽 원본 선택 사용자 승인 + 첨부 원본/지정 해시 | 기존 candidate를 보존하고 새 승인 바이트를 별도 경로에 등록 | VERIFIED | PARTIAL |

## 구현 계획의 자산 경로 보완 및 실제 기능 대응 상태

기존 로컬 감사 4개 보고서의 내용은 변경하지 않고 그대로 재사용한다. 특히 `UI_IMPLEMENTATION_PLAN.md`의 기존 화면별 범위에 아래 승인 경로를 대응시키는 **자산 경로 보완**만 수행했다. 기능 감사·회귀·코드 실행은 반복하지 않았다. 기존 기능 근거 SHA는 `75626f74cc1bfe750d24132e44019bcda478247b`다.

| 화면 | 기존 구현 계획 대상 | 사용할 승인 PNG | 실제 기능 대응 및 제약(기존 감사 재사용) |
|---|---|---|---|
| 뉴스 쇼츠 제작실 | Workbench.tsx · shorts | `approved-assets/news_shorts_v2.png` | PARTIAL: 기사·대본·장면·음성·MP4 경로 존재; 실계정 제작·새 디자인 미검증 |
| 캐릭터 쇼츠 제작실 | Workbench.tsx · characters | `approved-assets/character_shorts_v4.png` | PARTIAL: 참조 PNG·Claude·Seedance·견적/승인·FFmpeg 경로 존재; 무인 전 과정/다중 캐릭터 관리 미지원 |
| 독립 AI 이미지 제작 | Workbench.tsx · images/independent | `approved-assets/standalone_image_v2.png` | PARTIAL: 초안·모델·미리보기·재사용 존재; 참조 기반 유료 이미지 편집 미지원 |
| 뉴스 기반 이미지 제작 | Workbench.tsx · images/news | `approved-assets/news_image_v2.png` | PARTIAL: 기사·문구·출처·단일 이미지 검토 존재; 실제 HTTPS 전달/게시 미검증 |
| TOP 3 자동 피드 | TopThreeFeeds.tsx · images/top3 | `approved-assets/top3_feed_v3.png` | PARTIAL: 고정 분석·독립 3개 결과/상태·Fake 배치 존재; 실제 유료 배치 견적/계정 권한 미연결 |
| 뉴스 스튜디오 | Workbench.tsx · news | `approved-assets/news_studio_v2.png` | IMPLEMENTED: 검색·수집·출처·분석 연결 존재; 실계정 검색/분석 성공 및 새 디자인 미검증 |
| 자동화 센터 | Workbench.tsx · automation | `approved-assets/automation_v1.png` | PARTIAL: 예약 저장/활성화·정지·기록 존재; 모든 제작의 무인 자동화는 미지원 |
| 라이브러리 | Workbench.tsx · library | `approved-assets/library_v2.png` | PARTIAL: 검색·필터·미리보기·복원 경로 존재; 유형별 휴지통 의미/선택 ID 재진입 제약 유지 |
| 게시 스튜디오 | Workbench.tsx · publishing | `approved-assets/publishing_v4.png` | PARTIAL: 플랫폼 구분·검토·승인·상태 존재; TikTok/Facebook 실전송 차단 |
| 성과·비용 | Workbench.tsx · analytics | `approved-assets/analytics_v4_option2.png` | PARTIAL: AI 사용량/지표 경로 존재; React 계정/기간 투영 일부 부족, 실제 성과 수집 차단 |
| 설정·관리 | Workbench.tsx · settings/onboarding | `approved-assets/settings_v2.png` | PARTIAL: 모델·키·기본값·7단계 가이드 존재; 승인 탭/계정 목록 디자인 미반영 |

IMPLEMENTED는 코드상 기능·연결이 있다는 기존 정적 감사 판정이며 실제 공급사 성공을 의미하지 않는다. PARTIAL에는 미지원·미검증 제약이 포함된다. 모든 화면의 **새 승인 디자인 실제 반영은 NOT EXECUTED**, 새 UI/Windows DPI/실계정 제작·게시는 **NOT VERIFIED**다. 가상 모델·계정·비용·장면 수·성공 수치를 현재 제품 계약으로 자동 채택하지 않는다. 유료 승인·게시 검토/승인·결과 불명 재요청 차단·DPAPI 보호는 유지한다.

## TOP 3 매핑 정정

- 기존 `candidate-assets/top3_feed_v3.png`는 라이브러리 화면으로 확인되었으므로 TOP 3 구현 기준에서 영구 제외한다. 파일은 보존한다.
- 최종 `approved-assets/top3_feed_v3.png`는 뉴스 1·2·3위 선택, 공통 이미지 설정, TOP 3 생성 버튼 및 이미지 결과 3개가 있는 **뉴스 TOP 3 자동 이미지 제작 화면**이다.
- 최종 SHA-256: `4ddf7d94886312b5541dae87a949579d0cd14ef5f1e3f61eaf71b75a74348b6b`.
- 다른 라이브러리 승인 원본 `library_v2.png`와 혼합하거나 후보 파일명을 바꾸지 않는다.

## 보존 및 구현 승인 경계

홈·콘텐츠 제작 홈은 기존 화면 유지이므로 신규 PNG 목록에 추가하지 않는다. 두 화면의 JSX/CSS/공통 스타일·메뉴·동선 직접·간접 변경 금지를 유지한다.

기존 후보 PNG 11개와 원본 ZIP, 기존 감사 4개 보고서, 제품 코드·PR #35·main·운영 브랜치·운영 앱·DB·키·설정·미디어·백업은 변경하지 않았다. 이번 작업은 지정 문서 브랜치의 승인 자산과 인수 문서에 한정한다.

**기존 디자인 원본 미확보·매핑 차단 항목은 해소되었다.** 기존 기능 감사의 PARTIAL/UNSUPPORTED/NOT VERIFIED 항목을 해소했다는 뜻은 아니다. 자산 기준으로 후속 React 구현을 준비할 수 있으며, **실제 구현은 다음 별도 지시 후에만 시작한다.**
