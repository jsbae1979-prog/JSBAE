# Phase 5F.3 — Claude CLI 및 음성 엔진 변경 보존

확인일: 2026-10-16. 기준: `feat/newsflow-phase5f2` / `e2904c6335954c7fb71becf02dc4c94c059bcd43`.

## 구현과 변경 파일

- `intelligence/claude_code.py`, `intelligence/service.py`, `intelligence/settings.py`, `gui/intelligence_routes.py`, `gui/templates/ai.html`: 설치된 공식 Claude Code CLI의 비대화형 JSON 생성, 스키마 검증, 취소·시간 초과·인증/사용량 오류 처리. 기사 출처와 기존 API/Offline 선택 유지. 뉴스 자료 전송 및 본인 계정 사용량 안내.
- `video/supertonic_tts.py`, `supertonic_assets.py`, `supertonic3_manifest.json`, `requirements-supertonic.lock`, `pyproject.toml`, `tools/install_supertonic_models.py`: 선택적 Supertonic 3 로컬 ONNX 음성 10종, 고정 모델 무결성 확인. 기존 핵심 의존성 잠금 파일은 변경하지 않음.
- `video/elevenlabs_tts.py`, `voice_engines.py`, `gui/video_routes.py`, `gui/templates/tts_settings.html`, `video.html`: ElevenLabs 선택·설정, 별도 DPAPI 키 저장, 매 제작 동의, 계정 한도 조회, 보수적 크레딧 예약, 결과 불명 차단 및 완료 캐시. 무료 플랜 상업 이용 차단과 비상업 공개 시 출처 안내.
- `video/tts.py`, `engine.py`, `service.py`: 실제 WAV 길이·문장 구간으로 장면과 자막을 조정. 30 fps 경계, 음성 끝 여유 시간, ASS 자막을 기존 카드/이미지/클립 FFmpeg 경로에 적용. 길이 초과 시 완전한 뒷문장을 줄여 재생성하고 원본 초안 보존·사람 검토 표시. 안전하게 줄일 수 없으면 중단하며 음성을 자르거나 자동 가속하지 않음.
- 관련 테스트 4개 파일, `tools/validate_claude_audio.py`, `.gitignore`, 이 보고서. 새 migration 없음. Windows SAPI/Heami 및 Offline 무음 유지.

## 공식 연동·라이선스 확인

