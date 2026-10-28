# 실제 배포자 인증서 확보 후 서명 대상·절차

실제 인증서는 외부 확보 대상이다. 현재 시험 인증서를 상용 인증서로 사용하거나
신뢰 저장소에 추가하지 않는다. 이번에 개인 키/실제 API 키를 열지 않았다.
현재 publisher pin 미설정/updatesEnabled:false와 무서명 업데이트 거부를 유지한다.

| 순서 | 대상 | 수행/검증 |
|---|---|---|
| 1 | 최종 onedir NewsFlowAI-Candidate.exe 또는 확정 제품명 EXE | 고정 소스/의존성·최종 산출물 digest와 법적 배포자 연결, SHA256 Authenticode+RFC3161 timestamp |
| 2 | 실제 설치 Setup EXE | 1의 서명 완료 payload를 포함해 컴파일한 후 installer에 서명·timestamp |
| 3 | 업데이트 매니페스트의 서명 가능한 컨테이너 | 서명 완료 Setup의 최종 size/SHA256·appId/channel/version/단조 sequence를 연결한 후 서명 |
| 4 | 함께 배포하는 별도 실행/worker/helper EXE | 목록화·각 소유자/기존 vendor signature 확인. 제3자 바이너리 서명을 자신의 저작권 증빙으로 혼동하지 않음 |

현재 후보는 분리 worker EXE가 없고 같은 EXE의 SAPI operation을 재사용한다.
FFmpeg/ffprobe의 포함 hash는 기존 pin을 유지한다. 정확한 license/source 조건
미충족 상태에서 서명만으로 공개 배포를 승인하지 않는다.

실제 인증서 확보 시:

1. 배포자 법적 신원·issuer·code-signing EKU·유효기간·키 사용권/보관 경로를 확인한다.
2. 공급자가 지정한 신뢰 timestamp URL을 사용한다. `/fd SHA256 /tr <확인된URL>
   /td SHA256` 절차를 적용하되 실제 명령/키 식별자를 로그에 남기지 않는다.
3. `signtool verify /pa /all /v`와 제품 verifier 양쪽에서 체인·배포자·timestamp를
   확인한다. 인증서 선택용 SHA1 thumbprint와 RawData SHA256 pin을 구분한다.
4. EXE→Setup→manifest 순서로 서명 후 size/hash를 확정하고 certificate SHA256을
   신뢰 설정에 고정한다. manifest 내용은 데이터로만 읽고 실행하지 않는다.
5. unsigned/다른 배포자/변조/만료 및 timestamp 문제/replay·rollback 거부를 인수한다.
   모든 조건 확인 전 updatesEnabled를 켜지 않는다.

이번 CI의 private installer/slot 실패 주입은 일회용 VM 검증 도구다.
실제 public update verifier를 호출하지 않는 technical candidate test이며,
무서명 제품 업데이트를 사용자에게 허용하는 경로나 완성된 자동 업데이트가 아니다.
서명된 public updater와 DB migration 이후 rollback은 별도 인수 조건으로 남는다.

공식 참고:
[SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool),
[Authenticode timestamp](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures),
[Get-AuthenticodeSignature](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature).

이번 실제 파일명 목록: product는 각 slot의 NewsFlowAI-Candidate.exe,
기존 일반 private 설치 정의는 NewsFlowAI-Private-Setup.exe, 새 실패 주입
시험 설치 정의의 세 산출물은 각각 다른 디렉터리의 Recovery-Setup.exe다.
Recovery-Setup은 CI 전용이며 public 업데이트 verifier가 허용하는
NewsFlowAI-*.exe 형식의 공개 업데이트로 사용하지 않는다.
공개 제품명/Setup명 확정·서명 매니페스트 생성은 실제 배포 승인 전 단계다.

실제 복사 실패 주입과 성공 설치에는 동일한 최신 Setup을 재사용한다.
