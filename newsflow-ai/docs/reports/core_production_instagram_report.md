# B단계 Instagram Reels 구현

- 작업 브랜치: `codex/newsflow-core-production`, 기존 Draft PR #34 유지.
- A 승인 기준: `4d13ad067a167b6a701776bf54b7e555980e5a99`. A의 189개 테스트를 다시 실행하지 않음.
- 구현·Fake 검증 범위이며 실제 Meta 로그인·업로드·공개 게시 성공을 뜻하지 않음.

## 구현

| 항목 | 결과 |
| --- | --- |
| 계정 연결 | Facebook Login for Business의 사용자 토큰 → Page 토큰 → 연결된 Instagram 프로 계정 확인 계약 구현. 최소 권한·Page 작업 권한·계정 일치·만료 검사, 기존 DPAPI 저장 커널 재사용. **운영 로그인 BLOCKED**: 선택한 안전한 code 흐름의 HTTPS 인증 중계 미구현. |
| 로컬 MP4 전송 | 공식 resumable 컨테이너 생성 → 잠근 로컬 파일의 원본 바이트를 Meta로 직접 전송. 파일 전체를 메모리에 읽지 않으며 사전·전송 해시 확인. 별도 영상 서버 불필요. |
| 공개 게시 | 전송 후 처리 상태를 명시적으로 조회. FINISHED에서 계정·파일·공개 동의를 받아 게시. 최종 게시 직전 상태 재확인. 준비·전송만으로 게시 성공 표시 안 함. |
| 기록·중복 방지 | 요청 직전 SQLite 기록, 컨테이너 ID·게시 ID 즉시 저장, 링크·계정 검증. 결과 링크 조회 실패 시 성공 ID 유지. 계정+MP4 해시로 중복 차단, 시간 초과·중단·결과 불명 자동 재전송 없음. |
| 화면 | 기존 작업실에서 같은 영상의 YouTube/Instagram 선택. 설정에 계정 연결 상태, 작업실에 검토·전송·처리 확인·공개 승인·결과 표시. 플랫폼별 이력 독립. |

기존 PublishingService의 출처·내용·권리·AI 표시 검토, ffprobe 검사, MP4 경로·해시 보호와 YouTube의 Windows 파일 잠금을 재사용했다. 새 DB migration, 뉴스/음성/영상 엔진, 예약 게시, C단계 기능은 추가하지 않았다. Instagram 저장 후 같은 주소로 이동할 때 오래된 검토·처리 상태가 남는 문제는 해당 폼의 화면 갱신으로 해결했다.

## 공식 경로와 남은 연결 조건

2026-10-17 공식 공개 문서 확인. Graph API `v25.0`에 고정하며 최신 버전이라는 의미는 아니다. `graph.facebook.com`과 `rupload.facebook.com`만 사용한다. Instagram Login의 토큰·권한·호스트는 혼용하지 않는다.

- [컨테이너·직접 업로드 규격](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media.md): REELS, upload_type=resumable, 반환 id/uri, 원본 바이트 업로드, AI 생성 표시.
- [Resumable uploads](https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads.md): 로컬 파일 직접 전송, 전송과 게시 분리.
- [결과 필드](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media.md): id/permalink/owner. owner 누락 시 링크·소유자 확인 성공으로 표시하지 않는다.
- [계정·앱 조건](https://developers.facebook.com/documentation/instagram-platform/overview.md): Page와 연결된 Business/Creator 계정. 자체 관리 계정은 Standard Access 조건, 다른 사용자는 Advanced Access·App Review·Business Verification 조건 확인 필요.
- [Facebook Login for Business](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business.md), [로그인 보안](https://developers.facebook.com/docs/facebook-login/security/), [코드 교환](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/).

필요 권한은 `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`. 계정별 Page Publishing Authorization 등 추가 조건은 실제 앱·계정에서 확인해야 한다.

**가장 작은 남은 대안:** 등록된 HTTPS redirect에서 state·일회용 code를 검증하고 App Secret을 서버에서 관리하는 인증 전용 중계. 그 뒤 앱과의 안전한 토큰 전달을 구현·검증해야 한다. 영상은 Windows에서 Meta로 직접 보내므로 클라우드 영상 저장소는 필요 없다. 공유 App Secret 하드코딩, 토큰 직접 붙여넣기, 환경변수로 차단 해제는 제공하지 않는다. 공식 문서에 다른 데스크톱 흐름도 있으므로 Windows 자체가 전면 미지원이라고 주장하지 않는다. 이번에 선택한 안전한 코드 흐름의 인증 중계가 없는 상태다.

## 검증·보존

- 새 연결·전송·상태·공개 승인·결과 불명·중복·GUI의 Fake 테스트와 변경된 부분만 로컬 Python 3.14에서 확인했다. GUI fixture의 필수 message 누락을 보완한 뒤 해당 1건과 기존 YouTube 공유 화면 3건 PASS.
- 최종 Windows Python 3.12/3.14 CI: 아래 결과 기록에서 확정한다. 변경 범위 124건과 YouTube 공유 화면 영향 3건만 실행하며 전체 회귀는 반복하지 않는다.
- Ruff·로컬 pip check PASS. 새로운 패키지나 의존성 변경 없음.
- 별도 8795 서버와 합성 계정·DB·가짜 미디어로 화면 검토 저장, 플랫폼 선택, 미체크 전송 승인 표시 확인. Chrome 제어 연결이 없어 앱 내 브라우저 사용. 이 증거는 실제 MP4 재생·Meta 게시 증거가 아니다.
- 화면 증거는 로컬 `validation-output/instagram-ui-20261017/review.png`. 테스트 자료와 화면은 Git에 포함하지 않는다.
- 운영 8765 프로세스·사용자 DB·설정·DPAPI·API Key·기존 MP4·예약/실패 기록을 변경하지 않았다. 테스트는 별도 디렉터리만 사용했다.
- 실제 Meta OAuth·외부 MP4 전송·공개 게시·유료 AI·CLI 인증/추론 요청 **0건**. 문서의 공개 GET만 수행했다.
- 실계정 로그인·권한·만료·실제 업로드/처리/게시·반환 링크는 **NOT VERIFIED**. OAuth 중계 준비 전 실제 경로는 **BLOCKED**이며 전체 프로그램 완성을 선언하지 않는다.

## 변경 파일

신규: `oauth/instagram.py`, `publishing/instagram.py`, `publishing/instagram_live.py`, `gui/instagram_routes.py`, Instagram 연결/게시 템플릿 2개, 대응 테스트 4개, Instagram Windows CI, 이 보고서.

연결 변경: `main.py`, `gui/autopilot_routes.py`, `gui/production_routes.py`, `gui/youtube_routes.py`의 공통 조회, 작업실·설정 템플릿, `static/js/app.js`. 기존 YouTube CI는 수동 실행으로 보존해 B 변경마다 A 전체 테스트를 반복하지 않는다.

## 최종 결과

Windows CI 결과와 최종 커밋은 실행 완료 후 이 절에 기록한다. PR #34는 Draft로 유지하고 기존 PR #1~#33 및 main은 변경·병합하지 않는다. B 결과 제출 후 C단계는 시작하지 않는다.
