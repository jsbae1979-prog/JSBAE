# 핵심 제작실 5개 승인 디자인 최종 적용 · 자동 인수

최종 판정: **CONDITIONAL**. 제작실5개의 승인 핵심 패널 배치를 적용하고 Windows 집중 기능 검증을 완료했습니다. **MAJOR0**, 독립 이미지 스타일 미니어처의 작은 차이는 MINOR로 남습니다. 원본의 예시 데이터·완성 미디어를 가짜 운영 결과로 채우지 않았습니다. 실제 Windows11 데스크톱·OS DPI·실계정 생성·운영 배포의 인수는 포함하지 않습니다.

## 1. 브랜치·코드 기준

- 작업 브랜치: `codex/newsflow-core-studios-final-match-20261028`
- 최종 검증 제품/테스트 코드: `9e3861ff2f4869cd5430ab14eed114094fc84e9b`. 이후 보고 커밋은 이 문서·비교 캡처·증거만 보존합니다.
- 기존 제작실 HEAD `8ecf7e29f3d73a598e26d68d388a7a3ec232e0f6`이 관리 화면 완료본 `4580e8943a6e3a19d83ccad34995412f39bc21fa`의 조상임을 확인하고, 완료본에서 새 작업 브랜치를 만들었습니다. 기존 제작실·샘플 이력을 덮어쓰거나 두 기존 브랜치를 변경하지 않았습니다.
- 승인 원본은 GitHub 커밋 `17b81fab2325c4f1757a9e4d8cf88bd287719e4c`의 `CORE_5_APPROVED_MANIFEST.json` 및 해당 Git blob을 직접 읽었습니다. 이전 후보 뉴스 쇼츠/TOP3를 사용하지 않았습니다. [원본 근거](evidence/APPROVED_SOURCE.json)와 `reference/`의 원본 바이트를 보존합니다. 신규 디자인·대체 이미지 생성 없음.
- `validation/` 기존 미추적 폴더 유지. reset/clean/stash/force push·새 PR 생성 없음. 관리 브랜치4580e89·기존 core8ecf7e2·main·PR35 Draft/open/unmerged는 그대로입니다. [원격 상태](evidence/BRANCH_PROTECTION.json).

## 2. 제작실별 적용·시각 판정

| 화면 | 최종 시각 판정 | 이번 구현·보정 | 남은 차이/기능 제약 |
|---|---|---|---|
| 뉴스 쇼츠 | **MATCH** | 최신 TOP3 원본의 전용 전체 폭, 상단 가로 순위3개, 중앙 대본/간편설정+9:16, 하단 제작·저장. 대본 편집/저장본 보기,30·45·60초와 지원 자막3종의 실제 상태 선택. 제작 단계 번호 없음. 하단 제작바가1920 첫 화면 안에 표시됨. | 예시 뉴스·사진·완성 영상·가상 음성 아바타를 넣지 않음. 없는 파일은 빈 상태. 원본의 별도 미지원 자막/화질 옵션을 작동 가능하게 만들지 않음. 실제 글꼴·아이콘의 작은 렌더링 차이. |
| 캐릭터 쇼츠 | **MATCH** | 상단 제작실 메뉴·3단계, 참조/주제/미리보기·실제 견적의3열과 하단 스토리보드. 참조 옆 로봇·고양이·드래곤 소형 선택기. 전체 샘플 갤러리는 하단에 유지. | 합성 검증 참조 PNG·3장면 및 실제 저장 상태를 표시. 시안의5장면/완성클립·가상120크레딧을 만들지 않음. Claude/Seedance/FFmpeg·견적/승인 계약 유지. |
| 독립 AI 이미지 | **MINOR** | 왼쪽 탭/프롬프트·스타일·모델, 중앙 캔버스, 오른쪽2열 이력, 하단 최근 이미지. 샘플3개는 보조 갤러리. 모델·크기·품질·저장·승인·재사용 연결 보존. | 스타일6개 미니어처는 원본의 개별 일러스트 자산이 분리되어 있지 않아 SVG와 범위 제한 색상으로 표현. 캔버스/이력에 샘플을 실제 생성 결과로 넣지 않음. 참조 기반 유료 이미지 편집 생성은 기존 미구현 상태. |
| 뉴스 TOP3 이미지 | **MATCH** | 최신 전용 PNG의 메뉴 없는 전체 폭, 왼쪽 탭·저장 TOP3, 중앙 공통 설정·3개 독립 결과, 오른쪽 문구·출력·검토, 하단 이력. 결과가 없을 때도3개 결과 자리와 상태를 명확히 표시. 개별 뉴스 제작 모드 선택 UI 없음. | FUNCTIONAL_CONSTRAINT: 기존 계약의 실제 문구 수정·출처·게시 검토를 사용. 시안의 로고/날짜/카테고리 숨김·일괄 저장·뉴스 저장/직접입력 모드·공통 스타일 템플릿을 가짜 버튼으로 추가하지 않음. 출처·승인 정책 우선. |
| 뉴스 스튜디오 | **MATCH** | 상단 실제 메뉴, 왼쪽 검색/분야·기사 카드·TOP순위, 중앙 선택 기사·저장 분석·키워드 상태, 오른쪽 출처/TOP3·제작실 연결, 하단 최근 확인. | FUNCTIONAL_CONSTRAINT: 현재 저장 분석 계약에는 별도 키워드 필드가 없어 미제공 상태 표시. 관련 뉴스/즐겨찾기/미지원 분석 탭을 만들지 않음. 기존 요약·선정근거·출처·순위만 사용. 새 유료 분석 없음. |

