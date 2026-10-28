# 배포 차단 상태 — 구현과 증명을 구분

| 영역 | 이번 구현/자료 | 아직 필요한 외부 증거 |
|---|---|---|
| 샘플12 | 파일별 SHA·출처/가공·시각 위험·대체 계획 | 생성 원본/입력 권리·상용 재배포 허락 |
| FFmpeg/코덱 | 실제 GPL 구성 확인·GPLv3 및 기타 고지 수집 | 정확한 대응 소스/외부 라이브러리/패치/빌드·제공 방식 |
| 로컬 인증 | 실행별 bootstrap·세션·Host/Origin·CSRF 전달 | 실제 다른 Windows SID·전체 앱/OAuth callback |
| 데이터 | 보호 DACL·CurrentUser DPAPI·별도 data_dir/port | 새 표준 사용자/다른 SID·기존 제품 데이터 이관 |
| 설치 | 전용 CI Setup 컴파일·수명주기 검증 도구 | Windows11 새 PC·최초 실행·실제 제품 migration·실패 rollback |
| 업데이트 | pin/서명/timestamp/sha/sequence 검증기, 기본 차단 | 실제 배포자 인증서·서명·보호 staging/apply/원자적 상태 저장 |
| 음성 | Python/frozen SAPI 실합성 WAV,로컬 한국어1종 | 휴먼 품질·다른 PC 한국어 설치·선택 모델 가중치/권리 |
| DPI | 운영 설정 무변경 유지 | 별도 세션 실제 OS100/125/150/200% GUI |

이 표는 새로운 중간 승인 단계가 아니다. 증명하지 못한 내용을 성공으로
표시하지 않도록 현재 자료와 공개 배포 인수 조건을 한곳에 적은 것이다.
