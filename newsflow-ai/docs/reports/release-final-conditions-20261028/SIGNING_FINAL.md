# 실제 배포자 인증서·업데이트 진위 최종 준비

**실제 인증서: 현재 PC의 확인한 personal store에서0개. 공개 배포: BLOCKED.**

CurrentUser/My 및 LocalMachine/My의 code-signing 인증서 공개 메타데이터만
조회했다. 각각 전체/현재 유효/private-key binding 수0이다. 개인 키·PFX·
OAuth·API 키를 열지 않았고, HSM/외부 signing service의 존재까지 조사했다고
주장하지 않는다. 저장소의 publisher pin은 비어 있으며 updatesEnabled:false다.
`CERTIFICATE_AVAILABILITY.json` 참조.

## 이미 구현된 검증 재사용

기존 `updates.py`는 publisher SHA-256 pin, Authenticode Valid, code-signing EKU,
timestamp, manifest/설치파일 digest·size·appId/channel·단조 sequence를 검증한다.
manifest의 PowerShell 컨테이너를 데이터로만 파싱하고 실행하지 않는다.
인증서 미설정·unsigned·다른 배포자·timestamp 없음·변조·replay/rollback은
거부하는 기존28개 계약 검증을 재사용했다. 이는 실제 서명 성공이 아니다.

## 실제 인증서 확보 후 수행할 절차 — 이번에 실행하지 않음

1. 배포자 법적 신원·인증서 issuer/EKU·유효기간·키 소유/사용 권한을 확인한다.
   테스트/self-signed 인증서를 Windows 신뢰 저장소에 추가하지 않는다.
2. 관리된 실제 signing key로 고정 EXE/Setup에 SHA-256 서명과 신뢰할 timestamp를 적용한다.
   SignTool의 인증서 선택용 SHA-1 thumbprint와 앱 trust의 인증서 RawData SHA-256
   pin은 서로 다르다. 자동 `/a` 선택이나 임의 첫 인증서를 배포자로 확정하지 않는다.
3. `signtool verify /pa /all /v` 및 제품 verifier로 배포자·체인·timestamp를
   독립 확인한다. timestamp 서버 URL은 인증서 공급자의 확인된 주소를 사용한다.
4. manifest와 Setup 각각 서명·pin·digest를 확인한다. 앱별 불변 파일 목록과
   버전/sequence·배포 채널을 연결한다. 확인 전에 업데이트 enable 플래그를 켜지 않는다.
5. 승인된 업데이트를 보호 staging에서 검증하고 설치 성공 후에만 원자적으로
   active version/high-water를 저장한다. 실패 시 이전 버전·DB·키·미디어를 보존한다.
   이 실제 apply/migration/rollback 구현과 인수는 아직 완료가 아니다.

서명 전제 미충족인 현재는 기존 검증기가 읽기 전용이며 설치를 실행하지 않는다.
따라서 서명 거부를 통과시키기 위해 테스트 인증서·임의 pin·무서명 실행 예외를
만들지 않았다. 이전 설치 모형13 PASS는 파일 보존 모델 증거이고, 실제 제품의
업데이트 실패 rollback/SmartScreen 성공 증거가 아니다.

자세한 기존 설계: [서명·업데이트 준비](../distribution-gates-20261028/RELEASE_SIGNING_PLAN.md).
공식 기준: [Authenticode](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature),
[timestamp](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures).