MATCH는 핵심 배치와 작업 요소의 일치이며 모든 픽셀 동일성이나 미구현 기능의 인수가 아닙니다. 색상·테두리·그림자·SVG·간격은 제작실 전용으로 보정했습니다. 세부 SVG/폰트 렌더링, 실제 자료 양과 안전 안내로 인한 높이 차이는 남습니다. MINOR를 MATCH로 임의 승격하지 않았습니다.

[승인 원본·보정 전후·50%오버레이·차이×3](visual-comparison-final.html) · [배치 수치/색상차이](DESIGN_MEASUREMENTS.json).

1920×1080 및1366×768을 모두 캡처했습니다. 원본은1536×1024(TOP3는1610×977)라 독립 가로·세로 정규화는 왜곡/콘텐츠/폰트 차이를 포함합니다. 차이 수치를 디자인 일치율이나 합격 점수로 사용하지 않았습니다. 원본 PNG와 CI 캡처 바이트는 변경하지 않았습니다.

## 3. 최소 기능 보완 및 재사용

- 신규 `CoreNavigation.tsx`: 보호 화면과 분리된 제작실 실제 라우트 메뉴. 뉴스/캐릭터/이미지 등 기존 이동 함수 사용.
- 신규 `CharacterReferenceSamples.tsx`: 기존 `/api/samples` 및 `/api/samples/{id}/copy`만 사용해 사용자 복사본을 새 작업 참조로 연결. 선택만으로 캐릭터 작업·유료 영상을 생성하지 않음. 사용자별 숨김 상태를 조회 시 반영. 복사·숨김·전체 미리보기는 기존 하단 갤러리 유지.
- 뉴스 대본의 저장본 읽기/현재 편집 전환. 편집 버퍼와 저장 Revision을 섞거나 저장본 보기로 덮어쓰지 않음.
- 간편 길이·자막 버튼은 기존 제작 요청 컨텍스트에 연결. 새 가격 계산/Provider/생성 계약 없음.
- TOP3 결과 미생성3개 자리, 뉴스 카드 순위 및 이미지 이력 빈 상태를 명확히 표시.
- Python·API·DB·migration·사용자 경로·키/OAuth/DPAPI·Guard·CSP·Origin·CSRF·가격·게시 정책 변경 **0**. 원래 `useStudio`, `Command`, `ActionButton/Select` 계약은 공백 정규화 비교에서 동일합니다.
- 기존 대본 저장/Revision 충돌 복구, 수동 장면 편집/승인 모달, 이미지 초안/견적/생성/재사용, TOP3 배치·독립 상태·문구 수정, Claude/Seedance/FFmpeg 상태 기계를 재사용했습니다.

