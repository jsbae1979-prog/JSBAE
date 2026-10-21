"""Local artwork and explicitly approved image publishing; GET never calls a provider."""
import base64
import binascii
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy import select

from newsflow.db.models import ContentDraft, NewsArticle
from newsflow.intelligence.codex import cli_path
from newsflow.publishing.image_artwork import MAX_IMAGE_BYTES, card_artwork
from newsflow.publishing.image_generation import MODEL, STYLES
from newsflow.publishing.image_posts import STATES
from newsflow.publishing.service import PublishingError

from .routes import go, page

router = APIRouter()


@router.get("/image-posts")
def workspace(request: Request, article_id: int | None = Query(None, ge=1),
              post_id: int | None = Query(None, ge=1), draft_id: int | None = Query(None, ge=1),
              analysis_id: int | None = Query(None, ge=1), rank: int | None = Query(None, ge=1, le=3),
              generated_id: int | None = Query(None, ge=1), card_id: int | None = Query(None, ge=1)):
    service = request.app.state.image_posts
    try:
        post = service.get(post_id) if post_id else None
        feed_item = None
        if analysis_id is not None or rank is not None:
            if analysis_id is None or rank is None:
                raise PublishingError("평가 결과와 순위를 함께 선택하세요.")
            group = service.selection(analysis_id)
            feed_item = next(i for i in group["items"] if i["rank"] == rank)
            article_id, draft_id = feed_item["article_id"], feed_item["selection"]["draft_id"]
        with request.app.state.sessions() as session:
            articles = list(session.scalars(select(NewsArticle).order_by(NewsArticle.id.desc()).limit(100)))
            article = session.get(NewsArticle, article_id) if article_id else None
            if article_id and not article:
                raise PublishingError("뉴스를 찾을 수 없습니다.")
            drafts = [d for d in session.scalars(select(ContentDraft).order_by(ContentDraft.id.desc()).limit(100))
                      if article and any(a.get("id", a.get("article_id")) == article.id
                                         for a in (d.sources or {}).get("articles", []))]
            selected = feed_item["draft"] if feed_item else next((d for d in drafts if d.id == draft_id), None)
            if draft_id and not selected:
                raise PublishingError("선택한 뉴스에 연결된 대본이 아닙니다.")
            seed = {"title": article.title, "body": article.summary} if article else {}
            if selected:
                seed = {"title": selected.content.get("title", article.title),
                        "body": "\n\n".join(s.get("narration", "") for s in selected.content.get("scenes", []))}
            if feed_item:
                seed = {"title": feed_item["title"], "body": feed_item["body"]}
            generation = getattr(request.app.state, "image_generation", None)
            generated = generation.get(generated_id) if generation and generated_id else None
            if generated:
                generation.path(generated_id, article_id=article_id,
                                analysis_id=analysis_id, rank=rank)
            cards = getattr(request.app.state, "claude_cards", None)
            card = cards.get(card_id, article_id=article_id, analysis_id=analysis_id, rank=rank,
                             draft_id=draft_id) if cards and card_id else None
            if card:
                if generated or card.status != "success":
                    raise PublishingError("완료된 카드 구성 하나를 선택하세요.")
                seed = card.result["plan"]
            full_generated = bool(generated and generated.options.get("style") == "full_card")
            if full_generated:
                if generated.options.get("draft_id") != draft_id:
                    raise PublishingError("이미지와 대본 연결이 다릅니다.")
                seed = generated.evidence["source"]["plan"]
            return page(request, "image_posts.html", active="image-posts", article=article,
                        full_image_available=True, full_generated=full_generated,
                        claude_cards_available=bool(cards), card_plan=card,
                        card_readiness=cards.readiness(article_id, analysis_id, rank, draft_id) if cards else {},
                        card_runs=cards.recent(article_id) if cards and article_id else [],
                        image_generation_available=bool(generation),
                        codex_image_installed=cli_path() is not None,
                        image_key=generation.keys.status() if generation else {},
                        image_model=MODEL, image_styles=STYLES, generated=generated,
                        generations=generation.recent(article_id) if generation and article_id else [],
                        feed_item=feed_item, analysis_id=analysis_id,
                        articles=articles, seed=seed, drafts=drafts, selected_draft=selected,
                        post=post, recent=service.recent(), states=STATES,
                        deliveries=service.deliveries(post.id) if post else [],
                        accounts=request.app.state.instagram.status()["accounts"])
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/image-posts/selection")
def selected_feeds(request: Request, analysis_id: int | None = Query(None, ge=1)):
    try:
        group = request.app.state.image_posts.selection(analysis_id)
    except PublishingError as error:
        return page(request, "image_selection.html", group=None, error=str(error))
    return page(request, "image_selection.html", group=group, error=None)


