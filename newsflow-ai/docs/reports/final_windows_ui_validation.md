# 최종 Windows UX/UI 호환성 검증

기록일: 2026-10-24 KST. PR #35 / `codex/newsflow-ux-video-app`, Draft 유지.

**판정: 전체 PASS 아님. Windows 실행·화면·합성 DPAPI는 PASS이나, 비교 회귀 실패와 제작 동선 실패가 남아 Actions는 FAIL이다.** 이번에는 제품을 수정하지 않고 검증 도구와 증거만 추가했다. 신규 실패 0건은 아래 두 비교 그룹에 한정한다.

## 검증 코드와 환경

- 제품 SHA: `f6aedc5db10ac7df9e6ce7b2b7f8aab7f5c6bdac` (실사형 이미지 적용 완료 코드).
- 비교 기준: `fbadd460d3005fca5c5aa613a78fd7c926c87be6` (실사형 이미지 적용 전 통합 UX 코드).
- 본 검증 실행 SHA: `3b9f8f5035ea39bcb0f721abee025c7e2d30eec1`.
- 과거 실패 목록 재검증 SHA: `345cdc76355772e2cb5ef0ad89e8fc14ac92ba6f`.
- 실제 Windows Actions: Windows Server 2025 / 10.0.26100, Python **3.12.10 / 3.14.9**, Windows Chrome. Linux 모의 Windows 검증이 아니다. 사용자 Windows 11 PC는 NOT VERIFIED.
- 제품 `src/`, 기존 `tests/`, `run.bat`, `pyproject.toml`은 제품 SHA와 동일하다. [변경 경계 증거](evidence/final-windows-ui/product-boundary.json). 보고서 제출 커밋은 PR 댓글에 기록한다.

## 실행 결과

| 항목 | Windows Python 3.12 | Windows Python 3.14 |
|---|---|---|
| 의존성 설치·pip check | PASS | PASS |
| 실제 BAT 실행·중복 차단·종료·재실행 | PASS | PASS |
| 실제 Windows DPAPI, 합성 비밀값만 사용 | PASS | PASS |
| Chrome 화면 테스트 | 2 PASS | 2 PASS |
| 변경 범위 회귀, 기준/최종 각각 | 125 PASS / 5 FAIL / 0 ERROR / 0 SKIP | 동일 |
| 과거 57개 참조의 현행 대응 59개 사례, 기준/최종 각각 | 52 PASS / 7 FAIL / 0 ERROR / 0 SKIP | 동일 |
| 위 두 그룹의 기준 대비 신규 실패 ID / 누락 사례 | 0 / 0 | 0 / 0 |
| Fake OpenAI·Claude 전체 제작 동선 | 0 PASS / 2 FAIL | 0 PASS / 2 FAIL |
| 사용자 Windows 11·운영 데이터·실계정·실제 음질 | NOT VERIFIED | NOT VERIFIED |

테스트 그룹은 중복될 수 있으므로 합산하여 전체 테스트 수로 표현하지 않는다. 전체 pytest 회귀를 다시 실행하지 않았으며 기존 전체 회귀 57 FAIL 기록을 지우거나 전체 PASS로 바꾸지 않았다.

- [Windows 본 검증 — FAIL](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40056234817)
- [과거 실패 목록 비교 — FAIL](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40056878190)
- [최초 검증 도구 실행 — FAIL](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40055916894)

첫 시도는 검증 도구의 archive 실행 위치, BAT 임시 경로, 이전 홈 선택자 문제로 완료하지 못했다. 도구만 수정하고 재실행했다. 본 검증의 과거 목록 수집도 변경된 매개변수 ID 때문에 exit 4였으며 0건 성공으로 간주하지 않았다. 이후 과거 목록만 별도 재실행한 결과가 위 52/7이다. `continue-on-error`는 나머지 증거 수집을 위한 것이며 최종 gate는 실패를 반환했다.

## 회귀 실패 비교

동일 Windows job 안에서 같은 Python·설치 의존성·환경·pytest 명령과 대상 목록으로 기준/최종 소스를 실행했다. 전체 testcase ID와 상태를 비교했으며 건수만 비교하지 않았다. 기준과 최종의 상태 맵이 두 버전 모두 일치했다.

변경 범위의 공통 실패 5건:

- `test_topic_search_honestly_uses_existing_news_search_not_new_generation_contract`: 이전 문구 “자료 준비” 기대.
- `test_editor_never_invents_a_preview_for_invalid_output`의 3가지 매개변수: 이전 문구 “영상이 준비되면” 기대. 앞선 잘못된 미리보기 차단 검사를 통과한 뒤 문구 검사에서 실패했다.
- `test_all_main_destinations_fit_small_windows[390]`: “보이스 라이브러리” 라벨 높이 42px 미만 조건 실패. 추가 390px 범위의 잔존 문제이며 요청한 두 데스크톱 뷰포트 검사와 구분한다.