## 4. 이번 집중 검증

| 항목 | 신규 결과 |
|---|---|
| Windows Python | 3.14.7 · Windows Server2025 Actions Runner |
| TypeScript/Vite | PASS · 최종 Windows CI. 로컬 타입 검사도 PASS |
| Windows Chrome | **22 PASS / 0 FAIL / 0 ERROR / 0 SKIP**, Chrome156.0.8078.48 |
| 제작실 캡처 | 5개×2해상도, 실제 저장/승인 모달·Fake 생성 후 캡처 포함 |
| 보호 화면 | **14/14** 계산 배치·스타일 동일. 원본 텍스트 비교도 보존. 일부 이전 라이브러리 캡처의 `미리보기 불러오는 중` 문구는 비동기 캡처 시점 차이이며 기하/색상/글꼴 변화0 |
| 보호 소스 | **13 PASS / 0 FAIL** 비교 범주 · 운영 자료 재조회/샘플 바이너리 재검사 없음 |
| 샘플 유지 | 조회 인벤토리 **12개(이미지9/MP4 3)**,3개 캐릭터 참조 선택 및 기존 작업 보존. 원본/매니페스트 변경0 |
| 외부 요청/페이지 오류 | 페이지 경유 외부 요청0, JS오류0. Chrome 자체 OS 백그라운드 통신 완전 차단 검증과 구분 |
| 프로세스 정리 | 정상 종료, 강제 정리false, Chrome0·미처리 요청0·Python exit0 |
| 실제 Windows11 GUI·OS DPI100/125/150/200% | **NOT VERIFIED** |
| 전체 로컬 Python 앱/새 MP4 합성/실제 API·SNS | 이번 미실행. 기존 증거와 구분 |

[최종 CI](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40621402316) · [Chrome 결과](evidence/after/gui-results.json) · [Python ASGI](evidence/after/backend-summary.json) · [정리](evidence/after/process-cleanup.json).

실제 React를 실행한 Chrome 요청을 기존 승인된 합성 file IPC로 실제 Python ASGI/TestClient·SQLite에 전달했습니다. 완전한 Windows11 데스크톱 앱/실TCP 서버/OS DPI 검증으로 확대 해석하지 않습니다. localhost18765만 논리 테스트 origin으로 사용하고8765는 조회·점유하지 않았습니다. 기존 승인 fixture/Guard 경계 수정·권한 추가 없음. Paid/SNS 실제 호출0. Fake생성 이미지와 운영실적은 분리됩니다. 기존 Vite의 런타임 폰트 경로/use-client/500KB 묶음 경고는 남아 있으며 빌드 실패로 숨기거나 새 해결로 보고하지 않습니다.

| 집중 검사 | 결과 |
|---|---|
| news search, source and existing analysis to shorts | PASS |
| shorts real script save, reopen and Revision conflict | PASS |
| shorts simplified settings and separate production approval | PASS |
| character reference, saved story, storyboard and unknown guard | PASS |
| character topic and PNG registration through actual app | PASS |
| independent image options, actual draft save and reopen | PASS |
| independent Fake generation requires approval, preview and reuse gate | PASS |
| TOP3 actual stored analysis, independent Fake outputs and review separation | PASS |
| viewport shorts 1920 | PASS |
| viewport characters 1920 | PASS |
| viewport images 1920 | PASS |
| viewport images-top3 1920 | PASS |
| viewport news 1920 | PASS |
| viewport shorts 1366 | PASS |
| viewport characters 1366 | PASS |
| viewport images 1366 | PASS |
| viewport images-top3 1366 | PASS |
| viewport news 1366 | PASS |
| five approved studio shell and tab geometry | PASS |
| desktop production and storyboard stay in initial viewport | PASS |
| script saved-view preserves unsaved editor and simple option approval boundary | PASS |
| three sample character references available without replacing saved job | PASS |

