# 플랫폼별 계정·게시 가이드

작성 기준: 2026-10-20 KST. 이 문서는 현재 사용자 가이드의 위치와 범위를 안내합니다.

프로그램 실행 후 **설정 → 게시 계정 → 플랫폼별 가이드북**에서 읽으세요.
각 플랫폼의 설정에도 해당 가이드 링크가 있으며 기존 입력 화면을 보존하도록 새 탭으로 열립니다.

- 전체: `/guides/platforms`
- YouTube: `/guides/platforms/youtube`
- Instagram: `/guides/platforms/instagram`
- TikTok: `/guides/platforms/tiktok`

각 가이드는 계정 만들기 → 직접 업로드 → 앱 연결 → 게시 확인 → 문제 해결 순서입니다.
운영자 설정은 접어 두며, Ctrl+P 인쇄/PDF 저장 시 함께 펼칩니다.
도움말은 정적 로컬 화면이며 계정 조회·로그인·토큰 교환·업로드를 실행하지 않습니다.
외부 링크를 누르면 해당 공식 사이트가 새 탭에서 열립니다. 사이트에서 수행하는 로그인·게시 결정은 사용자의 별도 행동입니다.

직접 업로드에는 개발자 앱/API 키가 필요하지 않습니다. 직접 게시한 결과를 NewsFlow AI 이력으로 자동 동기화한다고 안내하지 않습니다.
YouTube 연결/게시와 Instagram 인증 중계/게시 코드는 존재하지만 실제 계정 운영은 미검증입니다.
Instagram은 별도 HTTPS 인증 서버와 Meta 앱 설정이 필요합니다. [운영자 배포 문서](INSTAGRAM_AUTH_RELAY.md)를 참고하세요.
TikTok Desktop Login Kit의 앱 등록·인증·갱신·해제 코드는 구현되어 있으나 실계정 인증·게시 활성화는 차단 상태입니다. [TikTok 연동 문서](TIKTOK_CONNECTION.md)에 구현 범위와 심사·운영 선행 조건을 정리했습니다.

가이드 본문은 `src/newsflow/gui/templates/guides/`의 플랫폼별 HTML을 단일 원본으로 관리합니다.
배포 파일에 해당 하위 템플릿을 포함합니다. 이전 보고서는 과거 단계의 근거로 보존하며 현재 동작 안내와 구분합니다.