과거 57개 참조는 기존 `regression-57-resolution/selection.json`을 사용했다. 변경된 매개변수 ID 4개는 해당 함수 전체를 실행하도록 매핑했다. 다른 매개변수도 생략하지 않아 현행 실행 사례는 59개이다. **과거 57건이 현재 모두 실패한다는 뜻도, 57건이 모두 해결됐다는 뜻도 아니다.** 원래 기록은 보존했다.

현행 대응 공통 실패 7건:

- `test_gui_prices_form_and_estimate_text`: 이전 `studio-estimate` 요소 기대.
- `test_start_and_job_pages_show_estimate_then_actual_usage[openai/claude_api]`: 기대 토큰값 `{1400,1600}`과 현행 `{2000}` 불일치, 2건.
- `test_home_policy_change_has_matching_readiness_and_notice_without_execution`: 이전 홈 정규식 매칭 실패.
- `test_pages_render_default_off_and_keep_six_main_menus`: 메뉴 링크 7개 기대/13개 실제.
- `test_wizard_is_optional_and_all_core_menus_remain`: 홈에 이전 quick-start form 존재 기대.
- `test_render[/settings-워크스페이스 설정]`: 이전 화면 제목 기대.

문구·메뉴·테스트 계약 불일치가 포함되지만 이번 검증만으로 모두 무해한 테스트 결함이라고 판정하지 않는다. 비용 예약을 되살리거나 테스트를 삭제·skip하여 PASS로 만들지 않았다.

상세 ID·실패 메시지·명령·상태 맵:
[3.12 변경 범위](evidence/final-windows-ui/py312/scoped-comparison.json) / [실패](evidence/final-windows-ui/py312/scoped-failures.json),
[3.14 변경 범위](evidence/final-windows-ui/py314/scoped-comparison.json) / [실패](evidence/final-windows-ui/py314/scoped-failures.json),
[3.12 과거 목록](evidence/final-windows-ui/py312/historical-comparison.json) / [실패](evidence/final-windows-ui/py312/historical-failures.json),
[3.14 과거 목록](evidence/final-windows-ui/py314/historical-comparison.json) / [실패](evidence/final-windows-ui/py314/historical-failures.json).

`scoped-comparison.json` 내부의 과거 목록 0건/exit 4는 수집 실패 기록이다. 과거 목록 판정에는 `historical-comparison.json`만 사용한다.

## 화면·이미지·데이터 보존

각 Python에서 홈·뉴스·대본·영상·보관함·Instagram 피드·게시 준비·설정의 8개 화면을 1366×768 및 1920×1080으로 확인했다. 16개 조합과 별도 빈 보관함 2개 화면을 캡처했다. HTTP 200, 가로 넘침 0, JS 오류 0, 외부 요청 0. 홈 실사형 WebP 로딩 및 “실제 보도 사진 아님” 표시, 문구와 이미지 설명의 겹침 방지를 확인했다. 빈 보관함의 보조 이미지도 확인했다. 선택적으로 적용하지 않은 화면에 이미지를 새로 추가하지 않았다.

이 검사는 화면 방문/배치 검증이며 모든 폼 제출이나 전체 제작 성공을 뜻하지 않는다. 화면 증거는 제품 SHA와 동일한 소스의 Windows 본 검증 실행에서 촬영했다. 브라우저 뷰포트 검증을 사용자 Windows 화면 배율 검증으로 확대하지 않는다.

| 화면 | 1366×768 | 1920×1080 |
|---|---|---|
| 홈 | [PNG](evidence/final-windows-ui/py312/screens/home-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/home-1920.png) |
| 뉴스 | [PNG](evidence/final-windows-ui/py312/screens/news-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/news-1920.png) |
| 대본 | [PNG](evidence/final-windows-ui/py312/screens/script-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/script-1920.png) |
| 영상 | [PNG](evidence/final-windows-ui/py312/screens/video-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/video-1920.png) |
| 보관함 | [PNG](evidence/final-windows-ui/py312/screens/library-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/library-1920.png) |
| Instagram 피드 | [PNG](evidence/final-windows-ui/py312/screens/feed-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/feed-1920.png) |
| 게시 준비 | [PNG](evidence/final-windows-ui/py312/screens/publish-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/publish-1920.png) |
| 설정 | [PNG](evidence/final-windows-ui/py312/screens/settings-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/settings-1920.png) |
| 빈 보관함 | [PNG](evidence/final-windows-ui/py312/screens/empty-library-1366.png) | [PNG](evidence/final-windows-ui/py312/screens/empty-library-1920.png) |

[Python 3.14 화면](evidence/final-windows-ui/py314/screens), [3.12 화면 감사](evidence/final-windows-ui/py312/screens/audit.json), [3.14 화면 감사](evidence/final-windows-ui/py314/screens/audit.json).

