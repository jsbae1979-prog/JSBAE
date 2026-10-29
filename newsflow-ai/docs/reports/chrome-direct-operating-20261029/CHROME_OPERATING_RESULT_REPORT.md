# Chrome 자동 열기 운영 적용 및 정상 인증 결과

**최종 판정: ACCEPTED — 승인된 Chrome 자동 열기 적용·Stop/Start1회·인증·세 제작실 표시 범위.** 유료 생성/API 계정 권한·SNS 기능의 실제 실행 인수는 포함하지 않는다.

## 기준과 적용

- 브랜치 `codex/newsflow-bat-distribution-prep`.
- 승인된 코드 커밋 `8e1043f430a8cc17b07726f1e8cb3cbd5fadde01`의 Chrome 직접 열기 helper와 READY 후 호출 부분만 운영 controller에 적용했다.
- 운영 경로 `C:/NewsFlowAI`, 데이터 `C:/Users/ching/AppData/Local/NewsFlowAI-BAT/v1`, 주소 `http://127.0.0.1:18768`.
- 현재 운영본 전체를 개발본으로 덮어쓰지 않았다. 기존 운영 고유 코드를 보존하고 **controller파일1개 및 layout의 해당 파일 크기/SHA 항목만** 변경했다. 실제 소스 diff는 `APPLIED_CHROME_DELTA.patch`에 보존했다.
- launch.json은 bytes/SHA 그대로, openBrowser=true. 수정 파일들의 owner/group/DACL도 불변. 다른 layout 항목은 동등 비교로 불변 확인했다.

| 파일 | 적용 전 SHA-256 | 적용 후 SHA-256 |
|---|---|---|
| app/controller/bat_distribution/windows_live.py | eeb245b15c817d000823e15848ea669e8d4f567038c7d3ff0d5c07fb8e28281a | 6fa06664b22c6394f3b063c764356de237e2a79fde2521a6f380d65b11454bc3 |
| app/layout.json | f90b5a0207cb4af92b2b4c37c570d160c53b7bca5dd5231b3b550a218facf011 | 619868c2f6d82df1501473ada5d72f071389ef4d6275d4aacb567a9db9ac112f |

## 실행·인증·GUI

| 항목 | 신규 결과 및 증거 종류 |
|---|---|
| 기존 PID31492 정상 Stop | PASS, Stop BAT exit0, 소유 프로세스 정상 종료 |
| 정지 상태 백업 | PASS,36파일, SQLite backup의47개 테이블 내용hash 일치 |
| 새 Start | PASS,1회만, READY |
| 현재 앱 | **PID35844**,STILL_ACTIVE,18768 수신 확인 |
| Chrome 직접 열기 | PASS,앱 실행 결과 requested=true/accepted=true/browser=chrome |
| Chrome 정상 인증 | **PASS — 사용자 직접 확인** |
| 뉴스 쇼츠 제작실 | **PASS — 사용자 직접 화면 표시 확인** |
| 이미지 제작실 | **PASS — 사용자 직접 화면 표시 확인** |
| 캐릭터 쇼츠 제작실 | **PASS — 사용자 직접 화면 표시 확인** |

사용자 응답: **“인증·세 제작실 모두 정상”**. 이를 브라우저 자동화 결과로 표시하지 않는다. 이전 URL 판별 제한으로 브라우저 자동화를 반복하지 않았고, 이번 GUI 증거는 명시적인 사용자 수동 확인이다. 추가 스크린샷·요청 헤더·쿠키·토큰 수집은 하지 않았다.

READY 후 앱 자체가 설치된 Chrome에 새 session launch URL을 직접 전달했다. 확장 goto/주소창 자동 입력/Edge 쿠키 이전/만료값 재전송은 하지 않았다. Chrome 실행 수락만으로 인증 성공을 판단하지 않고, 사용자 GUI 확인을 별도로 받았다. 기존120초·one-time claim·HttpOnly/SameSite 정책은 그대로다. 앱은 현재 실행 중이므로 Start의 최종 종료코드0을 주장하지 않는다.

## 데이터·정책 보존

사용자 확인 이후에도 아래 항목을 마지막으로 대조했다.

- SQLite integrity=ok. 전후 **47개 테이블의 모든 내용hash와 건수 동일**. 기존 기사169건·AI처리48·대본6·영상프로젝트7·이미지게시물3건 보존.
- DPAPI 암호문6개와 미디어20개 총26파일의hash/size/mtime 불변. 평문 복호화0.
- 기존169원본 및 백업A/B DB의 기존SHA `238d0aea41bc1377a29b9a1eb4b30f43e9d38ad39bba22e8a2fe31d7e6726287` 모두 동일.
- readOnly=false인 기존 운영 모드 유지. decryptCredentials/automaticJobsEnabled/externalExecutionEnabled=false 유지, 무서명 업데이트 차단 유지.
- LocalAccess/CSRF/Origin/DPAPI/ACL/비용·게시 승인/결과 불명 보호 변경0.
- 실제 공급사 유료API·OAuth·SNS 호출0, 자동화 활성화0, 실제 데이터 시험레코드 추가0.
- 기존 운영 원본/백업/프로그램 삭제0. main/PR35/외부배포 변경0.

비공개 복구 경로: `C:/Codex/NewsFlowAI-IsolatedReview/chrome-direct-operating-20261029/`. 변경 전 controller/layout/launch의 bytes·SHA·ACL과 정지 백업은 보존했다. 기존 복원 검증 증거를 재사용했고, 이번에는 운영 DB 또는 원본/A/B에 복원·migration을 수행하지 않았다. 이 private 자료·DB·암호문·미디어·인증파일은 Git에 포함하지 않는다.

## 검증 재사용과 종료

기존 Chrome 직접 열기 합성 집중 검사 **13 PASS를 재사용**했으며 새로 재실행한 결과로 표시하지 않는다. 이번 신규 증거는 실제 운영 적용·정상 Stop/Start·Chrome 실행 수락·사용자 인증/GUI 확인·전후 보존 대조다. 전체 회귀/패키징/보안 감사/V3 진단은 반복하지 않았다.

허용된 Stop1회/Start1회만 완료했다. 현재 PID35844와18768 운영을 유지하고 추가 재시작·생성·게시·배포 없이 종료한다. 기존 미추적 `validation/` 자료도 그대로 보존한다.
