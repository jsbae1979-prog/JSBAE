# RSS 출처 빠른 등록

- 기록일: 2026-10-20 KST
- 기준: `771d66a`, 기존 작업과 운영 데이터 보존.
- 범위: `/sources`에 제공 사이트 선택 등록 추가. 사용자 PC DB에 직접 등록한 것은 아님.

## 제공 주소

| 출처 | RSS |
|---|---|
| Google News 한국 | https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko |
| 연합뉴스 전체 | https://www.yna.co.kr/rss/news.xml |
| 한국경제 전체 | https://www.hankyung.com/feed/all-news |
| 경향신문 전체 | https://www.khan.co.kr/rss/rssdata/total_news.xml |
| BBC 세계 (영문) | https://feeds.bbci.co.uk/news/world/rss.xml |

주소는 등록 편의를 위한 목록이며 현재 공급 여부·영상 재사용 권한을 인증하지 않는다.
기존 Google 기본 등록은 유지한다. 사이트 선택 → 이용 조건 확인 → 등록 →
연결 테스트 → 사용하기 → 지금 뉴스 모으기 순서로 기존 수집기에 연결된다.
직접 주소 입력도 유지한다.

## 보존 및 검증

- PASS: 기존 등록 함수 재사용. CSRF·URL·이용 조건 확인·100개 한도·중복 URL 검사 유지.
- PASS: 등록 상태는 비활성. 등록만으로 외부 요청·수집·기사 삭제가 발생하지 않음.
- PASS: 기존 출처 이름·주소·활성 상태 보존. 등록된 사이트는 선택 목록에서 비활성 표시.
- PASS: Python 3.12, `python -m pytest -q -rs tests/test_sources_gui.py tests/test_collector.py tests/test_gui.py`
  → **35 passed / 0 failed / 0 skipped / 1 warning**, 6.67초.
- PASS: 변경 Python 파일 Ruff 및 `git diff --check`.
- 최초 테스트에서 새 테스트의 미설치 bs4 의존 때문에 5건 실패. 추가 의존 없이
  실제 렌더링 문자열 검사로 수정 후 위 명령 전체 재실행 통과.
- NOT VERIFIED: 실제 RSS 수집. 변경하지 않은 `PublicRSSAdapter`와 `Collector`로
  각 주소를 8초 제한으로 1회 확인했으나 5개 모두 `network` /
  `RSS 연결 또는 TLS 검증에 실패했습니다.` 반환. robots·TLS·SSRF 우회 없음.
  구체적인 네트워크/TLS 실패 원인 및 현재 주소 제공 여부는 확정하지 않음.
- NOT VERIFIED: 실제 브라우저 조작 및 Windows 사용자 PC 적용/연결.
- 전체 회귀 재실행 없음. 기존 57 FAIL 기록을 전체 PASS로 변경하지 않음.
- 운영 DB·키·영상 변경, 운영 앱 실행, 유료 API·OAuth·SNS 호출, push·PR 변경 없음.

변경: `news/catalog.py`, `gui/sources_routes.py`, `gui/templates/sources.html`,
`tests/test_sources_gui.py`, 이 보고서. DB migration·새 의존성·환경 설정 변경 없음.
