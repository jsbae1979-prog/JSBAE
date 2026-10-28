# 실제 Windows 표준 사용자 격리 결과

**Windows Server 2025 CI 실제 두 SID: PASS. Windows11 소비자 계정/GUI: NOT VERIFIED.**

[최종 CI run40644408628](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40644408628),
코드 `011833af86987ea0e8acf430dac8a573f1ce1816`.
Python3.14.7, GitHub hosted `windows-2025-vs2026` VM에서만 실행했다.
운영 Windows11 계정·프로필·DB·키를 사용하지 않았다.

## 실제 계정과 보호 경계

- 무작위 이름/비밀번호의 새 로컬 사용자2개를 만들고 Users 그룹에만 넣었다.
  각 자식은 실제 token SID가 생성한 계정과 일치함을 확인했고 관리자 아님을 확인했다.
  비밀번호·실제 SID·cookie/bootstrap·DPAPI blob은 공개 로그나 artifact로 내보내지 않았다.
- 소스/샘플의 읽기 복사본만 제공하고, 제품의 `private_directory`/
  `distribution_profile`로 사용자별 보호 DACL 폴더를 생성했다.
- 기존 제품 `Samples`와 AppSetting SQLAlchemy 테이블로 실제 SQLite의 숨김/복사를
  처리했다. 원본 catalog/사용자 데이터/제품 schema는 변경하지 않았다.
- A/B는 각각 CurrentUser DPAPI의 합성 문자열을 암복호화했다.
  B에는 **의도적으로 공유한 A의 합성 암호문 복사본만** 주어 교차 복호화 거부를 확인했다.
- 각 실제 사용자 프로세스는 제품 `LocalAccess`로 감싼 작은 합성 ASGI endpoint를
  loopback에서 열었다. 실제 전체 앱/API factory나 GUI를 실행한 검증은 아니다.

| 항목 | 실제 결과 |
|---|---|
| A/B 서로 다른 실제 SID·표준 사용자 | PASS |
| B→A DB 파일 읽기 | Permission denied, PASS |
| B→A SQLite read-only open/query | CANTOPEN, PASS |
| B→A 사용자 샘플 복사본 읽기 | Permission denied, PASS |
| B→A CurrentUser DPAPI blob 복호화 | native 거부, PASS |
| B→A 익명 HTTP 요청 | 403, PASS |
| B의 세션을 A cookie 이름으로 보낸 HTTP 요청 | 403, PASS |
| A/B 자기 HTTP 세션 | 각각200, PASS |
| 실제 동시 listener | 59187 / 59198, 운영8765 미사용, PASS |
| 사용자별 샘플 숨김·복사 | 분리됨, 반복 복사1개, A 상태에 B 변경 없음, PASS |
| 정상 서버/프로세스 정리·테스트 계정 제거 | PASS, 강제 정리false |

음성/GUI/설치 전체 회귀가 아니라 이번 사용자 격리 경계만 새로 검증했다.
음의 파일/API/DPAPI 검사는 B→A 대표 방향이다. 역방향의 모든 음의 동선을
별도로 실행했다고 주장하지 않는다. 관리자·동일 사용자 악성 코드까지
차단하는 보안 경계라고 해석하지 않는다.

## 증거와 이력

- `real-user-results.json`, `cleanup-results.json`: 실제 실행 결과.
- [artifact12797261365](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40644408628/artifacts/12797261365): JSON2개만.
- ZIP digest `6ec1d14762a812e2935c1a7e1d4e93a6b7de0a6bc329e766b4543bad5860eb84`.
  GitHub metadata/log digest와 내려받은 파일 SHA-256 일치.
- 초기 run40643879815는 Windows Description48자 제한을 넘긴 검증기 설정으로 실패했다.
- run40644220266는 실제 SQLite CANTOPEN 거부를 숫자로 잘못 분류해 실패했다.
  이름 있는 상수로 고쳤다. 이 실패 run의 강제 정리 경로에서도 예외가 나
  완전한 정리 증거를 인정하지 않는다. 두 run 모두 일회용 CI VM이며 운영 PC와 무관하다.
- 최종 run은 정상 종료·계정 제거true/강제 정리false다. 실패 이력은 성공으로 덮지 않았다.
  skip/xfail·정책 완화·운영 계정 impersonation은 하지 않았다.

## 남은 실제 Windows11/설치 범위

기존 run40640414466의 실제 Setup 신규 설치·동일 payload의 설치 버전 갱신·
제거/재설치·합성 파일 보존 PASS는 그대로 재사용한다. 이번에 재빌드하지 않았다.
현재 UI/제품/설치 정의가 바뀌지 않았으므로 전체 Python/Guard/GUI를 반복하지 않았다.
Windows11 새 표준 사용자에서 전체 EXE 최초 실행·종료·재실행, 실제 제품 DB
migration/업데이트 실패 rollback, OAuth callback/동적 port의 실제 계정 호환성은
NOT VERIFIED다. 기존12화면 Windows11 GUI PASS를 새 desktop 진입점의 성공으로
확대하지 않는다.
