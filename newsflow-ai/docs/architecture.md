# Phase 1 아키텍처

## 계층과 실행 흐름

```text
GUI: Jinja2 / local CSS / JS polling
  -> FastAPI routes (입력 검증, 검색, 설정)
  -> CollectionCoordinator (OS file lock, background thread, recovery)
  -> NewsService (per-source transaction, duplicate provenance, scores)
  -> Collector (defusedxml + feedparser; title/summary/link only)
  -> RSSAdapter protocol
     -> PublicRSSAdapter (robots + redirect policy)
        -> PublicTransport (public DNS validation, pinned socket, verified TLS)
     -> FakeRSSAdapter (offline fixtures)
  -> SQLAlchemy -> SQLite (WAL, foreign keys, UTC adapter)
```

애플리케이션 팩토리가 설정·DB·마이그레이션·수집 어댑터를 연결합니다. UI가 외부 서비스를 직접 호출하지 않습니다. 라이프사이클 종료 시 수집 스레드를 종료하고 DB 연결을 닫습니다. 셧다운은 현재 진행 중인 유한 RSS 작업을 기다릴 수 있습니다.

## 데이터 모델

- NewsSource: 공개 피드 URL, 이름, 활성 여부, 등록시각.
- NewsArticle: 제목, RSS가 제공한 원문 링크, 중복 비교용 canonical URL, 대표 출처, 요약, 카테고리, 확인 가능한 발행시각, 수집시각.
- ArticleMention (추가): 같은 제목으로 묶인 다른 출처의 링크·출처명. 중복 제거 이후에도 복수 출처 평가의 근거를 보존합니다.
- CollectionRun: 실행 상태, 시작·종료시각, 신규/중복/성공/실패 수.
- ArticleScore: 0~100점 합계, 평가 가능한 최대 합계, 항목별 nullable 점수·근거·평가 상태, 평가시각.
- AuditLog: 작업·출처 참조, 이벤트, 레벨, 민감정보를 제외한 메시지, 기록시각.
- AppSetting (추가): GUI에서 변경한 요청 타임아웃.
- alembic_version: DB 스키마 revision.

DB에는 UTC를 naive datetime으로 직렬화하지만 타입 어댑터가 UTC-aware 값을 반환합니다. timezone 없는 입력은 거부합니다. 발행시각을 얻지 못하면 NULL입니다. API와 UI는 UTC를 명시합니다.

## 원자성·실패 모델

피드의 항목 전체를 먼저 파싱합니다. 한 출처의 기사/중복 링크/성공 로그를 한 트랜잭션에 저장하고, 예외가 나면 롤백 후 별도 오류 로그를 남깁니다. 이후 다른 출처 수집을 계속합니다. 완료 상태는 `success`, `partial`, `failed`, `empty`; 크래시 후 `interrupted`입니다. 전체 수집을 하나의 트랜잭션으로 묶지 않은 것은 부분 성공을 보존하기 위해서입니다. 대표 기사는 삭제하지 않습니다.

파일 잠금은 요청 처리 전에 확보해 동시 수집을 409로 거부합니다. 파일 잠금 자체는 OS가 크래시 시 해제합니다. 다른 프로세스가 잠금을 소유한 경우 그 실행을 중단 상태로 변경하지 않습니다. 공유 네트워크 파일시스템의 잠금 동작은 지원 범위 밖입니다.

## 점수·중복 정책

URL 중복은 unique canonical URL로 차단하고 알려진 추적 파라미터만 제거합니다. 원본 URL은 별도로 보존합니다. 제목은 Unicode 정규화 후 비교하며 날짜가 확인되면 72시간 범위, 유사도 0.92 이상, 숫자 사실 일치 조건을 사용합니다. 날짜를 모르면 정규화된 정확 일치만 묶습니다. 중복 비교는 현재 O(기사 수 × 신규 항목 수)로 Phase 1의 로컬 규모를 대상으로 합니다.

RSS 근거 없는 항목은 nullable 상태로 저장합니다. 출처 이름은 RSS source 메타데이터 또는 등록 피드 이름을 이용하므로 실제 독립 언론 여부를 완전히 검증하지 못합니다. 분류·중요도·영상 적합성·국내 연관성은 명시된 키워드 기반 휴리스틱입니다. 점수는 수집 종료 시 평가하며 탐색 화면에서 실제 조회수로 표현하지 않습니다.

## 보안 경계

기본 GUI는 127.0.0.1:8765. 외부 공개 바인딩은 설정 검증에서 거부합니다. 상태 변경은 CSRF 서명 토큰과 cookie 일치, Origin과 Host 검증이 필요합니다. CSP로 외부 스크립트와 프레임 삽입을 차단합니다. 로컬 사용자의 악성 프로세스까지 방어하는 인증체계는 아닙니다.

외부 요청은 등록/리디렉션 URL 문법 검사 → 모든 DNS IP 검사 → 검증된 IP 직접 연결 → 원래 호스트명을 이용한 TLS 인증서 검증 순서입니다. DNS rebinding 시 두 번째 조회를 하지 않습니다. 사설·예약·멀티캐스트 주소와 기본 포트 외 연결을 금지합니다. DNS 조회는 요청자가 제한시간 이후 빠져나올 수 있도록 daemon resolver를 사용합니다. OS DNS 작업 자체를 강제로 취소하는 것은 지원하지 않습니다. 제한 환경에서 보호를 우회해 실패를 성공으로 바꾸지 않습니다.

robots.txt 확인 실패는 보수적으로 수집을 중단합니다. 리디렉션 목적지마다 정책을 다시 확인합니다. RSS 피드 이용 권한은 운영자가 확인하도록 GUI에서 동의를 요구합니다. 별도의 robots request-rate/crawl-delay 대기는 구현하지 않아 해당 출처는 실패 처리합니다.

## 구조 변경 이유

요구한 기본 폴더 구조를 유지하되 기사 상세 템플릿, 보안·실제 네트워크 테스트, XML fixtures, requirements-dev.lock를 추가했습니다. 마이그레이션은 설치 패키지에서도 접근 가능하도록 `newsflow/db/migrations/` 안에 두었습니다. DB 모델은 중복 provenance와 설정 영속성을 위해 두 테이블을 추가했습니다.
