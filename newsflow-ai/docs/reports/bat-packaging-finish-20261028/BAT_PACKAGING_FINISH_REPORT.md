# BAT 패키징 마무리 — 비실행 준비 결과

2026-10-28. **최종 판정: CONDITIONAL.** 허용된 런타임/의존성·경로·서명 어댑터/앵커 준비를 완료했다. 실제 사용자 전달용 NewsFlow ZIP과 앱 실행 인수는 완료하지 않았다.

## 구현·자료

| 대상 | 이번 완료 | 남은 한계 |
|---|---|---|
| 독립 Python3.14.7 | 공식 AMD64 ZIP·Sigstore·SPDX 확보, 공개 ZIP hash 일치·CRC, 원본37개 파일 목록/크기/hash | Sigstore 암호학적 검증, portable import/DLL·앱 실행 미검증 |
| Python 의존성 | 직접13·전체27개 버전과 의존 관계·wheel tags·native 파일명 고정 | wheel 원본/개별 hash·오프라인 bundle 미확보 |
| 배포 경로 | runtime/site-packages/product/controller/React frontend/dist/tools/licenses 매핑 확정 | 실제 앱 payload 조립 안 함 |
| React 경로 | 이전 app/frontend/index.html 표기를 실제 app/frontend/dist/index.html로 정정 | 제품·React 소스/자산은 무변경 |
| 실제 서명 검증기 준비 | Windows ByContent Authenticode reader·주석 컨테이너 digest 바인딩·기존 ZIP verifier 연결 경계·고정 helper pin | 실인증서/실서명 검증 미수행. AST/합성 transport만 확인 |
| 신뢰 앵커 | ZIP 밖 사용자별 security 경로·공개 cert·소유권/ACL·pin 대조·disabled 템플릿 | 실제 provision 없음, 업데이트 비활성 유지 |
| 외부 패키지/샘플 | 샘플12개 제외·기존 원본/rightsVerified:false 보존 | 배포 ZIP 생성 안 함 |

실제 경로와 파일 목록은 [구성·신뢰 설계](PACKAGE_COMPONENTS_AND_TRUST.md), [패키지 매핑](PACKAGE_COMPONENTS.json), [런타임37개](PYTHON_MATERIAL_INVENTORY.json), [의존성27개](PYTHON_DEPENDENCY_LOCK.json), [버전 lock](requirements-runtime.lock)에 보존했다.

Python 원본 보관: `C:/Users/ching/.codex/visualizations/2026/10/16/01a14359-7240-7522-8c13-8bc085201d78/bat-packaging-finish-20261028/python-materials/python-3.14.7-embed-amd64.zip`. 이것은 Python 공식 원본이며 NewsFlow 사용자 배포 ZIP이 아니다. 서명자료/아카이브를 실행하거나 사용자 환경에 설치하지 않았다.

## 새 검증만 실행

**31 PASS / 0 FAIL / 0 ERROR / 0 SKIP**: 새 메타데이터·신뢰 앵커·서명 바인딩·transport·React 경로30개, 새 어댑터→기존 ZIP validator 연결1개를 별도 실행했다. 첫30개도 두 번째에 반복하지 않았다. [JUnit](junit-new-only.xml)·[판정 JSON](RESULTS.json) 참조.

기존78 PASS 계약은 ACCEPTED 증거로 재사용했고 재실행하지 않았다. 기존 CI/설치/FFmpeg PASS도 이전 결과로만 유지했다. 전체 회귀·V3/Guard 진단·디자인·샘플 검증을 반복하지 않았다. 새 PowerShell helper는 문법 AST만 파싱했으며 실제 인증서/API를 호출해 검증한 것은 아니다. 새로운 live application·BAT·미디어 실행0이다.

신뢰 앵커 검사/서명 transport는 unit test double을 사용했다. 실제 Windows ACL·서명 체인·폐기·timestamp·완전한 offline cache-only 동작을 PASS로 표시하지 않는다. 공식 Windows API가 cache/네트워크 상태의 영향을 받을 수 있어 offlineValidationAccepted=false를 유지한다. 테스트 합성 cert/signature를 실제 것으로 배포하지 않는다.

독립 의존성 목록을 만들 때 integration 테스트 venv의 tzdata 누락이 드러나 목록 생성을 중단했다. 설치나 추정 pin으로 채우지 않고 기존 승인 build-runtime 단일 메타데이터를 기준으로 완료했다. 이는 앱 또는 V3 오류 재현이 아니다. 공식 페이지의 gzip 응답은 자료 읽기에서 처리했고 제품 코드와 관계없는 수집 형식 문제다.

## ZIP 생성 가능 여부·외부 조건

**현 상태에서 실제 사용자용 ZIP 완성/전달 가능으로 판정하지 않는다.** 런타임 원본·정확한 구성 목록은 확보했지만 wheel hash/portable 초기화·native DLL·live backend, 실제 배포자 인증서·정식 trust provisioning·offline verification이 남았다. 해당 앱의 공식 보안 정책 문제가 해결된 뒤 별도 승인된 Windows 실행/업데이트 검증이 필요하다.

FFmpeg 기존 후보7 PASS와 source/recipe/고지 묶음은 그대로며 대응 소스/최종 전달 조건은 미완료 상태다. 미확인 샘플12개는 제외한다. 기존 샘플의 권리를 새로 판정하거나 사용자 복사본을 변경하지 않았다.

기존 EXE/Setup/Update 후보와 브랜치는 보존했고 추가 EXE 개발을 하지 않았다. 운영 앱·8765·DB·키·OAuth·미디어·백업은 사용하거나 변경하지 않았다. PR35/main, 승인 디자인, 기존 미추적 validation/도 유지했다. 유료 AI·SNS·외부 사용자 배포0이며 배포 ZIP·앱 실행 경로를 새로 활성화하지 않았다.

기준 브랜치는 `codex/newsflow-bat-distribution-prep`, 시작 SHA는 `e7827837092c4b2548e0efb76a1882ae753225b4`이다. 최종 GitHub HEAD는 완료 응답과 체크포인트에 기록한다. 결과 보존 후 자동 실행/재개 없이 종료한다.
