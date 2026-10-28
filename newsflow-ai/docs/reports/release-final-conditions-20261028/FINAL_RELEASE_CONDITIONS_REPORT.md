# 일반 사용자 배포 차단 조건 최종 해소 결과

2026-10-28 · **최종 판정: BLOCKED — 일반 사용자 공개 배포 기준**

이번에는 실제 다른 Windows 사용자 격리 증거와 공식 업스트림 소스3개를
추가 확보했다. 그러나 이미지 권리·전체 GPL 대응 자료·실제 배포자 인증서는
검증되지 않았으며 코드만으로 그 증빙을 만들어낼 수 없으므로 공개 배포를
승인하지 않는다. 기능·디자인·Guard·전체 회귀를 처음부터 반복하지 않았다.

## 1. 작업 기준

- 저장소: `jsbae1979-prog/JSBAE`.
- 시작 HEAD: `ce1142270ae4ab9a3e8ec8bb8ce5e9f9936f23e2`.
- 작업 브랜치: `codex/newsflow-release-evidence-final-20261028`.
- 신규 실제 SID 검증 최종 코드: `011833af86987ea0e8acf430dac8a573f1ce1816`.
- 최종 보고 HEAD는 이 문서가 포함된 Git 로그/완료 메시지로 식별한다.
- 새 변경은 CI 검증 도구2개·전용 workflow 및 보고서다. 제품 `src/`,
  프런트엔드, 샘플 원본, 기존 패키징 정의/완료 브랜치는 변경하지 않았다.
- 기존 미추적 `validation/` 보존. reset/clean/stash/force push 없음.

## 2. 네 영역 판정

| 영역 | 이번 결과 | 최종 남은 조건 |
|---|---|---|
| 샘플12개 | 기존 해시/권리 감사 재사용, 파일별 자체 제작 v2 계획12행 작성 | 전부rightsVerified:false, 원본/입력/상업 재배포 증빙 BLOCKED |
| FFmpeg/의존성 | 실제 빌드와 연결되는 FFmpeg/x264/x265 업스트림 archive3개 확보 | 전체 정적 의존성·패치·recipe/제공 체계 NOT VERIFIED, 공개 배포 BLOCKED |
| Windows 사용자 격리 | 실제 표준 사용자2명·다른 SID로 파일/HTTP/DPAPI·동시 포트·샘플 상태 PASS | Windows Server2025 CI 범위; Windows11 새 실제 사용자/전체 GUI NOT VERIFIED |
| 실제 설치/업데이트 | 기존 CI Setup 수명주기 PASS 재사용 | Windows11 최초 실행·실제 제품 migration/실패 rollback NOT VERIFIED |
| 서명/업데이트 진위 | 현재 PC code-signing cert metadata0, unsigned 차단/서명 절차 유지 | 실제 배포자 인증서·서명·timestamp·적용기 인수 BLOCKED |

## 3. 샘플 권리

새 권리 자료가 제공되지 않아 기존 원본과 매니페스트를 변경하지 않았다.
ChatGPT 출력에 관한 일반 약관이 이 첨부 파일의 생성자·참조 입력·제3자
권리까지 증명하지는 않는다. 파일별 기존SHA, 자체 도형/벡터 제작 방식,
영상 파생 관계, 작성자·source commit·상용 허락·시각 인수 조건을
`SAMPLE_REPLACEMENT_PLAN.json`에 적었다. 새 그림 생성·바이너리 교체·
사용자 복사본 덮어쓰기·rightsVerified 허위 설정은 하지 않았다.
`SAMPLE_RIGHTS_FINAL.md` 참조.

## 4. FFmpeg 소스

기존9.0.2 GPLv3/static 및x264/x265 포함 증거를 재사용했다.
Gyan의 source commit을 전체 SHA로 확인하고 공식 저장소에서 FFmpeg archive를
다운로드했다. x265는 README의g116b875를 개발사 저장소에서 해석했다.
x264는 공식 VideoLAN bare clone의 X264_BUILD165/revision3223 및 version.sh
규칙을 확인해 버전이 맞는 업스트림 후보를 고정했다. source script를 실행하지 않았다.

3개 archive 약20.5MB는 새 로컬 증거 폴더에 보존하고 URL/commit/크기/SHA를
`SOURCE_ACQUISITION_INDEX.json`에 기록했다. Gyan 지원 저장소의 자동 source ZIP을
FFmpeg 소스로 혼동하지 않았다. 기존 README의 외부 구성요소37개를 추적하며,
시스템 라이브러리 예외 여부까지 포함해 필요한 소스/패치/recipe 범위를
확정해야 한다. 해당 binary의 전체 대응 소스 적합성은 여전히 미확인이다.
`FFMPEG_SOURCE_FINAL.md` 참조. 새 LGPL 빌드·인코더·렌더 엔진을 임의 도입하지 않았다.