@router.post("/image-posts/create")
def create(request: Request, article_id: int = Form(ge=1), title: str = Form(max_length=100),
           body: str = Form(max_length=1800), hashtags: str = Form("", max_length=200),
           draft_id: int | None = Form(None, ge=1),
           analysis_id: int | None = Form(None, ge=1), rank: int | None = Form(None, ge=1, le=3),
           generated_id: int | None = Form(None, ge=1),
           card_id: int | None = Form(None, ge=1),
           image_base64: str = Form("", max_length=6_000_000),
           reviewed: bool = Form(False), rights: bool = Form(False),
           sources_confirmed: bool = Form(False), ai_disclosure: str = Form("unreviewed", max_length=30)):
    try:
        photo = base64.b64decode(image_base64, validate=True) if image_base64 else None
        if photo and len(photo) > MAX_IMAGE_BYTES:
            raise PublishingError("사진은 4MB 이하로 선택하세요.")
        identifier = request.app.state.image_posts.create(
            article_id, title=title, body=body, hashtags=hashtags, photo=photo,
            reviewed=reviewed, rights=rights, sources_confirmed=sources_confirmed,
            ai_disclosure=ai_disclosure, draft_id=draft_id, analysis_id=analysis_id, rank=rank,
            generated_id=generated_id, card_id=card_id)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "사진 파일을 다시 선택하세요.") from None
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/image-posts?post_id={identifier}#image-result")


@router.post("/image-posts/claude-card")
def claude_card(request: Request, article_id: int = Form(ge=1),
                analysis_id: int | None = Form(None, ge=1), rank: int | None = Form(None, ge=1, le=3),
                draft_id: int | None = Form(None, ge=1), model: str = Form(max_length=80),
                consent: bool = Form(False), review_token: str = Form("", max_length=64),
                review_consent: bool = Form(False), purpose: str = Form("full_image", max_length=20)):
    service = request.app.state.claude_cards
    try:
        if purpose != "full_image":
            raise PublishingError("Claude는 문구·이미지 지시문만 작성합니다. 실제 이미지는 OpenAI로 생성하세요.")
        identifier = service.generate(article_id, analysis_id=analysis_id, rank=rank,
                                      draft_id=draft_id, model=model, consent=consent,
                                      review_token=review_token, review_consent=review_consent, purpose=purpose)
        run = service.get(identifier)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    query = {k: v for k, v in {"article_id": article_id, "analysis_id": analysis_id, "rank": rank,
                              "draft_id": draft_id}.items() if v is not None}
    if run.status == "success":
        query["card_id"] = identifier
    return go("/image-posts?" + urlencode(query) + "#claude-card")


@router.post("/image-posts/generate-card-image")
def generate_card_image(request: Request, article_id: int = Form(ge=1), card_id: int = Form(ge=1),
                        analysis_id: int | None = Form(None, ge=1),
                        rank: int | None = Form(None, ge=1, le=3),
                        draft_id: int | None = Form(None, ge=1),
                        consent: bool = Form(False), plan_reviewed: bool = Form(False)):
    service = request.app.state.image_generation
    try:
        identifier = service.generate_card(article_id, card_id=card_id, analysis_id=analysis_id,
            rank=rank, draft_id=draft_id, consent=consent, plan_reviewed=plan_reviewed)
        run = service.get(identifier)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    query = {k: v for k, v in {"article_id": article_id, "analysis_id": analysis_id,
                              "rank": rank, "draft_id": draft_id}.items() if v is not None}
    query["generated_id" if run.status == "success" else "card_id"] = (
        identifier if run.status == "success" else card_id)
    return go("/image-posts?" + urlencode(query) + "#ai-background")


