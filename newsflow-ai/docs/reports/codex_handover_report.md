# Codex 인계 검증 — Phase 5D → 5D.1

확인: 2026-10-16 08:02 KST (UTC+9). 저장소 `jsbae1979-prog/JSBAE`, Windows 11/Python 3.12 운영, Cloud 개발·검사.

## Git 및 자산 보존

작업 시작은 깨끗한 `feat/newsflow-phase5b` / `553098fcd4d303eb0cf9c6c33a33c5df7f9a371c`였다. 원격 Phase 5D를 fetch하여 HEAD가 인계 지정 `3951a231e8a5a03a113498d8223a25cc8a6d3b38`과 일치함을 확인하고 그 SHA에서 `feat/newsflow-phase5d1`을 만들었다. 미커밋 변경은 없었다. `698508e4e85d7f16caebabdeaecf50cb8469e490` 이후 인계 HEAD까지는 보고서·증거만 변경되었으며 실행 코드는 같다. main과 PR #1~#12의 원격 SHA는 작업 전 보존 기록을 남겼다. 기존 브랜치·PR 변경, 병합, force push, 커밋 재작성 없음.

## 읽은 자료와 구현 대조

`AGENTS.md`, README, architecture.md, Phase 5C.1 운영 준비도 보고서, Phase 5D 완료·기존 기능 분석·Higgsfield 검증 보고서, Phase 5D 구현 설계를 읽고 공급사·비용·작업자·GUI·CI 코드와 대조했다.

- 기존 RSS/AI/Autopilot/스토리보드/TTS/FFmpeg/검토·게시 대기함을 재사용하는 구조와 migration 0010/0011을 확인했다. 재구현하지 않는다.
- AI 영상은 별도 `AIVideoCoordinator`와 `VideoProvider`, 별도 DPAPI 키·비용표를 쓰고 Autopilot은 카드 모드를 유지한다.
- 공급사 기본 off, 날짜 있는 승인, 작업·월 한도, 모델 확인, 키, 계획별 비용 확인 게이트가 있다. OAuth/SNS 경계는 별도이며 계속 차단된다.
- 제출 `submitting`은 재시작 시 unknown, 알려진 request_id는 조회·다운로드로 복구하며 기존 클립 해시와 검토를 보존한다.

## 근거가 확인된 불일치

| 항목 | 근거 | Phase 5D.1 조치 |
| --- | --- | --- |
| 제출 재시도 없음이라는 Protocol/모듈 설명과 실제 서비스가 다름 | `service._submit_one`이 `ProviderRateLimited`를 최대 3회 waiting으로 되돌림. `HiggsfieldProvider._error`는 제출 408/429를 이 오류로 분류. 기존 테스트도 4번 전송을 기대 | 제출 자동 재전송 제거, 결과 불명·비용 예약 유지, 이전 버전의 재대기 행도 격리 |
| 408/429가 접수되지 않았다는 문서 가정 | 공급사 공식 오류 문서에서 그 보장을 확인하지 못함 | 안전한 미전송으로 간주하지 않음 |
| 공식 문서 접근 불가라는 이전 환경 한계 | 이번 환경에서는 docs.higgsfield.ai 문서 GET 200. 멱등성·보관·환불·모델 스키마 원문 확보 | 별도 날짜·URL·해시로 재검증; 과거 보고서는 당시 기록으로 보존 |
| 일부 모델 후보와 공통 4개 요청 필드 불일치 | 현재 Kling 2.6 문서에 resolution 없음, Wan 2.6 문서에 aspect_ratio 없음 | 확인되지 않은 필드를 추정하지 않고 현재 공통 어댑터의 제약을 점검·차단 |
| README 설치 브랜치가 5C.1에 머무름 | 실제 최신 구현은 5D | 새 검토 브랜치 안내 갱신 |

## 환경·기준 회귀

Python 3.12.14, 기존 .venv의 `pip check` PASS. FFmpeg/ffprobe 및 시스템 Chromium 사용 가능. `tools/ci_prepare_font.py`로 Noto Sans KR의 저장소 고정 SHA256을 검증했다. TLS·네트워크 정책 변경 없음.

첫 실행: 2190 passed / 17 skipped / 1 warning / 0 failed. 글꼴 환경변수 누락으로 10개 영상 검사가 추가 skip되었으므로 기준 검증으로 사용하지 않는다.

정상 설정 후 **2200 passed / 7 skipped / 1 warning / 0 failed**, 총 2207개. 명령: `NEWSFLOW_FONT_PATH=<검증된 글꼴> NEWSFLOW_LIVE_TEST=0 NEWSFLOW_AI_LIVE_TEST=0 python -m pytest -q -rs`. Skip: 실제 AI/RSS opt-in 2개, native Windows 5개. 기존 Starlette/httpx 경고 1개. 기존 보고서의 Cloud 수량과 일치. Windows 2204/3은 이전 검증 기록이며 이번 코드 검증으로 대체하지 않는다.

## 계속 미검증인 항목

실제 Higgsfield 인증·모델 동작·결제·계정별 가격/동시 제한·환불·품질, 실제 OpenAI, 사용자 Windows 11 운영, 한국어 음성의 사람 청취·완성 영상 품질은 NOT VERIFIED. 기존 Windows RSS 성공은 해당 피드·시점의 증거이며 모든 RSS의 보편적 성공으로 확대하지 않는다. 실제 OAuth/SNS는 차단 유지. 이번 인수 검사에 유료 API·OAuth·SNS 호출은 0건, 비용 0이다. 공식 공개 문서 GET은 생성 API 호출과 구분한다.

## Claude 최종 종료 보고 추가 대조

사용자가 전달한 Claude 종료 보고: 예약 점검 활성 0건, 마지막 작업 트리 Clean. 이는 **인계된 보고**이며 Codex가 다른 Claude 세션의 예약 작업을 직접 조회한 결과는 아니다.

2026-10-16 KST 추가 확인에서도 원격 `feat/newsflow-phase5d`는 지정 SHA `3951a231e8a5a03a113498d8223a25cc8a6d3b38`로 유지되었다. 동시 세션 푸시 가능성을 고려하여 종료 전에도 재확인한다. 기존 분석 §4~§4.12와 설계 §7.1의 유료 클립 보존·재조회·다시 받기·키/요청 내용 결합·대본 반영 정책을 재대조했다. 변경은 자동 제출 재전송·비용 기록 검증·로컬 사전 점검에 한정하며 기존 회귀를 유지한다. migration 0010·0011 및 다른 DB 파일 변경 없음, 새 migration도 필요하지 않다.

문서만 바뀐 최종 커밋과 실제 Windows 검증 코드 SHA를 구분하여 완료 보고서에 기록한다. 신규 코드 커밋 `986355879681bdcc159163f413b2afed6c79b602`에서 [Windows Actions](https://github.com/jsbae1979-prog/JSBAE/actions/runs/38832096264)가 실제 실행되어 SUCCESS로 종료되었음을 확인했다(2227 passed / 3 skipped / 1 warning / 0 failed). 문서 커밋에 자동 실행이 없으면 이전 코드 테스트를 새 실행으로 표현하지 않는다.
