# NewsFlow AI 최종 제작·단일 피드 통합

기준: `3c5230942466a87e5bc191961538e9bbccddc90b`, `codex/newsflow-ux-video-app`, 기존 [Draft PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35). 기존 A·B·C 및 production_choices 보고서는 보존한다. 이번 구현은 별도 Windows 소스 복사본에서 수행했으며 Codex Cloud에서 실행했다고 표시하지 않는다. 운영 적용·재시작은 하지 않았다.

## 구현 범위

| 항목 | 최종 동작 |
|---|---|
| 재사용 | RSS/AI 웹 검색, 선택 Provider의 IntelligenceService, Autopilot, 대본 검토, TTS, FFmpeg, Higgsfield worker·클립 보관·관계 검토·합성 승인, YouTube/Reels 공식 어댑터·OAuth·게시 기록 재사용 |
| 기본 영상 | 기존 카드·이미지·자막 + FFmpeg. Higgsfield 호출 0회. 로컬 음성 또는 별도 동의를 받은 ElevenLabs. 30/45/60초 유지 |
| 전체 AI 영상 | 작업실의 AI 영상은 전체 장면을 같은 등록 모델·공통 스타일로 계획. 장면 수·프롬프트·모델을 보고 일괄 유료 생성 승인. 모든 장면에 검토한 클립이 있어야 합성하며 카드로 자동 대체하지 않음 |
| 음성 결합 | 기본/전체 AI × 로컬/ElevenLabs 네 조합 연결. 새 계획에 음성·모델·외부 음성 동의·발화 설정을 고정. 기존 WAV·문장 타이밍과 클립 재사용. ElevenLabs는 캐시가 없는 내레이션별 최대 1회 생성, 계정 이용 조건 조회는 별도 GET |
| 길이 불일치 | API 대본·ElevenLabs·신규 전체 AI 합성은 기존 엄격한 오디오 길이 검사를 사용. 분량 부족/초과 시 보존하고 검토로 돌림. 자동 축약·가속·음성 교체·추가 유료 요청 없음 |
| 대본 검토 | 기존 기본 체크 유지. 새 전체 AI 계획은 화면에 대본을 표시하고 생성 승인에 해당 수정본 확인을 기록. 해제한 새 작업만 기존 구조·출처·수치·비밀정보·검토 메모 검사를 통과해야 진행. 사실 검증 완료나 공개 게시 승인으로 바꾸지 않음 |
| Autopilot 연결 | AI 장면 승인을 기다리는 상태로 유지. 합성 완료 전 진행 버튼 비활성·서버에서도 422. 같은 대본 수정·길이·제작 선택의 완성 MP4만 기존 최종 영상 검토·게시 초안 흐름에 재사용 |
| Instagram 기본 피드 | 기사/저장 대본 원고, 제목·핵심 내용·출처를 프로그램에서 정확히 렌더링한 1080×1350 JPG 1장. OpenAI 이미지 호출 0회. 계정 없이 저장·미리보기·다운로드 가능 |
| OpenAI 피드 | 뉴스 분석 Provider와 독립된 명시적 선택·동의. 기존 Image API 어댑터로 주제 배경 1장 생성 → 프로그램의 한글·숫자·출처 렌더링. `gpt-image-2.5-flare-2026-09-08`, 1024×1280, medium JPEG 계약 재사용. 원고 생성 API나 Claude 이미지 생성으로 표시하지 않음. 실패 시 기본 이미지로 자동 대체하지 않음 |
| 단일 IMAGE 게시 | Facebook Login for Business의 계정·권한·Graph transport 재사용. HTTPS `image_url` 컨테이너 생성 → 명시적 처리 조회 → 별도 공개 게시. 게시 ID·링크·계정과 파일 SHA-256 기록. 로컬 MP4 직접 전송과 구분 |
| 임시 HTTPS 전달 | 이미지 전용 별도 서버/클라이언트 코드·DPAPI 설정. 검토한 JPG만 POST, 동일 해시 확인, HTTPS/DNS 고정/robots/SSRF 보호. 서버 미준비 시 외부 요청 전에 BLOCKED, 로컬 저장은 가능. 실제 배포·업로드 없음 |
| 게시 보호 | Reels/YouTube 기존 코드는 재작성하지 않음. 피드와 동영상 기록 독립. 계정+파일 해시로 전송 전에 claim을 저장하고 실패·결과 불명·재시작 후 자동 중복 전송/게시 금지. 성공 ID를 링크 조회보다 먼저 저장 |

