# 배포자 서명·업데이트 진위·실제 설치 인수 조건

## 구현한 검증 경계

`src/newsflow/distribution/updates.py`는 읽기 전용 검증기다. 업데이트를
다운로드/실행/설치하거나 버전 상태를 바꾸지 않는다.

1. 실제 publisher certificate SHA-256을 신뢰 설정에 사전 고정한다.
2. Authenticode `Valid`, code-signing EKU, timestamp 존재 및 publisher pin을
   서명된 manifest와 설치 EXE **각각** 확인한다.
3. manifest는 서명 가능한 PowerShell 컨테이너의 주석에 든 base64 JSON이다.
   내용은 데이터로 파싱하고 Invoke/Import/dot-source/실행하지 않는다.
4. AppId/channel/version/단조 증가 sequence/file/size/SHA-256을 검사한다.
5. 변조·다른 배포자·timestamp 없음·rollback/replay를 거부한다.

현재 `publisher-trust.json`의 pin은 비어 있고 `updatesEnabled:false`다.
실제 업데이트는 **BLOCKED**이며 self-signed 테스트 인증서를 신뢰 저장소에
설치하거나 가짜 배포자 서명으로 활성화하지 않았다.

## 아직 구현/인수하지 않은 부분

- 실제 배포자 신원 확인·코드 서명 인증서/키 보관·CI signing service·timestamp
  정책과 인증서 교체/폐기 절차.
- 실제 서명된 EXE/Setup/manifest의 체인·timestamp 검증 성공.
- 보호된 staging directory, 전체 부모 경로/reparse 검사, 검증부터 apply까지
  파일 교체 방지, 원자적 설치 활성화 및 성공 후 sequence high-water 저장.
- 실제 다운로드/업데이트 적용기. 현재 검증기가 자동 업데이트인 것은 아니다.
- 재설치 시 version 상태를 잃지 않는 rollback 정책, DB migration/실패 복구.
- SmartScreen 평판·백신 실행 관찰. 서명만 있으면 경고가 반드시 사라진다고
  보장하지 않는다.

업데이트 unit test의 verifier는 명시적인 stub이다. unit PASS를 실제
Authenticode 성공으로 보고하지 않는다. 인증서 저장소의 개인 키를 열람하거나
새 신뢰 루트·방화벽/백신 예외를 설치하지 않았다.

## 설치 인수 구분

새 CI는 임시 Windows Runner에서만 기존 onedir와 Inno 정의를 사용한다.
앱을 실행하지 않고 설치 EXE 두 버전을 컴파일해 신규 설치·동일 payload의
installer-version 업데이트·제거·재설치를 수행하도록 했다.
사용자 파일은 설치 폴더 밖의 합성 디렉터리에 두고 byte 보존을 확인한다.
작업 앱/개발 도구/실제 키를 운영 PC에 설치하지 않는다.

이 검증이 통과해도 다음은 별개다:

- 실제 Windows11 새 일반 사용자/표준 권한에서 설치·최초 실행·종료·재실행.
- Python/Node 없는 새 PC, 다른 Windows SID의 HTTP·파일·DPAPI 접근 거부.
- 실제 구제품 DB를 사용하지 않는 합성 구버전→신버전 migration·실패 rollback.
- 실행 중 업데이트·누락/추가 DLL·원자적 버전 교체·전원 중단.
- 실제 OS DPI4종, 휴먼 음성 품질.

CI compiler 미확보나 해시 변경은 BLOCKED/FAIL로 남기고 자동 허용/재설치로
우회하지 않는다. EXE/Setup/ZIP·합성 DB·암호문·로그는 공개 artifact로 올리지
않고, 비민감 JSON 검사 결과만 보존한다.

공식 참고: [Get-AuthenticodeSignature](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature),
[timestamp](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures),
[Inno lowest 권한](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).
