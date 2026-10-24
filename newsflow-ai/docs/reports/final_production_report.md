# NewsFlow AI 최종 통합·운영 적용 보고

검증·적용 소스: `7d6224f6f223e6daee4470e3f361cc19ff7d4d26`.
브랜치: `codex/newsflow-ux-video-app`, 기존 [Draft PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35).
Windows 격리 개발과 GitHub Windows runner에서 검증했다. Codex Cloud에서 실행했다고 표시하지 않는다.

## 결합·재사용

공통 기준 `3c52309`에서 운영 `0276447`과 기존 통합 코드를 3방향 비교했다. 운영의 313개 소스를 모두 보존하고 SerpApi·Google Trends·전체 뉴스 화제성 평가·음성 목록/미리듣기·공식 견적 자동 입력·현재 화면을 유지했다. 로컬 Claude 진단 보완 3개 파일은 원본 바이트 그대로 보존했다. 이전에 인수한 OAuth 보완도 유지했다.

638개 파일의 커밋 차이는 기존 운영 코드·테스트·보고서·증거를 통합 브랜치로 인수한 범위다. 운영 소스와 비교한 실제 기능 수정은 30개 경로이며, 이미 있던 로컬 진단을 제외하고 운영에 새로 반영한 소스는 29개다. 새 관리 기능을 개발한 범위로 해석하지 않는다.

| 항목 | 동작·보호 |
|---|---|
| 기본 영상 | 기존 TTS·이미지·자막·FFmpeg. 30/45/60초, 선택 음성 사용, Higgsfield 0회 |
| 전체 AI 영상 | 모든 시각 장면 Higgsfield, 공통 스타일, 단일 모델, 최대 지원 길이보다 긴 장면은 수정 안내. 유료 생성 → 관계 검토 → 합성 → 최종 영상 검토 승인 유지. 카드 자동 대체 없음 |
| 음성 | 기본/전체 AI × 로컬/ElevenLabs 연결. 작업별 음성·모델·속도·동의를 보존하고 저장 WAV·타이밍·클립 재사용. ElevenLabs 실패 시 재전송·로컬 대체 없음 |
| 대본 검토 | 기본 체크. 해제한 새 작업만 기존 자동 구조·근거·비밀정보 검사를 통과해 진행. AI 장면 승인과 공개 게시 승인은 별도. 과거 작업의 승인 상태는 바꾸지 않음 |
| Instagram 피드 | 기본 1080×1350 JPG 1장, OpenAI 미선택 시 이미지 API 0회. 선택 시 기존 배경 생성/전체 이미지 생성 경로와 별도 승인을 유지. Claude는 문구·지시문을 작성하며 래스터 이미지 생성 공급사로 표시하지 않음 |
| 피드 게시 | 기존 Facebook Login for Business 계정·권한 재사용. HTTPS JPG → IMAGE 컨테이너 → 처리 조회 → 별도 공개 게시. 파일 SHA·계정·ID·링크, 실패·결과 불명·중복 방지 유지 |
| HTTPS 이미지 전달 | OAuth와 분리한 이미지 전용 서버/클라이언트. JPG 1장/2MiB, HTTPS·TLS·SSRF·robots·해시 검증, DPAPI 전용 키, 접근 1시간 만료. 실제 서버 배포는 미수행 |
| 기존 SNS | YouTube와 Reels 경로 및 독립 게시 기록 보존. 이미지 기능 때문에 동영상 게시 정책을 바꾸지 않음 |

Carousel·다중 이미지 게시·새 음성/영상 엔진은 추가하지 않았다. 기존 고급 혼합 계획·기록은 보존하며 신규 전체 AI 작업과 구분한다.

새 전체 AI 계획과 ElevenLabs는 추측 기반 금액 예약/임의 금액 상한으로 차단하지 않는다. 기존 한도 설정·예약·실패·결과 불명 원장은 그대로 둔다. 원장의 신규 금액 `0`은 내부 제출 claim 호환 값이며 무료/확정 청구액이 아니다. 공급사에서 확인한 사용량만 별도 기록하고 실제 청구액 미확인을 명시한다. 확인된 잔여 0·권한·이용 조건·명시적 동의·중복 방지는 유지한다.

## 변경 범위 검증

[동일 SHA의 Windows CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/39886504223):

| 환경 | 결과 |
|---|---|
| Windows Python 3.12.10 | **443 PASS / 0 FAIL / 0 SKIP**, Ruff·pip check PASS |
| Windows Python 3.14.8 | **443 PASS / 0 FAIL / 0 SKIP**, Ruff·pip check PASS |

각각 기존 Starlette/httpx deprecation warning 1건. 대상은 `tools/operating_compatibility_targets.txt`의 변경·보존 경계이며 전체 회귀 결과가 아니다. 이전 전체 회귀 **57 FAIL 기록과 이후 수정 보고서/증거를 보존**했다. 이번에 전체 회귀를 반복하지 않았으므로 현재 전수 결과로 확대하지 않는다.

Windows 로컬 3.14.7에서도 Fake 제작·수집·화제성 평가·음성·이미지 전달·콜백·브라우저 검증을 수행했다. 결합 초기에 발견한 생성자/중복 라우트·승인 분기 충돌과 테스트의 로컬 소켓 차단을 수정했다. 실패 테스트 삭제나 임의 skip은 없다.

