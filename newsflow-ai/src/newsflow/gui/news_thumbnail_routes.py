"""Same-origin raster endpoint for stored source previews; never accepts an arbitrary URL."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from newsflow.db.models import ArticleThumbnail

router = APIRouter()


@router.get("/news/{article_id}/thumbnail")
def thumbnail(request: Request, article_id: int):
    if (request.cookies.get("newsflow_csrf") != request.state.csrf
            or request.headers.get("sec-fetch-site") == "cross-site"
            or request.headers.get("origin", str(request.base_url).rstrip("/")) != str(request.base_url).rstrip("/")):
        raise HTTPException(403, "뉴스 화면에서 이미지를 확인해 주세요.")
    with request.app.state.sessions() as session:
        metadata = session.get(ArticleThumbnail, article_id)
        url = metadata.url if metadata else None
    if url is None:
        raise HTTPException(404, "출처 제공 이미지가 없습니다.")
    preview = request.app.state.news_thumbnails.get(url)
    if preview is None:
        raise HTTPException(404, "이미지를 표시할 수 없습니다. 기본 이미지를 유지합니다.")
    return Response(preview, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600",
                                                             "X-Content-Type-Options": "nosniff"})
