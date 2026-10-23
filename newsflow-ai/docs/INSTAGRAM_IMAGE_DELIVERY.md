# Instagram 일반 피드 이미지 전달 준비

단일 JPG만 대상으로 하는 별도 전달 서비스입니다. 인증 중계는 기존 `INSTAGRAM_AUTH_RELAY.md`를 그대로 사용하며, 이 서비스는 OAuth·토큰·MP4·사용자 DB를 취급하지 않습니다. Carousel 기능은 없습니다. 이번 개발에서 서버 배포·스토리지 개설·이미지 전송·실계정 인증·게시를 실행하지 않았습니다.

## 실제 사용 전 최소 조건

1. 기존 Facebook Login for Business 설정과 Page에 연결된 Instagram Professional 계정을 준비합니다. 기존 `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` 권한을 재사용하며 Instagram Login 토큰·호스트를 혼용하지 않습니다.
2. 별도 공개 도메인과 유효한 HTTPS 인증서, Python 실행 환경을 준비합니다. 인증 중계 도메인·스토리지와 역할을 구분합니다. HTTPS 역방향 프록시는 요청 크기 2MiB와 요청 시간 제한을 적용하고 허용한 로컬 프록시만 신뢰합니다.
3. 서버의 전용 빈 보관 폴더를 지정합니다. 운영 NewsFlow 폴더·DB·키·MP4 경로를 사용하지 않습니다. 서버 운영자가 아래 환경변수를 비밀 관리 기능으로 설정합니다. 값은 보고서·채팅·Git에 기록하지 않습니다.
   - `NEWSFLOW_FEED_STORAGE`: 이미지 전용 폴더
   - `NEWSFLOW_FEED_PUBLIC_ORIGIN`: 공개 HTTPS 도메인, 경로·쿼리 없음
   - `NEWSFLOW_FEED_UPLOAD_SECRET`: 무작위 32~256자 전용 업로드 키. Meta App Secret과 다릅니다.
4. 배포 진입점은 `newsflow.publishing.image_delivery_server:from_env`입니다. `uvicorn ... --factory --host 127.0.0.1 --port 8790 --no-access-log` 형태로 실행하고 HTTPS 프록시에 연결합니다. 프록시 전달 헤더는 해당 로컬 프록시만 신뢰하며 외부에서 평문 HTTP 포트에 접근할 수 없게 합니다. 이번 작업에서는 실행하지 않았습니다.
5. Windows의 기존 설정 → Instagram → 일반 피드 HTTPS 이미지 전달에 도메인과 전용 키를 등록합니다. 키는 별도 `feed-delivery-key.dpapi`에 현재 사용자 DPAPI로 보호합니다. 저장만으로 연결 성공으로 표시하거나 외부 조회하지 않습니다.
6. 피드 작업실에서 JPG·원고·계정을 확인하고 전송을 승인합니다. 서버 전송 → 동일 바이트 확인 → IMAGE 컨테이너 생성 → 명시적 처리 조회 → 별도 공개 게시 승인 순서입니다. 서버가 없으면 외부 전송 전에 BLOCKED이며 로컬 JPG 저장은 가능합니다.

## 계약과 보존

- 전송은 인증된 `POST /v1/images` 한 번입니다. 로컬 검토한 1080×1350 JPEG 1장, 최대 **2MiB**만 허용합니다. Meta 최대 규격보다 보수적인 앱 제한이며 RSS/썸네일의 기존 TLS·robots·DNS 고정 검사도 유지합니다.
- 서버는 EXIF가 없는 JPG만 새 UUID 이름으로 저장합니다. 영수증에는 SHA-256·접근 만료 시각만 기록합니다. 클라이언트는 같은 HTTPS origin의 `/images/<UUID>.jpg`와 해시만 수락합니다. 재지정·사설 주소·주소에 포함한 인증정보를 금지하고 TLS SNI 호스트 검증과 확인한 IP로의 연결을 사용합니다.
- 이미지는 Meta가 인증 없이 가져갈 수 있는 임시 공개 URL입니다. 사용자는 전송 전에 권리·노출 범위를 확인합니다. 폴더 목록·DB·키·MP4 읽기 경로는 없습니다.
- 기본 URL 접근 만료는 1시간이며 만료 즉시 GET은 410입니다. 물리 파일은 서버 운영자가 `cleanup_expired(전용_폴더)`를 주기적으로 호출해 정리합니다. 이 함수는 만료된 UUID JPG·영수증만 제거합니다. 자동 배포·OS 예약 등록은 하지 않았습니다.
- 로컬 원본 JPG·출처·캡션과 게시 기록은 서버 만료와 별도로 보존합니다. 계정+JPG 해시의 고유 기록을 외부 전송 전에 저장합니다. 전송·게시 결과 불명, 재시작 중단은 반복하지 않습니다. 게시 ID를 먼저 저장하고 링크 조회가 실패해도 재게시하지 않습니다.
- 직접 준비한 공개 HTTPS JPG 주소를 고급 항목에 지정할 수도 있습니다. 검토한 JPG와 해시가 다르거나 robots·TLS·SSRF 정책이 거절하면 Meta로 보내지 않습니다.

## 근거와 검증 한계

- [Meta 공식 Facebook Login 컬렉션](https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login)
- [Meta Content Publishing 문서](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/content-publishing/)
- 기존 Facebook Graph 호스트의 `/{ig_user_id}/media`에 `image_url`을 전달하고 `/{ig_user_id}/media_publish`를 별도로 실행하는 단일 이미지 계약입니다. 로컬 Reels의 resumable MP4 전송과 구분합니다.
- Meta 직접 문서 페이지는 이번 도구에서 접근 제한이 있었으며 공식 컬렉션·기존 어댑터와 대조했습니다. 실제 앱의 API 버전·권한·이미지 처리·게시 호환성은 실계정 검증 전 NOT VERIFIED입니다.

Fake HTTP/HTTPS·토큰 대체값·임시 DB·JPG로 형식·만료·비밀정보 비노출·실패·중복 보호를 확인합니다. 이 결과는 HTTPS 서버 배포나 Meta 게시 성공을 의미하지 않습니다.
