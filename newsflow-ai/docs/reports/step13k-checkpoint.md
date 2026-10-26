# Step 13K 개발 체크포인트

- 기준: 6c2c32f8d67e37459aef3f3f6388abf4e86e9d74
- 브랜치: codex/newsflow-step13k-models-20261026
- Windows Python 3.14.7 / PR #35 Draft 유지 / 운영 적용 없음.
- 독립 이미지 초안, 이미지 모델·해상도·품질 고정, 기존 OpenAI generations Adapter 재사용.
- 캐릭터 대본 모델·Seedance 참조 계약 고정, 새 작업의 사용자 저장 Higgsfield 키 사용. 기존 HF_KEY 작업 보존.
- 뉴스 전체 AI 계획의 다음 작업용 모델 기본값 분리. 기존 뉴스·음성·FFmpeg/Higgsfield 엔진 재사용.
- 모드별 기본값은 기존 AppSetting에 별도 저장. 스키마 변경 없음.
- 로컬 생성 이미지 검토 후 뉴스 자산·캐릭터 참조에 재사용. 임의 URL·파일 경로 입력 없음.
- 실제 유료 호출·인증·게시 없음. 전체 회귀와 Windows Actions는 최종 보고서에서 결과 확인 필요.

## 명시적 제한

참조 이미지의 로컬 첨부·보관·재사용은 구현됐으나 OpenAI image edits 연결은 별도 API 계약이므로 미구현이다. 참조가 첨부된 초안의 유료 생성은 거부한다. 캐릭터는 기존 Seedance 2.0 reference-to-video의 720p/9:16/4~10초 하위 계약만 사용한다. Wan/Kling의 캐릭터 참조 입력은 추가하지 않는다. Claude 외 캐릭터 대본 Provider는 기존 Writer와 호환되지 않아 추가하지 않는다.

모델 목록은 공식 계약상 후보이며 실계정 사용 가능성을 인증하지 않는다. 비용은 확인되지 않은 총액을 추측하지 않고 미확정으로 표시한다. 기존 공식 견적·사용량·청구액 구분을 보존한다. 캐릭터 선택 모델과 기존 API 인증 확인 모델이 다르면 기존 승인·인증 gate에서 거부될 수 있으며 무단으로 공통 설정을 바꾸지 않는다.

## 공식 계약 근거 (2026-10-26 확인)

- OpenAI generations: https://developers.openai.com/api/reference/resources/images/methods/generate
- OpenAI 이미지 가이드: https://developers.openai.com/api/docs/guides/image-generation
- Wan 3.0: https://open.higgsfield.ai/models/alibaba/wan-3.0/text-to-video/api-reference
- Kling 3.0 Turbo: https://open.higgsfield.ai/models/kling-video/v3.0-turbo/text-to-video/api-reference
- Seedance 참조: https://open.higgsfield.ai/models/bytedance/seedance-2.0/reference-to-video/api-reference

## 재개

이 브랜치의 최신 커밋과 최종 검증 보고서를 확인한다. 개발용 합성 프로필에서만 tools/validation/step13k/prepare_windows.py 및 해당 Windows workflow를 사용한다. 이전 실패 증거를 삭제하지 않는다. 운영 앱·DB·ledger·백업은 입력으로 사용하지 않는다. Step 14/15~18과 실제 API 호출은 별도 승인 대상이다.
