# 완성형 뉴스 피드와 설정 예산 재사용 (2026-11-03)

## 결과
새 스타일 `AI 완성 피드 · 한글·디자인 함께 생성`은 이미지 모델이 한글 제목, 핵심 설명, 강조색, 그림과 배치를 함께 생성한다. 생성 후 로컬 글자를 덧씌우지 않는다. 기존 `사진 중심 피드 · 무료 글자 편집` 및 기존 카드·작업·결과는 유지한다.

완성형 편집은 제목·설명·강조색을 입력하고 **AI 수정 · 설정 예산 사용**을 눌러 기존 완성 이미지를 참조하는 Images edits 요청을 준비/실행하는 구조이다. 출력은 새 파일·버전이며 이전 버전은 조회·다운로드할 수 있다. 픽셀에 포함된 글자를 무료 레이어 편집이라고 표시하지 않는다. 입력값을 바꾸거나 화면을 여는 것만으로 API가 호출되지 않는다. 실제 편집 품질/배경 보존 정도는 공급사 결과 검토가 필요하다.

설정의 OpenAI `사용 승인 + 1회 실행 한도`를 재사용한다. 버튼을 누를 때 서버가 새 요청 범위, 계정, 모델, 예상 비용과 기존 보류액을 확인한다. 별도 작업별 예산 입력·반복 승인 팝업 없이 저장된 한도 안에서 진행한다. 미설정·승인 철회·예산 초과·결과 불명·동시 요청은 계속 차단한다. 승인·요금은 공급사 강제 청구 상한이 아닌 앱 예산이다. 사용자 설정 값은 이 작업에서 변경하지 않았다.

## 구현
- `creation/complete_feed.py`: 완성형 프롬프트, 수정 초안, 원본 해시 확인, 메타데이터 없는 참조 PNG.
- `creation/top_three_feeds.py`, `gui/creation_routes.py`: 새 스타일/명시적 수정, 이전 버전 조회. 기존 POST 경로를 재사용한다.
- `creation/feed_readiness.py`, `feed_budget.py`, `feed_costs.py`: 저장된 승인·한도, 요청/참조 해시, 보류액·실패·불명 처리 유지.
- `tools/bat_distribution/feed_image_access.py`, `operation.py`: 정확한 `design_edit` 동작과 서버에서 고정한 원본만 허용. 임의 참조 파일·비인증 키 접근을 허용하지 않는다.
- `CompleteFeedEditor.tsx`, `TopThreeImageStudio.tsx`, `TopThreeFeeds.tsx`, `FeedCostReview.tsx`: 완성형 편집 화면과 설정 예산 실행.
- `feed_art_direction.py`, `feed_designs.py`, `photo_feed.py`, `PhotoFeedEditor.tsx`: 앞선 무료 편집 작업 유지. 기사별 구성 정보·원본·편집 값을 분리하며, 변수 글꼴 Thin 기본값 대신 새 편집의 제목 Bold/본문 Regular를 선택한다. 기존 글꼴 배치는 변경하지 않는다.

## 시안 확인
Codex 내장 이미지 도구로 `우주에 / 고양이가 있다?` 제목, `별빛과 가스가 빚은 모양, / 상상력을 자극하는 우주의 풍경` 설명, 주황색 강조를 포함한 4:5 피드 시안 1장을 생성하고 채팅에 표시했다. 실제 뉴스 사진이나 출판용 검증 결과가 아닌 `디자인 시안 · AI 일러스트`이다. NewsFlow 키/API는 사용하지 않았다. 생성 이미지는 로컬 `feed_director_20261103/complete-design-demo.png`에 보존했으며 운영 데이터/샘플에는 등록하지 않았다.

핵심 생성 지시: 하나의 고양이 형태 성운 일러스트가 대부분을 차지하고, 하단의 어두운 그라데이션 위에 정확한 한글 제목·설명을 큰 활자로 배치한다. 고양이 단어만 주황색으로 강조한다. 실제 관측·발견·날짜 주장을 추가하지 않고 장식 UI·번호·콜라주를 넣지 않는다.

## 검증
- Python 집중 검사 중복 제외 **218 PASS**, 화면 실행 함수 계약 **53 PASS**, **0 FAIL / 0 ERROR / 0 SKIP**.
- React typecheck/build 성공. 전체 Python 회귀를 반복하지 않았다.
- Fake로 완성형 3장 생성 → 한 결과 문구/색상 수정 → 이전 파일·다른 두 결과 보존 → 이전 버전 HTTP 조회를 확인했다.
- 화면 열기/수정 준비는 호출 0회. 명시적 생성은 대기 항목당 1회, 명시적 편집은 1회. 결과 불명 시 다음 장·재시도 없음.
- 설정 승인 철회, 0/부족 예산, 동의 없음, 검토 없음, 원본 변조, 예산 거부 시 전송 차단.
- 실행 명령: `python run.py full tests/test_complete_feed.py tests/test_feed_art_direction.py tests/test_photo_feed_editor.py tests/test_feed_budget.py tests/test_feed_costs.py tests/test_feed_new_background.py tests/test_feed_recovery_improvements.py tests/test_insta_feed_safety.py tests/test_top_three_selection.py`; 변경 후 `run.py followup tests/test_complete_feed.py`; `tools/studio_v3/tests`와 `tools/feed_top3/tests` 직접 실행; `node --test tests/*.test.mjs`; `tsc --noEmit`; `vite build --configLoader runner`.
- 독립 프런트엔드 빌드에는 기존 미커밋 Analytics 변경을 포함하지 않았다. 기존 topics/character_automation_routes 변경도 이번 커밋·운영 반영에서 제외했다.

## 과금/실제 검증 한계
공식 문서: [이미지 생성·편집](https://developers.openai.com/api/docs/guides/image-generation), [Flare 단가](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare). 이미지 입력 $8/백만 토큰, 텍스트 입력 $5/백만, 출력 $30/백만 기준. 편집 참조 입력은 앱의 16px 패치 추정과 여유분을 사용한다(공식 토큰화 방식·청구 상한을 보장하지 않는다). 기존 응답 저장 형식에는 입력 종류별 토큰이 없으므로 편집 입력은 높은 단가로 보수적으로 계산하며 실제 청구 확정으로 표시하지 않는다.

유료 NewsFlow 생성·편집, 뉴스 수집/분석, SNS, 업로드는 수행하지 않았다. 여기서 생성한 Codex 시안의 품질이 운영 API 결과와 동일하다는 보장은 없다. 실제 Chrome 화면과 운영 API의 한글 정확도·수정 품질은 별도 사용자 확인 대상이다. 운영 반영·보존 결과는 `operating-result.json`에서 분리 보고한다.

## 운영 반영
- 제품 코드 `816e95a4916530c37bec712f9f672a05f44b33a4`의 정확한 프로그램/정적 자산 13개만 반영. 정상 Stop·Start 각 1회.
- 포트 18768, 시작 PID 43504. Chrome 자동 열기 요청 수락. 사용자는 화면 확인을 나중으로 미룸: GUI 육안 확인은 미검증.
- DB 모든 테이블 논리 내용, 기타 프로필 파일(키·미디어 포함), 원본·백업 A/B 해시 보존. launch 설정 불변. 세션·브라우저 시작 기록만 정상 갱신.
- 수정 프로그램 파일과 SQLite 일관성 백업을 비공개 복구 폴더에 보존. 기존 결과/이미지는 덮어쓰지 않았다.
- NewsFlow 실제 유료 호출 0, SNS 0. 생성 시안 1개는 Codex 내장 도구로만 생성.
