# NewsFlow AI Studio — 사용자 선정 원본 PNG 업로드 절차

**현 상태: 원본 이미지 로컬 SHA-256 검증 완료 / GitHub 바이너리 업로드 미완료.**

- 전용 브랜치: `design/newsflow-ai-studio-v3-20261026`
- 업로드 대상: `newsflow-ai/docs/design/studio-v3.0/assets/master_dashboard_reference.png`
- 원본 크기: `1658 × 938`px · `2,881,357` bytes
- 기대 SHA-256: `ee910d5d975fffdd551f26a097051b1f998caea415246fdf8a33b48255de9b99`
- 원본 파일 이름(배포 ZIP 내부): `master_dashboard_reference.png`
- 자료 출처: 사용자가 선정한 첫 번째 마스터 대시보드 이미지

## 업로드 방법

1. ChatGPT 제공 `NewsFlow_AI_Studio_Master_Dashboard_GitHub_Upload_Kit.zip`을 받아 압축을 푼다.
2. GitHub의 `design/newsflow-ai-studio-v3-20261026` 브랜치로 이동한다. **main 또는 Step15B 개발 브랜치에 업로드하지 않는다.**
3. 해당 브랜치에서 `newsflow-ai/docs/design/studio-v3.0/assets/master_dashboard_reference.png` 파일 경로로 정확한 원본 PNG를 등록한다. 폴더가 없다면 GitHub 웹 업로드 또는 로컬 Git으로 디렉터리를 만든다.
4. 커밋 예시: `docs(newsflow): add approved Studio master dashboard reference`
5. 받은 원본 파일의 SHA-256을 다음 명령으로 검증한다.

```powershell
Get-FileHash -LiteralPath '.\master_dashboard_reference.png' -Algorithm SHA256
```

6. GitHub에 등록된 이미지 다운로드본의 SHA도 위 값과 같은지 검증한다.
7. **동일함을 확인한 뒤에만** `MASTER_ASSET_STATUS.md`의 상태를 `VERIFIED_IN_REPO`로 수정한다.
8. Codex는 마스터 이미지와 실제 React UI를 비교하되 화면 전체를 PNG 한 장으로 덮는 구현은 금지한다.

## 검증 경계

GitHub 브랜치에는 설계 문서·56개 기능그룹 CSV·독립 HTML 프로토타입이 먼저 커밋돼 있다. 이 원본 PNG는 현재 별도로 업로드해야 한다. 바이너리 자체가 GitHub에 올라오기 전에는 원본 파일 등록 성공이라고 보고하지 않는다.
