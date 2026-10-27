# Windows AI 대본 제작 동선 재검증

2026-10-24 KST / PR #35, Draft 유지.

## 범위와 코드

[검토 지시](https://github.com/jsbae1979-prog/JSBAE/pull/35#issuecomment-6379220221)에 따라 실패 동선만 진단했다. 제품 소스·기존 테스트·DB migration·BAT·API/게시 계약·보안 정책은 수정하지 않았다.

- 이전 검증/자료 HEAD: `446236f639640260d358eabec73f15fd67998155`
- 비교 기준 제품: `fbadd460d3005fca5c5aa613a78fd7c926c87be6`
- 최종 제품: `f6aedc5db10ac7df9e6ce7b2b7f8aab7f5c6bdac`
- 최초 검증 도구 SHA: `17110a8ddc163694e7253814057e38da7fc5c345`
- 최종 검증 도구 SHA: `090202f6f1cacfb7656aa227ca4802811a79da9b`
- [최초 Windows 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40058279550)
- [최종 Windows 실행](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40058732719)
- [제품 불변 증거](evidence/script-flow-recheck/product-boundary.json). 최종 보고서 제출 SHA는 PR 댓글에 별도로 기재한다.

## 원인: 제품이 차단해야 하는 Fake 대본

`tools/test_windows_final_flow.py`는 기존 Fake Provider의 짧은 응답에 “살펴봅니다.”를 반복 추가하여 예상 발화 시간을 27.05초로 맞췄다. 장면별 음성 시간은 맞았지만 이것만으로 대본 안전 검사를 통과하는 것은 아니다.

저장된 작업은 `stage=script`, `status=failed`, `error_code=script_auto_review`, `retryable=false`였다. Fake 호출 순서는 `search → analysis → script` 각 1회였다. 출처 참조는 존재했고 선택은 검토 사용/로컬 `supertonic:F1`/기본 FFmpeg/음성 API 동의 없음/속도 0·문장 휴지 250ms로 고정되어 있었다. TTS와 렌더링 전 중단했다.

`PipelineBackend._check_render_draft()` → `production_policy.check_draft()` → `IntelligenceService._review_notes()`에서 다음 경고를 발견했다.

| 규칙 코드 | 실제 Fake 응답 결함 |
|---|---|
| `explainer_spoken_hook` | hook이 첫 장면 내레이션의 맨 앞에 포함되지 않음 |
| `explainer_spoken_closing` | closing이 마지막 내레이션 끝에 포함되지 않음 |
| `explainer_synthetic_context` | 합성 자료인데 사실 장면의 역할/내레이션/자막에서 합성임을 명시하지 않음 |
| `narration_sentence_limit` | 문장 수가 3/3/3개로, 해당 3장면의 허용 2/1/2개를 초과 |

구체적인 사건·수치·날짜·인물을 새로 추가하지 않았으며, 실패는 실제 공급사 응답/인증 오류나 TTS 설치 문제가 아니었다. `check_draft`가 경고를 발견하면 중단하는 제품 동작을 유지했다. [수정 전 Cloud 진단](evidence/script-flow-recheck/cloud/old-fixture-diagnostic-openai.json).

## 최소 수정

검증 도구의 Fake 응답만 짧고 독립된 합성 뉴스 검토 문장으로 교체했다. hook/closing을 내레이션 경계에 포함하고 fact 역할·합성 자막을 명시했다. 문장 수 2/1/2, 장면 각 10초, 발화 추정 합계 27.45초다. 출처/분량/복제/비밀정보/게시 승인 검사와 실제 FFmpeg 경로는 그대로 실행한다.

`flow_script_fixture.valid_script()`는 테스트 도구에서만 import하며 실제 제작의 대체 Provider나 자동 재생성 기능이 아니다. 기존 3장면/합성 TTS 측정 조건을 보존했다. 권장 4장면 구성과의 차이는 기존 정책대로 `explainer_roles` 정보성 검토 메모로 남는다. 이를 숨기거나 완성 콘텐츠 품질 PASS로 주장하지 않는다.

대본 단계를 통과하자 이전 UI 선택자의 문제도 드러났다. 실제 현행 조작에 맞춰 `대본 직접 수정`을 펼친 다음 원래 편집 form을 저장하고, `작업실로 돌아가기` 링크와 기존 `data-publish-save` 버튼을 사용하도록 도구만 수정했다. HTTP POST·CSRF·동의 누락 차단·초안 revision·Provider 추가 호출 없음 등의 기존 검증은 유지했다.

변경 파일:

- `tools/test_windows_final_flow.py`: Fake 응답 연결, 현행 편집 조작, 합성 MP4 및 단계 결과 증거.
- `tools/flow_script_fixture.py`: 테스트 전용 응답.
- `tools/flow_failure_diagnostics.py`: 작업/규칙/합성 응답의 읽기 전용 진단. 키·토큰·운영 데이터 기록 없음.
- `tools/ci_script_flow_recheck.py`: 동일 Windows 환경에서 두 제품 SHA의 수정 전/후 동선 실행.
- `tools/test_mobile_voice_access.py`: 기존 390px 높이 실패와 실제 클릭·포커스 구분.
- `.github/workflows/newsflow-cloud-connect-windows.yml`: 수동 `scope=flow` 검증 job.
- 이 보고서와 증거 JSON/XML/PNG.

별도 신규 workflow 파일은 GitHub에 등록되어 있지 않아 수동 dispatch가 HTTP 404로 시작되지 않았다. 파일을 제거하고 기존에 등록된 workflow의 수동 scope로 실행했다. main 변경이나 미실행 PASS 처리 없음.

## 최초 Windows 실행에서 발견한 별도 종료 문제

`40058279550`에서 3.12는 성공했다. 3.14는 기준 코드의 수정 후 동선 2건이 통과했지만 최종 제품 코드의 OpenAI 동선이 테스트 서버 종료 시 `thread.is_alive()` 검사에서 실패했다(해당 묶음 1 PASS/1 FAIL). 실제 대본·MP4·Fake 게시 검증 다음의 context 종료에서 발생했으며, 로그에 Windows Proactor `ConnectionResetError [WinError 10054]`가 함께 기록됐다.

합성 브라우저의 요청이 안정된 후 context를 닫고, **테스트용 Uvicorn에만** `timeout_graceful_shutdown=5`를 지정했다. 기존 15초 thread join 및 스레드가 종료되어야 한다는 assertion은 유지했다. 제품 서버 설정이나 BAT는 변경하지 않았다. 연결 종료 오류의 운영체제 내부 원인을 해결했다고 주장하지 않는다. [최초 실행 증거](evidence/script-flow-recheck/initial-windows)는 그대로 보존했고 최종 SHA에서 두 Windows 버전을 재검증했다.

## Cloud 결과

Python 3.12.14 / Linux 개발 컨테이너 / Chromium, 임시 데이터만 사용.

- 수정 전 진단 probe: OpenAI 1 FAIL, `--maxfail=1`. 이를 두 Provider 전체 비교라고 주장하지 않는다.
- 수정 후 최종 동선: **2 PASS / 0 FAIL / 0 SKIP**, Starlette/httpx deprecation warning 1건.
- 관련 기존 안전·API 파이프라인 및 모바일 검사: **84 PASS / 0 FAIL / 0 SKIP**, 같은 warning 1건.
- 변경 검증 도구 Ruff: PASS.
- [동선 JUnit](evidence/script-flow-recheck/cloud/flow.xml), [동선 로그](evidence/script-flow-recheck/cloud/flow.txt), [안전 검사](evidence/script-flow-recheck/cloud/safety.xml).

## Windows 결과

**최종 Actions SUCCESS. 한정된 Fake 제작 동선과 안전 검사 PASS이며 전체 제품 회귀/실환경 출시 승인이 아니다.** 실제 Windows Server 2025(10.0.26100)의 Chrome에서 실행했다.

| 같은 환경의 비교 | Python 3.12.10 | Python 3.14.9 |
|---|---|---|
| fbadd460 + 이전 Fake 응답 | 0 PASS / 2 FAIL | 0 PASS / 2 FAIL |
| f6aedc5 + 이전 Fake 응답 | 0 PASS / 2 FAIL | 0 PASS / 2 FAIL |
| fbadd460 + 수정 응답·현행 UI 조작 | 2 PASS / 0 FAIL | 2 PASS / 0 FAIL |
| f6aedc5 + 수정 응답·현행 UI 조작 | 2 PASS / 0 FAIL | 2 PASS / 0 FAIL |
| 기존 안전/API 파이프라인 + 모바일 조작 | 84 PASS / 0 FAIL | 84 PASS / 0 FAIL |
| Ruff·의존성·pip check | PASS | PASS |

모든 표의 pytest 묶음은 ERROR/SKIP 0건이다. 각 동선 묶음에 Starlette/httpx deprecation warning 1건이 남는다. 이전 응답의 **실패 JUnit도 그대로 보존**한다. 비교 도구는 이 실패가 정확한 `script_auto_review`/경고 코드로 발생하고 수정 응답이 통과하는지를 판정한다. 이전 실패를 pytest PASS나 skip으로 변환하지 않았다. 관계없는 workflow job은 scope 조건으로 실행하지 않았으며 그 항목을 PASS로 세지 않는다.

양 버전에서 기준/최종의 testcase ID와 상태 맵이 수정 전·후 각각 동일했다. 즉 이미지 변경에 따른 신규 제품 회귀가 아니라 **검증용 Fake 응답이 기존 정책을 충족하지 못한 문제**다. 최초 도입 시점을 모든 과거 커밋까지 역추적한 것은 아니다.

정확한 동선 testcase는 `test_api_to_render_review_and_existing_publish_services[openai]`, `[claude_api]`이다. 비교 실행 사본의 `validation_tools/test_old_flow.py`, `validation_tools/test_fixed_flow.py`별 ID·명령·원시 JUnit은 다음 증거에 있다.

- [3.12 비교 JSON](evidence/script-flow-recheck/py312/comparison.json), [최종 동선 JUnit](evidence/script-flow-recheck/py312/product-fixed/tests.xml), [안전 84건 JUnit](evidence/script-flow-recheck/py312/safety.xml).
- [3.14 비교 JSON](evidence/script-flow-recheck/py314/comparison.json), [최종 동선 JUnit](evidence/script-flow-recheck/py314/product-fixed/tests.xml), [안전 84건 JUnit](evidence/script-flow-recheck/py314/safety.xml).
- [전체 요약·파일 해시](evidence/script-flow-recheck/summary.json), [증거 manifest](evidence/script-flow-recheck/manifest.json).

기존 `test_narration_length_contract.py`, `test_explainer_review_safety.py`, `test_api_news_pipeline.py`를 수정 없이 실행해 부적합 대본·출처/수치 검사·결과 불명/재시도 제한 등을 유지했다.

### MP4와 화면 증거

최종 제품 코드에서 양 Provider가 만든 합성 MP4는 1080×1920 / H.264 / AAC / 30fps / 30.021029초다. 실제 파일 SHA-256:
`0ee914930bdf9295f7d38808092e7c59c6fa4d06a77e3d2d0922fd70f9f3df7f`.
합성 입력이 같아 두 Provider/두 Python의 출력 해시가 동일하다. 단일 파일을 결과로 재사용한 것이 아니라 각 임시 실행에서 생성·다운로드·해시 검사를 수행했다.

MP4 자체는 Git에 추가하지 않고 Actions의 합성 산출물에 보존했다(14일 보관, 저장소 접근 권한 필요). `product-fixed/openai/synthetic-review.mp4` 또는 `product-fixed/claude_api/synthetic-review.mp4`를 사용한다.

- [Windows 3.12 다운로드 자료](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40058732719/artifacts/12546323872)
- [Windows 3.14 다운로드 자료](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40058732719/artifacts/12546451721)

| 합성 Windows 화면 | Python 3.12 | Python 3.14 |
|---|---|---|
| 대본 검토 대기 | [PNG](evidence/script-flow-recheck/py312/product-fixed/openai/api-script-review.png) | [PNG](evidence/script-flow-recheck/py314/product-fixed/openai/api-script-review.png) |
| 실제 생성 MP4 검토·재생 | [PNG](evidence/script-flow-recheck/py312/product-fixed/openai/generated-video-review.png) | [PNG](evidence/script-flow-recheck/py314/product-fixed/openai/generated-video-review.png) |
| Fake YouTube 성공 / Instagram 대기 | [PNG](evidence/script-flow-recheck/py312/product-fixed/openai/synthetic-partial-result.png) | [PNG](evidence/script-flow-recheck/py314/product-fixed/openai/synthetic-partial-result.png) |
| 390px 메뉴 | [PNG](evidence/script-flow-recheck/py312/safety/mobile/voice-menu-390.png) | [PNG](evidence/script-flow-recheck/py314/safety/mobile/voice-menu-390.png) |

### 390px 접근성 확인

Windows에서 해당 라벨은 두 줄 높이 **42px**, 실제 링크 영역은 **167.5×64px**였다. 잘림/가로 넘침 없음, 중앙 hit test·실제 클릭·키보드 포커스/Enter 이동 PASS. 한글 마지막 글자가 다음 줄로 내려가는 시각적 한계는 남는다. 이번 확인에서 입력·클릭 기능을 막는 접근성 결함은 재현하지 못해 CSS를 바꾸지 않았다. 기존 `<42px` 테스트는 여전히 실패 기록으로 유지한다. 사용자 PC 배율 검증과는 다르다.

## 단계별 검증 범위

이번 성공 동선은 모두 Fake API와 임시 DB를 사용한다. 검토·동의 버튼도 합성 자료에 대해 브라우저 자동화가 조작한 것으로, 사람이 실제 뉴스의 사실·저작권·음질을 승인했다는 뜻이 아니다.

1. 뉴스: 합성 검색 응답 저장, 무단 RSS fallback 없음, 요청 1회.
2. 분석/대본: 선택한 Fake Provider 각 1회, 자동 검사를 통과한 뒤 사용자 검토 대기.
3. 편집: 현재 화면에서 편집 영역 열기 → 기존 POST 저장 → revision 2 → 같은 작업 복귀. 새 API 요청 없음.
4. 음성/영상: 합성 무음 WAV 3개와 실제 FFmpeg로 MP4 생성. Windows SAPI/Supertonic/ElevenLabs 실제 음질은 미검증.
5. 파일/재생: ffprobe로 1080×1920, H.264/AAC, 약 30.021초 확인. Chrome `play()` 후 `currentTime > 0`, HTTP 다운로드와 디스크 SHA-256 일치. 전체 30초 사람 시청 평가는 아니다.
6. 최종 검토: `waiting_review/validate`에서 명시적으로 재개해야 로컬 게시 대기함에 등록. 이 단계만으로 저작권·사실 확인/게시 승인을 기록하지 않음.
7. Fake 게시 계약: 승인 누락 422 차단, 동일 MP4 해시, YouTube 1회, Instagram 처리 대기→별도 계속 동작, coordinator 재생성 후 성공 플랫폼 재전송 없음. 실제 계정/OAuth/외부 업로드 없음.

## 재현 명령

Windows workflow는 임시 프로필·DB·경로, 설치된 Chrome/FFmpeg 및 `PYTHONPATH=src;tests;tools`에서 다음을 실행했다. 각 비교 subprocess의 정확한 전체 명령과 대상 ID는 비교 JSON에 기록되어 있다.

```text
python tools/ci_script_flow_recheck.py --output <runner temporary directory>/newsflow-script-flow
python -m pytest -q -rs -p windows_final_guard tests/test_narration_length_contract.py tests/test_explainer_review_safety.py tests/test_api_news_pipeline.py tools/test_mobile_voice_access.py --junitxml=<temporary evidence>/safety.xml
```

첫 명령은 Git에서 기준/최종 소스를 임시 폴더로 읽어 실행하며 운영 앱을 시작하지 않는다. 실제 외부 서비스 접근은 guard로 차단한다. 과거 Fake 실패를 확인하는 진단과 수정 후 성공 검증이 모두 맞아야 비교 도구가 성공한다.

## 기존 실패 및 운영 한계

[이전 보고서](final_windows_ui_validation.md)의 변경 범위 125 PASS/5 FAIL 및 과거 57개 참조의 현행 대응 52 PASS/7 FAIL 결과는 그대로 보존한다. 제품 소스와 기존 테스트가 동일하므로 이번에 같은 회귀를 반복하지 않았다. 과거 57 FAIL 역사 기록도 유지하며 전체 회귀 PASS로 바꾸지 않는다.

이번에는 앞서 비교하지 못한 **실패 동선 자체**를 두 SHA에서 비교한다. 수정 전 Fake 응답의 실패와 수정 후 응답의 성공을 구분하며, 이전 실패 보고서를 삭제하지 않는다. 실제 사용자 Windows 11, 운영 DB/DPAPI/MP4 호환성, 한국어 음질·사람의 시청 평가, 실제 RSS/AI/실계정 게시는 NOT VERIFIED다.

합성 자료의 MP4와 화면만 검증 산출물로 보존한다. 사용자 DB·설정·키·기존 MP4·운영 앱에 접근하거나 재시작하지 않았다. 실제 유료 API·OAuth·SNS 호출 0건. 추가 제품 개발·main 병합·운영 반영 없이 제출 후 중단한다.