## 5. 실제 Windows 사용자 격리

[CI40644408628](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40644408628)
**SUCCESS**. 임시 Windows Server2025 VM에서 새 표준 사용자2명을 생성해
실제 SID·관리자 아님을 확인했다. 비밀번호·SID원문·bootstrap/session·암호문은
보고서/로그/artifact로 출력하지 않았다.

B→A의 파일/SQLite/샘플복사본·합성 DPAPI blob 복호화·익명 API·다른 세션
요청을 거부했고, 각각 자기 HTTP200/DPAPI/샘플 숨김·중복 없는 복사는 성공했다.
59187/59198을 동시에 사용했다. 실제 제품의 보호 모듈을 합성 endpoint에
연결한 검사이며 전체 앱/실제 계정 OAuth 성공은 아니다. 정상 종료·테스트 계정
제거true, 강제 정리false다. 역방향 모든 음의 동선/Windows11을 검증한 것으로
확대하지 않는다. `WINDOWS_USERS_FINAL.md`, JSON2개 및 artifact 참조.

초기2개 run은 검증기 Description 길이/SQLite 거부 코드 분류 오류로 실패했으며
그 이력도 보존한다. 두번째 실패 run의 강제 정리는 완전한 증거로 인정하지
않는다. 최종 run은 정상 정리까지 성공했다. 실제 제품 FAIL로 단정하거나
실패 run을 성공으로 덮지 않았고 skip/xfail·Guard 완화는 하지 않았다.

## 6. 설치·업데이트·서명

기존 실제 [설치CI40640414466](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40640414466)의
Setup 신규 설치·동일payload 설치 버전 갱신·제거·재설치·합성 사용자 파일 보존을
재사용한다. 변경 없는 PyInstaller/Inno를 다시 빌드하지 않았다.
실제 구제품 DB migration/실패 rollback·Windows11 새 사용자 최초 실행은
NOT VERIFIED다. 기존12화면 로컬GUI/샘플 MP4/SAPI 결과는 과거 증거다.

로컬 CurrentUser/My 및 LocalMachine/My의 code-signing 인증서 metadata는
각각0개다. 개인 키를 열지 않았고 외부 HSM 서비스까지 확인한 것은 아니다.
실제 publisher pin은 비어 있고 updatesEnabled:false다. 기존 무서명/변조/
rollback 차단 검증과 준비 절차를 재사용했다. 실제 timestamp/서명 성공이나
배포자 신원이 확인됐다고 표시하지 않는다. `SIGNING_FINAL.md` 참조.

## 7. 보호 및 판정

- 운영8765/PID55740 listener 유지, 앱 시작/종료/재시작·운영 HTTP 요청 없음.
- 운영 DB·ledger·설정·API 키·OAuth·미디어·백업 열람/복호화/수정 없음.
  확인한 것은 명시적으로 요청된 공개 인증서 metadata뿐이며 운영 계정으로
  앱/DB/API/DPAPI 검증을 하지 않았다. 계정 생성은 오직 일회용 CI VM에서만 했다.
- src/frontend/기존 패키징 도구 diff0. 승인 디자인12개·샘플12개 원본 무변경.
- PR35 Draft·미병합 및 main 무변경. 기존완료/배포준비 브랜치 보존.
- 유료 AI/OAuth/SNS/예약/실제 운영 업데이트/공개 배포0.
- Windows 사용자 보안28 PASS·네이티브6·설치CI·한국어SAPI·기존GUI12화면/MP4는
  재사용했고 이번 신규 실행 수에 합산하지 않았다.

현재 해소한 것은 **업스트림 소스 확보와 실제 두 Windows SID의 대표 격리
검증**이다. 공개 배포 전에는 샘플 권리 증빙 또는 승인된 대체 자산,
전체 필요한 GPL 대응 자료·제공 체계, 실제 배포자 인증서/서명 인수가 남는다.
Windows11 새 일반 사용자·새 PC 최초 실행·실제 제품 업데이트 실패 복구도
별도 실제 검증이 필요하다. 이 조건을 flags 변경이나 가짜 성공으로 해소하지 않는다.

**최종 BLOCKED.** 개발 증거를 작업 브랜치에 보존하고 운영 전환·PR 병합·
실제 유료 API·SNS 게시 없이 종료한다.