합성 DB 레코드·설정 및 테스트 미디어 파일 해시가 화면 방문 전후 동일했다. BAT는 임시 LOCALAPPDATA/한글·공백 경로에서 127.0.0.1:8765 실행, 중복 실행 거절, 종료, 재시작 후 SQLite marker/무결성을 확인했다. DPAPI는 현재 사용자 암호화·다른 Python 프로세스에서 합성 값 조회·계정 격리·교체/삭제·변조 거절을 검사했다. **실제 사용자 DB·설정·DPAPI 키·기존 MP4는 접근하지 않았으므로 그 실물의 호환성은 NOT VERIFIED**다.

## 뉴스 → 대본 → 영상 → 검토 → 게시 준비

기존 Fake 통합 테스트를 재사용하되 현재 홈 → `/create` 이동에 맞춰 검증용 선택자만 조정했다. 기존 제품 테스트는 그대로 두었다. OpenAI/Claude 각각 Fake 뉴스/분석 경로를 거쳐 대본 단계에서 기대 `waiting_review` 대신 실제 `failed`가 반환되어 두 버전 모두 2건 실패했다.

따라서 **이번 동선에서 신규 MP4 생성·재생, 완성 검토, 게시 준비까지 연결 성공은 NOT VERIFIED**이다. 기존 합성 영상이 표시된 스크린샷과 이 실패한 전체 동선을 혼동하지 않는다. 최신 안전 검증과 기존 Fake 대본 fixture의 적합성은 추가 확인 대상이며, 이번 결과만으로 실서비스 결함이나 공급사 품질 문제라고 단정하지 않는다. 이 동선 도구는 동일 기준 소스 비교를 수행하지 않았으므로 위 ‘신규 실패 0건’에 포함하지 않는다.

[3.12 동선 JUnit](evidence/final-windows-ui/py312/flow.xml) / [3.14 동선 JUnit](evidence/final-windows-ui/py314/flow.xml).

## 변경 파일·명령·보안

제품 변경 없음. 추가/수정한 검증 파일:

- `.github/workflows/newsflow-cloud-connect-windows.yml`: 수동 Windows 3.12/3.14 검증 job, 범위 선택, 실패를 보존하는 최종 gate.
- `tools/ci_final_windows_ui.py`: 동일 환경의 기준/최종 비교 및 과거 ID 매핑.
- `tools/windows_final_guard.py`: 외부 연결 차단 및 합성 테스트 환경.
- `tools/test_windows_final_visual.py`: 기존 격리 fixture를 사용하는 Windows Chrome 화면 검사.
- `tools/test_windows_final_flow.py`: 기존 Fake 통합 동선의 현재 진입 경로 검증용 사본.
- 이 보고서 및 `docs/reports/evidence/final-windows-ui/`.

워크플로는 설치된 동일 venv에서 다음 도구를 실행했다. 전체 인수·환경은 workflow와 비교 JSON에 보존했다.

```text
python tools/ci_final_windows_ui.py --output <temporary evidence>/comparison
python tools/ci_final_windows_ui.py --historical-only --output <temporary evidence>/comparison
python tools/ci_vault_validation.py --output <temporary evidence>/vault.json
python tools/ci_windows_launch_smoke.py --root <TEMP>/newsflow-final-ui-bat --output <temporary evidence>/bat.json
python -m pytest -q -rs tools/test_windows_final_visual.py --junitxml=<temporary evidence>/browser.xml
python -m pytest -q -rs tools/test_windows_final_flow.py --junitxml=<temporary evidence>/flow.xml
```

GitHub Actions 실행에서는 synthetic/Fake만 사용했다. 실제 유료 AI·Google/Meta OAuth·SNS 호출 **0건**. 테스트 외부 연결은 차단했고 운영 앱·사용자 자료는 읽거나 변경하지 않았다. 배포·main 병합 없음. 합성 DB·키·음성·MP4 자체도 보고서에 올리지 않고 JSON/XML/PNG 증거만 보존했다. [전체 요약](evidence/final-windows-ui/summary.json), [SHA-256 manifest](evidence/final-windows-ui/manifest.json).

## 남은 확인과 중단

- 대본 단계의 Fake 동선 실패 원인을 fixture와 실제 제품 검증 정책으로 나누어 확인한 뒤 전체 동선을 별도 재검증해야 한다.
- Windows 390px 라벨 높이 및 공통 테스트 계약 불일치는 잔존 사항으로 유지한다.
- 사용자 Windows 11의 운영 데이터 호환성·배율·한국어 음질·실제 콘텐츠 품질·실계정 연결/게시: NOT VERIFIED.
- 이번 작업은 검증 결과 제출로 종료한다. 실패를 숨기기 위한 제품/테스트 변경, 추가 개발, 실제 호출, 운영 반영을 진행하지 않는다.
