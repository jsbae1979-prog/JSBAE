# 기본 샘플 12개 권리 검토

2026-10-28 · **12개 모두 rightsVerified:false 유지 / 공개 재배포 BLOCKED**.

## 근거와 한계

- 기존 파일 무결성·재생 검사를 재사용했다. 표의 SHA-256은 승인된 기존 매니페스트/파일 감사에서 인용했으며 이번에 동일 바이너리 검사를 반복하지 않았다.
- 이번에는 PNG9개를 직접 보며 상표·캐릭터·사진 관련 표현을 검토했다. 이는 상표 검색·역이미지 검색·권리자 확인을 대체하지 않는다. 영상은 기존 슬라이드/무음 검증과 source manifest를 재사용했다.
- 사용자 첨부 ZIP의 MANIFEST.json/README.txt만 다시 읽었다. README는 기존 콜라주의 영역 추출·확대, 무음12초 예제, 배포 전 권리 확인 필요를 명시한다. 생성 대화 원본·원본 콜라주·생성 계정·입력 자산 권리·상용 재배포 허락은 없다.
- 따라서 ChatGPT 생성 출처를 파일별로 입증하지 못했다. 메타데이터 부재를 비AI 생성 증거로 해석하지 않는다. 앱의 providerGenerated:false는 실제 공급사 성공 이력으로 표시하지 않는 정책이며 원저작자에 관한 확정 증거가 아니다.
- OpenAI Docs의 [이미지 생성 안내](https://learn.chatgpt.com/docs/image-generation)는 일반적 이미지 사용을 설명한다. 그 안내 자체가 이 첨부 파일들의 생성자·입력 권리·제3자 상표 권리를 보증하지 않는다. 일반 약관을 근거로 파일별 VERIFIED를 임의 설정하지 않았다.

## 파일별 판정

| 파일 | 기존 SHA-256 | 시각·출처 검토 | 권리 |
|---|---|---|---|
| `characters/CHAR_S01_robot.png` | `6832ac0a0828d3e819fa3a4105f7a7ba12fee6cfc4143dfd9caff9b42171f5bf` | 로봇 일러스트. 특정 제품·캐릭터와의 권리관계는 시각 검사만으로 확정 불가. | NOT VERIFIED / false |
| `characters/CHAR_S02_cat.png` | `18f5702917c7908e3f65a5dc937cc01cbb36ef60549d16fc74c2bd70979fe9c8` | 고양이 일러스트. 뚜렷한 상표를 확인하지 못했으나 원본/입력 권리 미확인. | NOT VERIFIED / false |
| `characters/CHAR_S03_dragon.png` | `a22daa60e3eb9ec7f062210ae0d4dfcf553cf8c8315ef9529835484cccccefac` | 드래곤 일러스트. 제3자 캐릭터 유사성/원본 생성 이력 미확인. | NOT VERIFIED / false |
| `images/standalone/IMG_S01_city.png` | `c9608819f1b030d034af87c0f26064cead7fa2c4bf7e1b1785a21d99338369ea` | 랜드마크를 연상시키는 도시. 원본 사진·입력·건축물 표현 권리 확인 필요. | NOT VERIFIED / false |
| `images/standalone/IMG_S02_cat.png` | `462566d59e2eaac0f17edf4d11dee2433506bc47cd95e2bb4adaee74476a9acb` | 고양이 일러스트. 원본·생성 계정·이용 권리 미확인. | NOT VERIFIED / false |
| `images/standalone/IMG_S03_earth.png` | `dd781fe0c716cb746870bbc7c0309f64f62eb53d761a6e6d9d962045c2558e4a` | 지구/야경 표현. 위성사진 등 원본 사용 여부 미확인. | NOT VERIFIED / false |
| `images/news-top3/TOP3_S01_ai.png` | `e28c902251e217d53672f5858fc095986c46dc1c8b75877ffc211cddc38a1474` | AI 칩 일러스트. 명백한 공급사 로고는 확인하지 못했으나 생성 출처 미확인. | NOT VERIFIED / false |
| `images/news-top3/TOP3_S02_ev.png` | `1624c901b4108a647e7c87a602f3882edcc521be26862a0e6abbc71a1d22f341` | 차량 외관·후면 엠블럼/번호판 유사 표현. 상표·디자인 검토 우선. | NOT VERIFIED / false |
| `images/news-top3/TOP3_S03_economy.png` | `4f9aad8e4fc51052c90c9fd6e1b7a26ae270d82800c1eca673acc705e50588c6` | 예시 금융 차트. 실제 수치 아님. 차트/입력 원본 권리 미확인. | NOT VERIFIED / false |
| `videos/character-shorts/SHORTS_CHAR_S01.mp4` | `7fda267e97d574426c5d1024185aa3a28265510790b77994c527294aa11bf8b0` | 기존 무음 12초 슬라이드. 원본 로봇 이미지 권리 승계 확인 필요. | NOT VERIFIED / false |
| `videos/character-shorts/SHORTS_CHAR_S02.mp4` | `9da45f543a4ab5b7ab737fd3128d0706a7b542ddaf91da133effbc4245742189` | 기존 무음 12초 슬라이드. 원본 고양이 이미지 권리 승계 확인 필요. | NOT VERIFIED / false |
| `videos/news-shorts/SHORTS_NEWS_S01.mp4` | `3609e4c56a88d9a79df912991086bbbc1dd17945543623659085af394049f3b8` | 기존 무음 12초 슬라이드. 사용 뉴스 예시 이미지 각각의 권리 승계 확인 필요. | NOT VERIFIED / false |

## 원본·가공 이력

기존 ZIP hash: `c6a508471bdd12be4241004a6e66e5e0405146624cd213f8b5cc0c6c01a7440b`.
앱 등록 과정은 검증된 원본 PNG/MP4의 경로 재배치·매니페스트·poster 연결이며, 기존 보고서는 원본 바이트 보존을 확인했다. 그보다 앞선 콜라주 제작·추출은 ZIP README의 설명만 있으며 원본 생성 증빙이 아니다.

## 필요한 확인 자료

1. 9개 이미지에 대응되는 원본/콜라주 및 ChatGPT 생성 대화·날짜·사용자 계정 권한을 입증하는 비민감 기록. 계정 비밀번호·API 키는 제출할 자료가 아니다.
2. 참조 사진·캐릭터·상표 등의 입력 권리 및 제작자의 상업 이용·설치 패키지 재배포 허락.
3. 3개 슬라이드 영상의 사용 이미지 목록·편집 이력 및 동일 권리 적용 여부.

## 대체 계획 — 아직 교체하지 않음

증빙 확보가 어렵다면 기존 원본12개는 보존하고 별도 버전에서 자체 제작 SVG/도형·직접 촬영/권리확인 일러스트로 9개 원본을 만든다. 특정 제품·캐릭터·상표·실제 사건을 모사하지 않고 제작자·입력·라이선스·해시를 기록한다. 해당 자체 원본으로 로컬 FFmpeg 무음 샘플3개를 합성한다. 새로운 권리 검토·시각 인수 후 별도 샘플 버전을 선택하고 기존 사용자 복사본은 덮어쓰지 않는다.

이번에는 이미지 생성·유료 API·원본 교체·샘플 매니페스트 수정·일반 공개를 하지 않았다.

## 공식 약관상 권리와 이 파일들의 차이

현재 [OpenAI ROW Terms of Use](https://openai.com/policies/row-terms-of-use/)는 OpenAI와 사용자 사이에서 법이 허용하는 범위의 출력 귀속을 사용자에게 두며, 입력에 필요한 권리는 사용자가 확보해야 한다고 정한다. 다른 사용자 출력·제3자 출력까지 이전하는 것은 아니며 유사 출력이 존재할 수 있다. 이것만으로 이 ZIP의 생성자나 차량·캐릭터 등 제3자 권리가 증명되지는 않는다.

[Service Terms](https://openai.com/policies/service-terms/)는 계약 종류별 조건을 구분한다. API/Enterprise의 특정 면책도 모든 상업 이용에 대한 포괄 허가가 아니며, 입력 권리 부족·변형/조합·상표 관련 주장 등의 제외 조건이 있다. 이 샘플의 실제 생성 계정·적용 계약·생성 시점의 조건은 NOT VERIFIED다. 따라서 일반적인 출력 귀속과 이 12개의 상업적 설치 패키지 재배포 권리 판정을 분리했다. 현재 판정은 모두 false로 유지한다.