@router.post("/image-posts/generate-background")
def generate_background(request: Request, article_id: int = Form(ge=1),
                        analysis_id: int | None = Form(None, ge=1),
                        rank: int | None = Form(None, ge=1, le=3),
                        draft_id: int | None = Form(None, ge=1),
                        style: str = Form("illustration", max_length=20),
                        consent: bool = Form(False)):
    service = request.app.state.image_generation
    try:
        identifier = service.generate(article_id, analysis_id=analysis_id, rank=rank,
                                      style=style, consent=consent)
        run = service.get(identifier)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    query = {k: v for k, v in {"article_id": article_id, "analysis_id": analysis_id, "rank": rank,
                              "draft_id": draft_id}.items() if v is not None}
    if run.status == "success":
        query["generated_id"] = identifier
    return go("/image-posts?" + urlencode(query) + "#ai-background")


@router.post("/image-posts/generate-codex-image")
def generate_codex_image(request: Request, article_id: int = Form(ge=1),
                         title: str = Form(max_length=60), body: str = Form(max_length=200),
                         analysis_id: int | None = Form(None, ge=1),
                         rank: int | None = Form(None, ge=1, le=3),
                         draft_id: int | None = Form(None, ge=1),
                         consent: bool = Form(False), reviewed: bool = Form(False)):
    service = request.app.state.image_generation
    try:
        identifier = service.generate_codex(article_id, title=title, body=body,
            analysis_id=analysis_id, rank=rank, draft_id=draft_id, consent=consent, reviewed=reviewed)
        run = service.get(identifier)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    query = {k: v for k, v in {"article_id": article_id, "analysis_id": analysis_id,
                              "rank": rank, "draft_id": draft_id}.items() if v is not None}
    if run.status == "success":
        query["generated_id"] = identifier
    return go("/image-posts?" + urlencode(query) + "#codex-image")


@router.get("/image-posts/cards/{identifier}/preview")
def card_preview(request: Request, identifier: int):
    try:
        run = request.app.state.claude_cards.get(identifier)
        if run.status != "success":
            raise PublishingError("완료된 구성이 없습니다.")
        if run.options.get("purpose") == "full_image":
            raise PublishingError("지시문 단계입니다. 아직 생성된 이미지가 없습니다.")
        plan = run.result["plan"]
        raw = card_artwork(plan["title"], plan["body"], run.evidence["publisher"], plan)
    except PublishingError as error:
        raise HTTPException(404, str(error)) from None
    return Response(raw, media_type="image/jpeg")


@router.get("/image-posts/backgrounds/{identifier}/file")
def generated_file(request: Request, identifier: int):
    try:
        path = request.app.state.image_generation.path(identifier)
    except PublishingError as error:
        raise HTTPException(404, str(error)) from None
    return FileResponse(path, media_type="image/jpeg")


@router.get("/image-posts/{identifier}/file")
def file(request: Request, identifier: int, download: bool = False):
    try:
        path = request.app.state.image_posts.path(identifier)
    except PublishingError as error:
        raise HTTPException(404, str(error)) from None
    return FileResponse(path, media_type="image/jpeg", filename=path.name if download else None)


@router.get("/image-posts/{identifier}/caption")
def caption(request: Request, identifier: int):
    try:
        post = request.app.state.image_posts.get(identifier)
    except PublishingError as error:
        raise HTTPException(404, str(error)) from None
    return PlainTextResponse(post.caption, headers={
        "Content-Disposition": f'attachment; filename="newsflow-image-{identifier}-caption.txt"'})


@router.post("/image-posts/{identifier}/prepare")
def prepare(request: Request, identifier: int, account_id: int = Form(ge=1),
            image_url: str = Form(max_length=2048), consent: bool = Form(False)):
    try:
        request.app.state.image_posts.prepare(identifier, account_id, image_url, consent=consent)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/image-posts?post_id={identifier}#image-result")


@router.post("/image-posts/deliveries/{identifier}/{action}")
def delivery(request: Request, identifier: int, action: str, consent: bool = Form(False)):
    service = request.app.state.image_posts
    try:
        if action == "check":
            service.check(identifier, consent=consent)
        elif action == "publish":
            service.publish(identifier, public_consent=consent)
        else:
            raise HTTPException(404)
        row = service._delivery(identifier)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/image-posts?post_id={row.post_id}#image-result")