Carousel·다중 이미지 게시·새 영상/음성 엔진·새 계정 Provider·분석 대시보드는 추가하지 않았다. 기존 고급 장면별 혼합 계획과 과거 승인·사용 이력은 기존 계약으로 보존하며 새 전체 AI 영상의 기본값으로 사용하지 않는다. 과거 무버전 ElevenLabs+AI 계획은 자동 재개하지 않고, 명시적으로 새 전체 AI 계획과 승인을 사용한다.

## 공식 입력 규격·비용

이번 작업에서 공식 문서와 기존 Model Contract를 대조했다. 표는 요청 스키마이며 계정 사용 가능 판정이 아니다.

| 후보 | 모델 경로 | 공식 길이·선택 규격 |
|---|---|---|
| 기본 후보 | `pixverse/v6/text-to-video` | 1~15초, 720p, 9:16, Text-to-Video. 선택 TTS 사용을 위해 `generate_audio=false` |
| 대안 | `alibaba/wan-3.0/text-to-video` | 2~30초, 720p, 9:16. `generate_audio=false` |
| 대안 | `kling-video/v3.0-turbo/text-to-video` | 3~15초, 720p, 9:16. 공식 네 입력 필드 유지 |

장면을 덮는 가장 짧은 등록 길이를 선택한다. 모델 최대 길이보다 긴 대본 장면은 자동으로 짧은 클립을 반복 생성하지 않고 계획을 차단해 대본 장면 분할 또는 적합한 모델을 안내한다. 최종 합성은 기존 FFmpeg의 클립 배경·자막·출처·AI 표시 경로를 사용한다.

- 신규 전체 AI 영상·ElevenLabs에 추측 금액 예약이나 임의 요청 금액 상한을 추가하지 않는다. 기존 설정값·예약·실패 원장은 삭제하지 않는다.
- 신규 AI 영상 원장의 금액 `0`은 **무과금/확인된 청구액이 아닌 제출 claim의 내부 호환 값**이다. 화면은 실제 사용량·청구액 미확인으로 표시한다. 과거 고급 계획의 예상 기록은 구분해 보존한다.
- ElevenLabs는 응답 `character-cost`가 있을 때 보고된 크레딧만 저장하고 없으면 null이다. 실제 청구액과 다르다. 확인된 공급사 잔여 0, 권한·플랜 이용 조건, 명시적 동의, 결과 불명 차단은 유지한다.
- 뉴스 API의 잔액 확인 시각/추측 잔여액 강제 조건은 해제하며 기존 요청 원장과 결과 불명·동의·보고 사용량 보호는 유지한다.
- 공개 PixVerse 페이지는 15초 720p 클립의 표준 $0.06/초와 할인 $0.051/초를 안내한다. 이를 다른 길이·계정의 확정 견적으로 적용하거나 앱에 자동 저장하지 않았다. 계정별 실제 견적·잔액·청구액은 **NOT VERIFIED**다.

