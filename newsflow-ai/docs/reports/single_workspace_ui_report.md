# 단일 작업실 UI 보고서

## 범위와 분리

- 기준: PR #24 `feat/newsflow-ux-workflow-unification`, `515f9544dfa2df587a95b2bafeceef43d08a64a7`.
- 작업: `feat/newsflow-single-workspace`. Phase 5F.5 AI 뉴스 자동화는 별도 PR #25에 보존했으며 이 브랜치에 포함하지 않았다.
- 기존 PR·main·마이그레이션·사용자 설정·DB·영상은 변경하지 않았다.

## 통합 결과

| 이전 | 현재 |
|---|---|
| 홈 / 작업 현황 / 내 영상 / 설정, 왼쪽 사이드바 | 상단 작업실(`/`) / 설정(`/simple-settings`) |
| 작업 상세로 이동해 검토·재개 | 작업실 안의 상세 패널에서 같은 검토 폼으로 재개 |
| 보관함의 여러 MP4 미리 로드 | 작은 첫 화면 썸네일만 지연 로드, 선택한 영상 하나만 `preload=none` 플레이어로 표시 |
| 작업·완성 영상 중복 목록 | 공통 작업 모델의 관계를 이용해 기본 목록 중복 제거; 최근 5개와 더 보기 |

- 기존 `task_rows`, Autopilot, Video Studio, PublishingService 파일 검증·다운로드를 재사용한다. 제작 엔진과 승인 기준은 바꾸지 않았다.
- 작업/영상 선택은 `/?task=…`, `/?video=…`, 전체 목록은 `/?show=tasks`, `/?show=videos`로 유지된다. 기존 상세 URL과 북마크도 유지한다.
- 누락된 영상은 재생 성공으로 표시하지 않고 기존 상세 복구 화면으로 연결한다.
- 썸네일은 기존 FFmpeg로 검증된 로컬 MP4 첫 프레임만 추출한다. 2개 동시 작업·10초 제한·32개 메모리 캐시·고정 인자·로컬 프로토콜 제한을 사용하며 원본 파일을 수정하지 않는다.
- 설정의 7단계 연결 상태, 저장한 Provider와 실제 실행 엔진 구분, 외부 동의·비용 승인, 대본·출처·최종 검토, AI 생성 장면 표시를 유지한다.

## 검증

- 로컬 Windows 11 / Python 3.14.7: 변경 범위 핵심 테스트 205개 통과 후 화면 기대값 2개를 수정해 해당 2개 통과. 누락 영상 복구 테스트 1개 추가 통과. 중복 제거 안내 변경은 해당 테스트 1개만 다시 확인했다. 전체 회귀는 실행하지 않았다.
- Ruff 및 `pip check` 통과. Windows Python 3.12·3.14 최종 Actions 결과는 아래 이력에 기록한다.
- 실제 Chrome: 체험 뉴스 선택 → Offline 대본 → 같은 화면에서 대본·합성 출처 확인 → Supertonic F1 + FFmpeg → 최종 검토 대기 → 같은 화면 재생·MP4 저장 확인.
- MP4: H.264/AAC, 1080×1920, **30.021680초**. Chrome에서 끝까지 재생(`ended=true`, 오류 없음). 목록에는 MP4 플레이어가 없고 선택한 플레이어는 재생 전 `readyState=0`을 확인했다.
- 다운로드한 MP4와 원본 SHA256 동일: `7ac55940c9e3524dbf4f8d7ac83b78840fde8724074ebc277101bf030fcd9b15`.
- 설정의 7단계 상태와 기존 `/autopilot/jobs/{id}` 상세 URL을 Chrome에서 확인했다. 실제 사용자 `run.bat` 화면도 열었다.
- 기존 사용자 DB 읽기 전용 백업 후 비교: 모든 테이블 건수·설정 해시·기존 MP4 2개 해시 동일, SQLite `integrity_check=ok`. 실제 사용자 검토 작업은 승인하거나 취소하지 않았다.

## 로컬 산출물

GitHub에는 사용자 자료·DB·영상·스크린샷·모델을 올리지 않는다. 아래 파일은 프로젝트의 무시된 `validation-output/single-workspace/`에 보존했다.

- `live-workspace.png`: 실제 사용자 통합 작업실 전체 화면
- `empty-workspace.png`, `script-review.png`, `final-review-playback.png`, `video-cards.png`, `inline-player.png`, `settings.png`: Chrome 동선
- `ui-test-data/outputs/videos/video-8198642b94a149bdbfdd87ef9c1c50fd.mp4`: 격리 환경에서 제작한 합성 체험 영상
- `video-result.json`, `before-preservation.json`, `after-preservation.json`: 로컬 검증 기록

## 한계·미검증

- PR #24 기준의 Claude·Codex 분석/대본, ElevenLabs, Higgsfield는 기존 개별 검토·승인 화면으로 연결한다. 해당 엔진의 자동 실행을 새로 구현하거나 Phase 5F.5를 병합하지 않았다.
- 뉴스 종류는 기존 체험/등록 뉴스 선택을 재사용한다. 분야별 AI 검색은 이 UI 작업 범위에 포함하지 않았다.
- 실제 유료 API·구독 추론·OAuth·SNS 호출은 0건. 인증·연결 진단을 자동으로 실행하지 않는다.
- 최종 검토는 대기 상태로 남겼다. 사람의 음성 품질 평가는 **NOT VERIFIED**.
- 다운로드 파일의 Chrome 직접 재열기는 도구가 `file:` URL을 차단해 **NOT VERIFIED**. 다운로드와 원본 일치는 확인했다.
- 로컬 Python 3.12 MSI는 설치/재시도하지 않았다. 해당 버전 검증은 Windows Actions로 분리한다.

## GitHub 이력

- 코드 SHA / Draft PR / Windows Actions: 업로드 및 1회 검증 후 기록 예정.
