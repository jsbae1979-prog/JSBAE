# NewsFlow AI Studio — STEP 18: Media & Component Acceptance Contract v2.5

작성일: 2026-10-26 KST · **설계 계약 / 구현 아님**

## 0. 범위·근거
- 마스터 디자인: 사용자가 선택한 최초 대시보드. 기존 v2.4 HTML은 **수정하지 않는다**.
- 현행 프런트엔드: 별도 오프라인 HTML 디자인 시안. 신규 React 소스·실제 API·Windows 실환경은 이 단계에서 **검증하지 않음**.
- GitHub 읽기 기준: `jsbae1979-prog/JSBAE`, `codex/newsflow-step13j-final-20261025` (확인된 파일: `video_routes.py`, `video_ai_routes.py`, `character_routes.py`, `image_post_routes.py`, `db/models.py`). Codex PC의 로컬 미반영 변경은 포함하지 않음.
- 세부 자료: `STEP18_Asset_Resolution_Audit_v2.5.csv`, `STEP18_Media_State_Matrix_v2.5.csv`, `STEP18_Backend_Media_Map_v2.5.csv`, `STEP18_Screen_Gates_v2.5.csv`.

## 1. 실제 발견 사항
기존 시안에는 다음과 같은 **작은 합성 WebP 에셋**이 존재한다. 해상도를 인위적으로 확대해도 새로운 디테일이 생성되지 않는다.

| 파일 | 실제 크기 | 판정 |
|---|---:|---|
| `feature_news.webp` | 155×164 | 원본 미디어 용도로 부적합, 합성 시안 전용 |
| `feature_character.webp` | 158×162 | 원본 미디어 용도로 부적합, 합성 시안 전용 |
| `feature_image.webp` | 154×160 | 원본 미디어 용도로 부적합, 합성 시안 전용 |
| `thumb_news.webp` | 235×100 | 원본 미디어 용도로 부적합, 합성 시안 전용 |
| `thumb_character.webp` | 230×99 | 원본 미디어 용도로 부적합, 합성 시안 전용 |

> 현재 이미지 크기는 **기존 디자인 자산 자체**의 수치다. 프로그램의 실제 미디어 파일 품질을 측정한 값이 아니다.

## 2. 기준 시안의 구성 요소 계약

| 컴포넌트 | 주요 역할 | 표현 및 행동 원칙 |
|---|---|---|
| `MediaFrame` | 9:16 영상·이미지·4:5 카드 중앙 배치 | 출력은 `contain`, 썸네일은 필요 시 `cover`, 비율·크롭 정보 분리 |
| `VerifiedVideoPlayer` | 검증된 MP4 재생 | 서버 승인된 작업과 실제 파일이 있는 경우만 활성화; 샘플에서 재생하지 않음 |
| `MediaAssetTile` | 목록 썸네일, 출처, 유형, 상태 | `SAMPLE ONLY` 또는 실제 프로비넌스 라벨 표시, 이미지 대체 금지 |
| `SceneStrip` | 장면 선택·시간·자막·상태 | 저장 성공까지 '저장됨' 노출 금지, 장면 상태는 서버 기준 |
| `StoryboardReview` | 캐릭터 참조·생성/검토·견적 | PNG 참조/클립/MP4 상태 구분, 캐릭터는 무대사 기존 정책 유지 |
| `ImageCanvas` | 이미지 선택·문구·비율 미리보기 | 1:1/4:5/9:16은 디자인 선택 값일 뿐 출력 지원 확인 후 활성화 |
| `MediaStatus` | 비어 있음·생성 중·오류·결과 불명 등 | 미디어 생성 성공 ≠ 내용 검토 ≠ 게시 승인 |
| `RightsAndSource` | 기사·이미지 출처·사용권 확인 | 사용권 미확인 시 실행·게시 차단, 사실 정보의 시각적 조작 금지 |
| `ApprovalBoundary` | 유료 API·최종 합성·게시 승인 | 별개의 서버 기반 승인. 버튼 활성화만으로 보안 보장 불가 |
| `ErrorRecovery` | 서버가 허용한 재시도·상태 확인 | 결과 불명 자동 재전송 금지 |

### 레이아웃·시각 토큰
- 배경 `#0C1424`, 패널 `#19243A`, Primary `#6D5DF6`, Accent `#20C5D8`, 텍스트 `#F5F7FF`.
- 1920×1080 권장. 1366×768에서는 편집 미리보기와 타임라인이 작업실 기본 뷰에 동시에 나타나도록 설계. 390×844는 세로 스크롤, 중요 버튼 확인 가능, 가로 문서 넘침 금지.
- 사이드바 240px(접힘 72px), 헤더 64px; 클릭 목표 44×44px 권장. 200% DPI에서 실제 Windows 재검증 필요.
- `prefers-reduced-motion`, 키보드 포커스, 이미지 대체 텍스트, 읽을 수 있는 색상 대비를 포함한다.

### 미디어 출력 권장 해상도 (기존 구현 강제 요건 아님)
| 용도 | 권장 기준 | 조건 |
|---|---|---|
| 대시보드 히어로 | 1600px 이상 가로 그래픽 | 브랜드 자산만 사용, 데이터 이미지와 구분 |
| 프로젝트 카드 썸네일 | 640×360 이상 권장 | 실제 파일에서 파생, 손실 크롭 시 중심 피사체 유지 |
| 9:16 영상 | 최종 1080×1920 지원 시 해당 파일 사용 | 기존 API가 그 크기를 보장하는 것은 아님 |
| 세로 포스터 | 540×960 이상 권장 | 파일 해상도가 낮으면 경고·상세 보기 대안 제공 |
| 뉴스 이미지 카드 | 원본 비율을 유지하는 내보내기 | 실제 백엔드 출력 비율·권한 확인 전 비율 버튼 비활성 |
| 캐릭터 참조 이미지 | 현재 PNG 입력 정책 우선 | 입력 크기·형식 제한을 실제 서버와 대조 |

