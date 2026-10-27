# 검증 전용 앱 초기화 실행 정책

상태: 구현 준비 / **보안 실행 NOT VERIFIED**. Guard 거절 후 권한을 추가하거나 재시도하지 않았다.

| 권한 | 최소 범위와 근거 | 구현 상태 |
|---|---|---|
| 앱/런타임 소스 읽기 | main.py의 import, templates/static, frontend/dist, Python runtime 및 검증 도구의 고정 소스 | 앱 정책에 구현. 정책 등록 이전 gate의 검증 도구 읽기와 불일치하여 BLOCKED |
| 파일 쓰기 | Runner TEMP의 단일 신규 합성 workspace만. mkdir/open/rename/delete 검사 | 구현 / 미실행 |
| 경로 | UNC/ADS/Device/상대 traversal·credential 파일·reparse 조상 거부. 링크 생성 및 directory move 거부 | 구현 / 미실행. 기존 native handle 검사는 재사용 |
| SQLite | 등록한 newsflow.db와 sqlite-probe.db만. 연결·트랜잭션·재열기 | 구현 / 미실행 |
| SQLite 우회 | URI·임의 factory·foreign Connection·ATTACH·DETACH·extension·writable_schema·파일 temp PRAGMA 거부 | 구현 / 미실행 |
| DB 초기화 | 실제 create_app의 migrate(engine)는 새 합성 DB에만 적용. 운영 migration 없음 | 실행 차단 |
| 네트워크 | 등록한 127.0.0.1 소유 socket probe와 정확한 asyncio socketpair self-pipe만. 임의 loopback/8765/DNS/IPv6/외부 IP 거부 | 구현 / 미실행 |
| 프로세스 | 필요 없음. shell/EXE/subprocess/운영 프로세스 제어 전부 거부 | 구현 / 미실행 |
| 스레드 | 명시적 read-only ASGI 문맥의 실제 AnyIO I/O worker 최대 2개만. 그 외 Thread/raw thread 거부 | 구현 / 미실행 |
| FileLock | 기존 Rtl bridge의 등록된 합성 scope. autopilot/collection/render/ai-video/claude-feed-card/feed-image-generation/top3-feeds/scheduler/smoke 잠금 이름 | 준비 / 현재 미검증. 기존 28 PASS는 이전 결과 |
| native | 기존 고정 함수만. 추가 DLL/DPAPI/함수는 거부하고 자동 허용하지 않음 | 새 허용 0 |
| 비밀값 | 상속 환경을 Windows 최소 값으로 교체, UserProfile/AppData/TEMP 합성 경로, explicit synthetic Settings.secret_key | 준비 / 런타임 확인 미완료 |
| 자동 작업 | automatic_start=True는 기존 복구 분기. lifespan에 진입하지 않아 scheduler/calendar start를 호출하지 않음 | 정적 확인 / 실제 init 차단 |
| API | FakeRSSAdapter 주입. 유료 생성/게시 경로는 호출하지 않음. 기타 provider 객체가 생성돼도 외부 네트워크/키 접근 차단 | 실제 init 차단 |
| React/API | 5개 shell·JS/CSS 및 4개 module JSON을 in-process ASGI로 검사할 계획. 실제 서버/브라우저 실행과 구분 | NOT VERIFIED |

이 정책은 신뢰하는 합성 CI harness의 경계이며, 악성 Python reflection이나 C 확장 내부의 모든 OS 호출을 격리하는 OS 보장을 하지 않는다. 생성·게시 worker와 운영 권한을 허용한 정책이 아니다.
