# Windows 11 실환경 검증 체크리스트

현재 모든 아래 항목은 사용자 Windows 머신에서 실행 전 **NOT VERIFIED**입니다. Cloud의 Linux subprocess/경로 테스트나 BAT 정적 검사로 대체하지 않습니다. 각 작업의 PASS/FAIL과 오류 코드·기사 수를 기록하고 키/토큰·사용자 이름/전체 로그는 공유하지 마세요.

## 환경 정보

Windows 11 버전, Python 3.12 버전/아키텍처, Chrome/Edge 버전, JSBAE 브랜치 `feat/newsflow-phase1`, `git rev-parse HEAD`, 사용 포트(기본 8765)를 기록합니다. main은 병합하지 않습니다.

## 설치/시작/종료

1. 한글·공백을 포함한 사용자 폴더에서 checkout/ZIP 압축을 풉니다. Python 3.12/Python launcher 설치 확인 후 run.bat 더블클릭.
2. 새 `.venv` 생성과 패키지 설치가 완료되었는지 확인. 잘못된 Python 버전/인터넷 차단 환경에서 서버를 성공으로 표시하지 않는지 확인. 비밀값이 콘솔/로그에 없는지 확인.
3. 브라우저 주소창에 `http://127.0.0.1:8765`를 직접 입력. `/health` 응답 `{"status":"ok","phase":1}` 확인.
4. 같은 BAT를 다시 실행해 기존 서버를 종료하지 않고 중복 오류가 안내되는지 확인.
5. 기존 서버를 Ctrl+C로 종료해 포트가 해제되는지 확인. 사용자 데이터가 남아 있는지 확인.
6. 다른 프로그램이 8765를 사용하는 경우 충돌 안내/종료 코드 실패와 자동 포트 변경 없음 확인. 모르는 프로세스를 강제 종료하지 않습니다.
7. 재실행 시 의존성 설치가 불필요하게 반복되지 않는지 확인. manifest가 갱신되면 설치 성공 후 실행하는지 확인.
8. `%LOCALAPPDATA%\NewsFlowAI`에 DB·설정·session.key·logs·content·videos가 있고 소스에는 사용자 데이터가 생성되지 않는지 확인. 사용자 전용 ACL 확인.

## 데이터 이전

서버 종료 후 기존 data 전체 백업. `.venv\Scripts\python.exe -m newsflow.migrate_data --source ".\data"` 실행. 원본 보존·새 DB의 기존 기사/설정/키 유지, 대상 이미 존재 시 덮어쓰기 거부, 모든 SQLite 핸들이 닫혀 잠금 오류 없이 임시 폴더 정리되는지 확인.

## GUI

- Dashboard 기사 수, 최근 수집, 분포, 추천 TOP 10, 실행 이력.
- News Explorer 검색 및 시작/종료 날짜·카테고리·출처·정렬·페이지 이동.
- News Detail 출처 provenance, RSS 요약, 원문 링크, 점수의 미평가와 평가 근거.
- Settings 출처 등록, 비활성화/권한 확인 후 활성화, 타임아웃 저장, 실행/수집 로그.
- 실제 일반 Chrome/Edge 브라우저에서 폼 POST. 개발자 도구 Network의 Origin은 요청 주소와 일치해야 합니다. Cloud에서 관찰한 Origin:null을 허용하도록 변경하지 않습니다.
- 수동 수집 진행 표시·중복 실행 방지·완료 결과·부분 실패/전체 실패 시 기존 기사 보존.
- 작은 창/모바일 emulation에서 가로 넘침, 표시 오류 없음.
- 원격 Origin, 위조/누락 CSRF, 사설 RSS URL이 차단되는지 확인.

## 실제 RSS 저장

이용 조건을 확인한 공개 피드에 대해 다음 두 명령을 각각 실행:

```powershell
.\.venv\Scripts\python.exe -m newsflow.diagnostics --url "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
.\.venv\Scripts\python.exe -m newsflow.diagnostics --url "https://feeds.bbci.co.uk/news/rss.xml"
```

`rss_store=PASS`, 실제 `article_count>0`, `collection_status=success` 및 종료 코드 0인 경우만 PASS입니다. 실패 시 단계 DNS/HTTPS/robots/parse/network와 NOT VERIFIED를 기록합니다. proxy robots HEAD의 HTTP 200만으로 수집 성공을 판단하지 않습니다. 환경 네트워크 변경은 별도 승인 후 진행하며 TLS/SSRF/robots 검사를 생략하지 않습니다.

## 회귀와 승인

README의 개발 의존성 설치 후 `python -m pytest -q -rs`를 실행해 pass/skip/warning/fail 수를 기록합니다. 모든 관찰 결과를 Phase 1A 보고서에 추가한 뒤 사용자에게 Phase 1 최종 승인을 요청할 수 있습니다. 승인 전 main 병합이나 Phase 2 작업을 하지 않습니다.