## 3. 데이터·API 계약 (신규 React 목표)
```
MediaView = {
  kind: 'video' | 'character' | 'image',
  resourceId: string,
  sourceType: 'verified-file' | 'draft' | 'generated' | 'sample',
  sourceLabel: string,
  mediaUrl: string | null,          // same-origin 서버에서 검증된 URL만
  mime: string | null,
  width: number | null,
  height: number | null,
  durationMs: number | null,
  sha256: string | null,
  technicalStatus: string,         // 기술적 존재/재생성 확인
  contentReviewStatus: string,     // 내용·출처·권리 검토
  publishApprovalStatus: string,   // 플랫폼별 승인
  revision: number | null,
  allowedActions: string[],        // 서버가 계산한 허용 동작
};
```
이 객체와 경로는 **신규 UI용 제안 타입**으로, 현재 Python API의 응답 스키마라고 주장하지 않는다. 기존 `GET` 조회 경로 중 공급사 동기화를 내부 수행하는 경우 폴링 정책을 반드시 따로 확인한다.

| 유형 | 기존 URL | UI 연결 |
|---|---|---|
| 뉴스 쇼츠 | `GET /video/jobs/{job_id}/file` | 출력 파일 존재, 작업 성공, playable 표시 확인 후 재생 |
| 뉴스 쇼츠 | `GET /video/jobs/{job_id}/thumbnail` | 실제 영상 작업 ID에만 종속 |
| 뉴스 쇼츠 | `GET /video/ai/scenes/{scene_id}/clip` | 장면 상태·출력 검증 및 승인 확인 |
| 캐릭터 쇼츠 | `GET /character/{job_id}/file` | 작업 결과 검사; 실패·결과 불명은 대체 재생 금지 |
| 캐릭터 쇼츠 | `GET /character/{job_id}/clips/{position}` | 장면별 완료 결과와 검토 상태 유지 |
| 이미지 게시물 | `GET /image-posts/{identifier}/file` | 완성 이미지 저장·출처·권리 확인 |
| 이미지 게시물 | `GET /image-posts/cards/{identifier}/preview` | 카드 설계 초안과 최종 저장물 구분 |
| 이미지 게시물 | `GET /image-posts/backgrounds/{identifier}/file` | 배경 산출물은 게시 승인 아님 |


## 4. 안전한 상태 및 권한 분리
- 상태: `empty`, `demo`, `loading`, `processing`, `needs_review`, `verified_file`, `missing`, `failed`, `unknown`, `blocked`.
- **기술 검증**은 MP4 파일 존재·재생 가능 여부 등을 뜻할 뿐, 대본 사실 확인·저작권 검토·SNS 게시 승인을 대체하지 않는다.
- 미디어 조회 오류(404), 디코딩 실패, 파일 누락, 경로/해시 이상 시 샘플·스톡 이미지를 실제 결과처럼 대체하지 않는다.
- 외부 유료 생성·SNS 게시·캐릭터 장면 재시도는 사용자 의사뿐 아니라 서버 승인/상태/예산이 허용하는 경우에만 실행한다.
- `unknown`에서 동일 유료 요청 자동 재전송 금지; 서버/공급사 상태 확인 정책을 보존한다.
- React JSON 명령 계층은 기존 CSRF·Origin·Revision·idempotency 방어를 해제하지 않는다.

## 5. 화면별 최종 인수 Gate
- **D1**: 마스터 대시보드 유지. 색상·공통 레이아웃·동작 원본 대비 비교 자료 필요.
- **D2**: 뉴스 쇼츠의 중앙 미리보기 + 타임라인 + 대본/속성 패널을 1366×768에서 함께 볼 수 있어야 함.
- **D3**: 캐릭터 참조 PNG, 장면 클립, 견적, 생성 승인, 장면 검토·합성이 실상태와 연결되어야 함.
- **D4**: 이미지 카드/선택/생성/저장 상태가 구분되고 완성 이미지 원본과 출처가 보존돼야 함.
- **F1**: 기존 기능 그룹·세부 버튼·API의 최신 커밋 기준 누락 0건 검토.
- **S1**: 외부 유료 호출/결과 불명/게시 승인/삭제·복원 정책 유지.
- **W1**: Windows 1366×768 및 DPI 100/125/150/200%, 파일·DB·키 보호 실측.
- **A1**: 키보드·포커스·텍스트 명암비·44px 목표 및 오류 설명 확인.

**현재 판정**: D1~A1 모두 실제 제품 수준 인수 **미검증**. 오프라인 데모 검사는 최종 인수 대체 불가.

## 6. 다음 실제 구현 착수 조건
1. 현재 Codex 개발의 **최신 코드 기준**과 기존 기능 인벤토리를 다시 대조한다.
2. 마스터 디자인의 화면별 인수 기준을 확정한다.
3. 신규 React UI는 기존 Python 엔진에 연결하되, 미디어 스트리밍·파일 권한·보안 계약을 테스트한다.
4. 실제 Windows 엔드투엔드 검증 전에 기존 UI·운영 데이터를 대체하거나 삭제하지 않는다.
5. 최종 Codex 지시문은 모든 사전 설계가 정리된 뒤 한 번에 전달한다.

## 7. 브라우저 데모 한계
STEP 18 HTML은 미디어 상태와 권한 분리의 **UX 데모**이다. 예시 이미지는 의도적으로 작은 합성 샘플이며, 어떤 샘플도 원본 미디어로 재생·게시되지 않는다. 상태 선택은 네트워크 요청이나 파일 쓰기를 하지 않는다.