| 로컬 합성 결과 | 길이 | 검사 |
|---|---:|---|
| 기본 + 로컬 Fake | 30.021초 | 1080×1920 H.264/AAC, 전체 디코딩 PASS |
| 기본 + ElevenLabs Fake | 45.021초 | 동일, 저장 WAV·타이밍 재사용 |
| 전체 AI Fake + 로컬 Fake | 60.021초 | 모든 시각 장면 Fake 클립, 검토·합성 승인 |
| 전체 AI Fake + ElevenLabs Fake | 30.021초 | 동일, 고정 음성·모델·동의 보존 |

실제 한국어 음질·유료 공급사 결과물·사람의 최종 시청/청취 품질은 **NOT VERIFIED**다. [합성 자료 검증 증거](evidence/operating-compatible/windows-ci.json), [AI 계획](evidence/operating-compatible/final-video-1366.png), [작은 창](evidence/operating-compatible/final-video-390.png), [피드 화면](evidence/operating-compatible/final-feed-1366.png)을 제공한다. 운영 DB·키·MP4·WAV는 Git/Actions에 올리지 않았다.

## 승인된 운영 적용·보존

- 영구 보호 백업: `C:/Codex/NewsFlowAI/backups/production-preapply-20261023-103129`. 데이터 37개, 기존 코드 archive/patch/미추적 소스를 보존하고 복사 해시를 확인했다.
- 복사본의 migration·integrity·FK 확인 결과 **0018 → 0018**, 신규 migration 없음. 게시된 migration 파일은 변경하지 않았다.
- 내용이 달라진 소스 29개만 원본을 추가 백업한 뒤 반영했다. 줄바꿈만 다른 파일은 유지했고 기존 파일 삭제는 0개다. 적용 후 소스 318개를 검증 코드와 대조했다.
- 기존 LocalCache 데이터 경로로 정상 첫 실행 1회. 활성 예약/진행 중 제작은 없었다. 강제 종료·재시도·복구·예약 변경은 하지 않았다.
- 운영 9개 화면과 390px 주요 3개 화면, 총 12개 뷰: HTTP 200, 가로 넘침·JavaScript 오류 0. 폼 제출 0, 외부/비읽기 요청 0. 출처 이미지 프록시와 영상 썸네일 생성은 검사 중 차단했다. 운영 화면 캡처는 보호 백업에만 저장했다.
- 안정 복사한 DB에서 **47개 모든 테이블의 행·값 해시 동일**, integrity PASS, FK 위반 0. 운영 DB에 직접 진단 연결을 열지 않았다. 키·설정·기존 영상 등 사용자 콘텐츠 파일 28개의 해시도 동일하다. 보호 백업 전체 해시 동일.
- 첫 보존 검사는 실행 중 Windows 잠금 파일 읽기에서 멈췄다. `migration.lock`·`server-8765.lock` 2개는 사용자 콘텐츠 검증에서 제외하고, 이미 확보한 DB 복사본으로 검사를 마쳤다. 운영 DB 재복사·복구·앱 재시작은 하지 않았다.
- 실제 유료 API·OAuth·외부 파일 전송·SNS 게시 **0회**. [비밀정보 없는 운영 적용 요약](evidence/operating-compatible/operating-application.json).

운영 체크아웃의 브랜치/HEAD는 백업·비교 기준 `codex/newsflow-local-d4dc20f` / `027644730c04b6b977baa9c4ede3eeb56115e61b`를 유지한다. checkout/reset/병합으로 이력을 바꾸지 않고 위 검증 소스를 반영했다. PR #35의 브랜치와 운영 Git HEAD를 같은 것으로 보고하지 않는다. 보고서 후속 커밋은 문서·합성 증거만 갱신한다.

## 실제 사용에 남은 필수 조건

1. 기존 대본을 재사용하는 30초 제작 1건으로 실제 공급사·한국어 음질·자막·영상 품질을 확인한다. 기사/대본·모델·장면 수·요청 횟수를 제시한 별도 유료 승인이 필요하다. 실제 모델 계정 접근·잔액·확정 견적은 미조회/NOT VERIFIED다.
2. 저장된 공식 모델 계약은 PixVerse V6/Wan 3.0/Kling 3.0 Turbo의 720p·9:16 입력을 지원한다. 기존 공식 견적 자동 입력은 Fake로 보존 검증했으며, 이번에 실제 계정 조회나 최신 견적 조회를 실행하지 않았다. 단가를 추측해 저장하지 않았다.
3. Google/Meta 실제 로그인·권한·업로드·게시 검증은 별도 사용자 승인 후 진행한다. 현재 **NOT VERIFIED**다. 계정·영상/이미지·공개 범위·게시 횟수를 먼저 정해야 한다.
4. Instagram은 Meta 앱/권한·Page 연결 프로 계정과 기존 HTTPS OAuth 중계가 필요하다. 단일 피드에는 [이미지 전용 HTTPS 서버](../INSTAGRAM_IMAGE_DELIVERY.md)의 도메인·TLS·전용 저장소/키·만료 정리가 별도로 필요하다. 인프라가 없는 실게시 경로는 **BLOCKED**다. 서버 배포·스토리지 개설·공개 업로드는 수행하지 않았다.

기존 [Draft PR #35](https://github.com/jsbae1979-prog/JSBAE/pull/35)는 미병합으로 유지한다. 새 PR·main/기존 PR 병합·force push 없음. 이번 승인 범위는 완료했으며 추가 기능 개발을 시작하지 않는다.