대본 저장·재열기·Revision 충돌 시 편집 보존, TOP3→대본 연결 시 분석 건수 불변, 승인 체크 초기false, 미승인/결과불명 생성 비활성, Fake 독립 이미지 및3개1080×1350 결과, 완료 후 재요청 차단, 샘플 참조 선택 후 기존 캐릭터 작업 보존을 확인했습니다. 새 MP4 생성/재생·FFmpeg 전체 흐름은 이번 변경하지 않아 기존 제작실20PASS 및 샘플21PASS 증거를 재사용하며 신규 검증으로 합산하지 않습니다.

보정 전 기준은 [run40619701492 before](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40619701492), 중간 보정21PASS는 [run40620438850](https://github.com/jsbae1979-prog/JSBAE/actions/runs/40620438850). 소스 변경 후 관련 범위만 다시 검증했고 보정 전 캡처는 재실행하지 않았습니다. 기존 제작실GUI20PASS/집중CI59PASS/샘플API9PASS·GUI21PASS/관리최종Chrome15PASS는 과거 승인 증거입니다. 전체 Python 회귀·보안 감사·샘플 해시 검사를 반복하지 않았습니다. 기존 Windows identity 시간 초과 위험도 해결된 것으로 표시하지 않습니다. skip/xfail 추가 없음.

## 5. 변경 파일

- `.github/workflows/newsflow-core-final.yml`
- `newsflow-ai/frontend/src/studio/core/CharacterReferenceSamples.tsx`
- `newsflow-ai/frontend/src/studio/core/CharacterStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/CoreNavigation.tsx`
- `newsflow-ai/frontend/src/studio/core/CoreStudios.tsx`
- `newsflow-ai/frontend/src/studio/core/ImageStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/NewsShortsStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/NewsStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/TopThreeImageStudio.tsx`
- `newsflow-ai/frontend/src/studio/core/core-studios.css`
- `newsflow-ai/frontend/src/studio/core/shared.tsx`
- `newsflow-ai/tools/studio_v3/integration/core_final.browser.cjs`

신규 보고서 폴더는 `newsflow-ai/docs/reports/core-studios-final-match-20261028/`이며 승인 원본 복사·전후 캡처·비교 파생 이미지·JSON 측정·테스트/보호 증거를 포함합니다. 문서 브랜치의 원본을 이동하거나 수정하지 않았습니다.

## 6. 보호·남은 조건

- 홈/콘텐츠 제작 홈·관리5개는 소스 차이0 및 두 viewport의 계산 배치/스타일 동일입니다. `.core-studio`가 있는 라우트에서만 전용 셸/CSS가 적용됩니다. [보호 소스](evidence/PROTECTION.json) · [보호 캡처 비교](evidence/PROTECTED_CAPTURE_COMPARISON.json).
- 샘플12개 원본/매니페스트, 기존 사용자 복사본, 운영 앱/8765·DB/ledger·설정·키/토큰·미디어·백업에 쓰기/테스트 입력 접근 없음. 보존 확인을 위해 운영 비밀값을 열거나 DB 해시를 새로 읽지 않았습니다. 과거 보존 증거를 재사용합니다.
- 운영 재시작/배포·main/PR35변경·merge·유료API/OAuth/SNS·설치형 배포를 수행하지 않았습니다. 실제 계정 사용 권한·가격·생성 결과는 새로 검증하지 않았습니다.
- 독립 이미지 스타일 썸네일의 MINOR, 키워드/공통 스타일/관련뉴스 등 실제 미지원 계약, 실데이터에 따른 빈 상태는 명시적으로 남깁니다. 미구현 기능을 가짜 성공이나 장식 버튼으로 채우지 않았습니다.
- 실제 Windows11 데스크톱/DPI·로컬 전체 앱·실계정 호출·운영/배포 인수는 별도 범위입니다. 이 단계 후 추가 개발·운영 적용·PR 병합 없이 종료합니다.