공식 근거: [PixVerse 스키마](https://open.higgsfield.ai/models/pixverse/v6/text-to-video/api-reference), [공개 가격 조건](https://open.higgsfield.ai/models/pixverse/v6/text-to-video/playground), [Wan 3.0 스키마](https://open.higgsfield.ai/models/alibaba/wan-3.0/text-to-video/api-reference), [Kling Turbo 스키마](https://open.higgsfield.ai/models/kling-video/v3.0-turbo/text-to-video/api-reference), [OpenAI Image API](https://developers.openai.com/api/reference/resources/images/methods/generate), [Meta 공식 Facebook Login 컬렉션](https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login).

## 보존과 검증

- 운영 체크아웃·앱·DB·LocalCache·기존 키·설정·MP4에 쓰거나 앱을 재시작하지 않았다. 개발 위치는 `integration-final-20261022/candidate`의 별도 소스 복사본이다.
- 기존 로컬 피드 제작·게시 코드를 재사용하고, 로컬에서 이미 사용한 additive migration **0014~0018을 그대로** 가져와 연결했다. 기존 0001~0013은 변경하지 않았다. 합성 DB의 0013/0017 → 0018 전환에서 기존 모든 테이블 행과 SQLite integrity를 확인했다. 운영 migration 실행은 없다.
- 실제 OpenAI·Claude·ElevenLabs·Higgsfield 유료 요청, OAuth, 외부 파일 전송, SNS 게시 **0회**. 임시 DB·Fake 토큰/응답·로컬 FFmpeg만 사용했다.
- Windows 로컬 Python **3.14.7**: 변경 범위 초기 실행 **451 PASS / 2 FAIL**. 두 실패는 합성 전 비활성 진행 버튼을 없다고 가정한 기존 UI 기대값이었다. 기대값을 실제 차단 동작으로 바꾸고 서버 조기 진행 거절까지 검사했다. 수정된 2개와 새 합성 연결·Chrome 경로 **7 PASS**, 최종 장면/피드 계약 **64 PASS**. 최종 Windows CI 결과는 아래에 별도 기록한다.
- Ruff·pip check PASS. 기존 전체 회귀 **57 FAIL 기록을 유지**하며 전체 재실행·실패 삭제·임의 skip은 하지 않았다. 본 범위 결과를 전체 회귀 PASS로 확대하지 않는다.

| 로컬 FFmpeg 결과 | 실제 길이 | 형식·검사 |
|---|---:|---|
| 기본 + 로컬 Fake 음성 | 30.021초 | 1080×1920, H.264/AAC, 전체 디코딩 PASS, Higgsfield 0회 |
| 기본 + ElevenLabs Fake | 45.021초 | 동일, WAV/타이밍 캐시 재사용 PASS, Higgsfield 0회 |
| 전체 AI Fake + 로컬 Fake 음성 | 60.021초 | 6개 시각 장면, 전부 Fake 클립·검토·합성 승인 후 MP4 |
| 전체 AI Fake + ElevenLabs Fake | 30.021초 | 동일, 고정 음성·모델·동의 및 저장 WAV/타이밍 재사용 |

음성은 합성 PCM이므로 실제 한국어 TTS 음질이나 사람의 최종 시청·청취 품질 PASS가 아니다. Chrome 1366/390px에서 계획·피드·설정 화면과 로컬 저장 동선을 확인했다. 브라우저 외부 요청을 차단하고 예약·자동 실행 없이 임시 앱에서만 검사했다.

[AI 계획 화면](evidence/final-production/final-video-1366.png) · [작은 창의 단일 피드](evidence/final-production/final-feed-390.png). 미디어 검사 JSON도 같은 증거 폴더에 보존한다. MP4·WAV·DB·키는 Git/Actions 아티팩트에 올리지 않는다.

## Windows CI와 최종 상태

Windows Python 3.12/3.14 변경 범위 CI: **실행 전**. 코드 push 후 실제 결과와 검증 SHA를 갱신한다. 기존 Draft PR #35 유지, 신규 PR·main/기존 PR 병합 없음.

## 실사용에 남은 필수 조건

1. 승인 후에만 운영 전체 백업·예약/미완료 작업 점검·코드 적용·첫 실행을 진행한다. 이번 단계에서는 적용하지 않았다.
2. 선택한 AI API·ElevenLabs·Higgsfield의 실제 계정 권한·모델 사용 가능 여부와 명시적 작업별 유료 승인을 확인하고 제한된 실생성으로 음성 길이·자막·영상 품질을 검증해야 한다. 현재 **NOT VERIFIED**.
3. Google/Meta 실제 로그인·권한·실제 업로드·게시 결과는 **NOT VERIFIED**. Meta 앱 승인·Page/프로 계정·기존 HTTPS OAuth 중계를 준비해야 한다.
4. 단일 피드 실게시에는 [별도 HTTPS 이미지 전달 서버 배포 조건](../INSTAGRAM_IMAGE_DELIVERY.md)이 필요하다. 서버·도메인·키가 없는 상태는 **BLOCKED**이며 이번에 서버를 배포하거나 이미지를 공개 업로드하지 않았다. 주소 접근 만료·서버 별도 정리와 로컬 원본/게시 기록 보존을 구분한다.
5. 기존 전체 회귀 57개 실패와 구버전 고급 계획 계약은 미해결 범위로 남긴다. 운영 적용 판정이나 실계정 성공으로 간주하지 않는다.

결과 제출 뒤 추가 기능 개발을 멈추고 사용자 판정을 기다린다.
