# NewsFlow AI Studio — UX/UI 전면 교체 설계 v3.0

> **DESIGN-ONLY / NOT IMPLEMENTED / DO NOT DEPLOY**
>
> 이 폴더는 ChatGPT 대화에서 준비한 UX/UI 설계 자료를 보관하는 전용 경로입니다. 
> 기존 Python 소스·운영 DB·백업·기존 PR과 분리하며, 이 커밋은 신규 React UI 구현이나 기존 프로그램의 변경을 의미하지 않습니다.

## 프로젝트 기준

- 원본 기준 코드: `codex/newsflow-step15b-20261026` @ `b1eadb3686bfe5765ab1aa64d51688e180980b97`
- 디자인: **사용자가 선택한 최초 NewsFlow AI Studio 대시보드 이미지**
- 목표: Windows 전용 다중 사용자 배포 가능성을 고려한 전체 사용자 화면 React + TypeScript 전면 교체
- 포함: 뉴스 쇼츠, 캐릭터 쇼츠, 독립 AI 이미지 제작, 뉴스 이미지 게시물, 자동화, SNS 게시, 사용량·설정 등
- 실제 유료 API·SNS 호출, OAuth, Windows 설치·배포, 운영 적용은 승인 대상에 **포함하지 않음**

## 자료 안내

| 파일 | 역할 |
| --- | --- |
| [Design_Baseline_v3.0.md](Design_Baseline_v3.0.md) | 디자인·UX·기존 기능 보존 통합 기준 |
| [Codex_Handoff_v3.0.md](Codex_Handoff_v3.0.md) | 나중에 Codex PC 세션에 전달할 구현 지시 초안; **자동 실행 아님** |
| [Feature_Trace_56_v3.0.csv](Feature_Trace_56_v3.0.csv) | 56개 기능 그룹 → 신규 화면 추적표, 런타임 전수검증 결과는 아님 |
| [Media_Component_Contract_v2.5.md](Media_Component_Contract_v2.5.md) | 영상·이미지·승인·결과불명 UI 규칙 |
| [prototypes/NewsFlow_Master_Experience_v2.4.html](prototypes/NewsFlow_Master_Experience_v2.4.html) | 이미지가 내장된 오프라인 HTML 화면 예시; 실제 React·API 앱 아님 |
| [MASTER_ASSET_STATUS.md](MASTER_ASSET_STATUS.md) | 사용자 선정 원본 PNG의 정확한 해시·업로드 상태 |
| [MASTER_PNG_UPLOAD_GUIDE.md](MASTER_PNG_UPLOAD_GUIDE.md) | 원본 PNG GitHub 등록과 SHA-256 확인 방법 |

## 마스터 PNG 처리

원본 `마스터_대시보드_사용자선정원본.png`은 사용자가 직접 선택한 시각 기준입니다.
**이 GitHub 커밋에는 원본 PNG 바이너리가 아직 포함되지 않았습니다.**
자세한 크기·SHA-256과 누락 시 처리 기준은 `MASTER_ASSET_STATUS.md`를 참고하세요.
오프라인 HTML의 이미지 자산을 원본 PNG와 동일한 것으로 오인하지 마세요.

## 변경·검증 원칙

1. 신규 개발은 별도 브랜치에서 수행하고 `main`, 기존 Draft PR, 운영 사용자 데이터를 변경하지 않는다.
2. 기능·비용·승인·저장·보안 동작은 최신 Python 서비스 계약에서 재확인한다.
3. 시각적 일치와 실제 기능 테스트는 **별도 판정**한다.
4. 백엔드 API 연결 전에는 샘플 데이터를 실데이터·실계정 연결 성공으로 표시하지 않는다.
5. 사용자가 명시적으로 승인하기 전까지 운영 앱 전환·설치 프로그램 배포·유료 API·SNS 공개 게시는 하지 않는다.