**Claude:** [공식 비대화형 CLI 문서](https://code.claude.com/docs/en/headless)는 `claude -p`, JSON 출력 및 JSON Schema를 지원한다. 이 구현은 수정하지 않은 사용자 설치 CLI를 subprocess로 실행하며 로그인은 사용자가 Anthropic의 공식 흐름에서 완료한다. 인증 파일·쿠키·세션 토큰을 읽거나 복사하지 않는다. 도구/MCP/훅 실행과 세션 저장을 제한하고 빈 임시 작업 폴더에서 선택된 뉴스 자료만 stdin으로 전달한다.

[인증·제품 제공 조건](https://code.claude.com/docs/en/legal-and-compliance)에 따르면 사용자 본인이 공식 바이너리에 로그인하는 것과 제3자가 구독 자격증명을 수집·중개하는 것은 구분된다. 제품 제공에는 Commercial Terms, 공식 바이너리와 인증 방식 보존, 사용자 직접 인증·청구 조건이 적용된다. 현재는 본인 PC에서 본인 CLI를 이용하는 검증이며, 일반 배포 제품 전체에 대한 법적 적합성 승인으로 표시하지 않는다. 어댑터는 이번 승인 범위상 구독 모드만 허용하고 API 키 환경변수의 자동 상속을 차단한다. 배포 확대 전 이 제한과 공급사의 인증 방식 보존 조건을 별도 검토해야 한다. 공식 CLI 자체는 수정하지 않았다.

[구독 안내](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)에 따른 본인 플랜의 사용량·한도가 적용된다. 무료 무제한으로 표시하지 않는다. 로컬 토큰 기록은 공급사 잔여량·청구서가 아니다. 앱은 실패 요청을 자동 재실행하지 않지만 CLI 내부 네트워크 재시도까지 없다고 보장하지 않는다. 이번 보존 작업에서는 실제 추론을 다시 호출하지 않았다.

**Supertonic 3:** [공식 코드 보관소](https://github.com/supertone-oss-archive/supertonic)는 MIT, 모델은 OpenRAIL-M이다. 설치된 고정 revision `aafc6e32416a594460b32413efc49d7fe4ce6d46`의 [모델 LICENSE](https://huggingface.co/supertone-oss-archive/supertonic-3/blob/aafc6e32416a594460b32413efc49d7fe4ce6d46/LICENSE)를 확인했다. 상업적 이용을 일괄 금지하지 않으며 사용 제한 준수를 전제로 로열티 없이 사용할 수 있다. 유해·불법 이용 제한, 기계 생성임을 명확히 고지할 의무, 모델 재배포 시 라이선스·고지·사용 제한 전달 의무가 있다. 원본 라이선스는 로컬 모델 폴더에 보존된다. 코드와 모델의 라이선스를 동일한 MIT로 표시하지 않는다. 공식 개발·지원은 2026-09-09 종료되어 추가 보안 패치가 보장되지 않는다. 모델은 이번 Git 변경에 포함하지 않는다.

**ElevenLabs:** [공식 이용 안내](https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform)에 따라 무료 플랜 생성물은 비상업용이며 공개 시 제목에 `elevenlabs.io` 또는 `11.ai` 표시가 필요하다. 유료 플랜의 상업 라이선스도 음성·이용 조건을 확인해야 한다. 설정 UI에 제한을 표시하고 기본 사용 목적을 상업용으로 두어 무료 계정으로 생성하는 것을 차단한다. 잔여량 조회 실패·알 수 없는 플랜·초과 과금 활성화 시 호출을 차단한다. 실제 계정 잔여량과 로컬 카운터를 동일시하지 않는다.

## 검증 결과

| 항목 | 결과 |
| --- | --- |
| 이전 핵심 테스트 | 84개 PASS. 이번 작업에서 반복하지 않음 |
| 이번 추가 확인 | 라이선스·무료 플랜 안내를 검증하는 설정 화면 테스트 1개 PASS; 변경 Python 파일 Ruff PASS |
| 이전 실제 Claude 연동 | Windows 11 / Python 3.14.7 / CLI 2.1.301에서 SUCCESS. 체험용 합성 기사만 전송, 원문 출처 보존 |
| 기존 실제 Heami MP4 | H.264/AAC, 1080×1920, 30.021680초 |
| 기존 실제 Supertonic F1 MP4 | H.264/AAC, 1080×1920, 30.021354초. 이전 Claude JSON 재사용, 추가 Claude 호출 없음 |
| 문장 타이밍 | 실제 문장 WAV 길이 사용. Supertonic 장면 음성 3.204/7.175/5.503초, 장면 시작 0/7.033/19.766초. 음성 끝 25.269초, 영상 끝까지 여유 유지 |
| 데이터 보존 | 이전 재시작 검증에서 SQLite quick_check=ok, 행 개수 및 기존 MP4 해시 유지. 이번에는 사용자 데이터 쓰기·앱 재시작 없음 |
| Python 호환성 | 3.12·3.14 정책 및 Ruff py312 유지. 이전 3.12 선택 의존성 wheel 해석 성공; 새 기능의 3.12 실제 런타임은 미검증 |
| 실제 ElevenLabs | 미실행. Fake만 검증; 실제 인증·플랜·청구·음질 미검증 |
| Windows Actions | 이번 정리에서는 새 CI를 실행하지 않음. 기존 다른 브랜치 CI를 이번 변경의 성공으로 대체하지 않음 |

로컬 샘플: `validation-output/claude-live-audio-20261016/result.mp4`, `validation-output/claude-supertonic-20261016/result.mp4`. WAV·영상·검증 JSON·DB 백업·모델 가중치는 로컬에만 보존한다. 문장 시간은 측정했지만 단어별 정확한 발화 정렬이나 사람의 발음·가독성·체감 싱크 평가를 PASS로 주장하지 않는다. Chrome 창 열기는 수행했으나 새 설정 화면의 최종 자동 브라우저 확인은 도구의 URL 확인 제한으로 완료하지 못했다.

## Git 및 범위

기존 `feat/newsflow-phase5f3` / PR #18의 Azure·Google TTS 이력과 현재 작업을 덮어 합치지 않는다. Phase 5F.4 연구 계약 변경은 원래 브랜치에 보존하고 이번 음성 변경 커밋에는 포함하지 않는다. 최종 브랜치·SHA·Draft PR 링크는 완료 메시지와 PR에 기록한다. 사용자 인증정보·SQLite·WAV·MP4·모델은 추가하지 않는다. 기존 Git 이력에 있는 과거 증거 파일은 수정·삭제하거나 새로 업로드하지 않는다. main 및 PR #1–#17 변경, 실제 유료 API·SNS 호출, 실행 정책 변경은 수행하지 않는다.
