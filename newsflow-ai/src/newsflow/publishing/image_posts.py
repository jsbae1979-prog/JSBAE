"""Image posts reuse Instagram credentials/transport with durable one-shot delivery."""
import hashlib
import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from newsflow.db.models import (
    AuditLog,
    ContentDraft,
    ImagePost,
    ImagePostDelivery,
    NewsArticle,
    NewsListState,
    PlatformAccount,
)
from newsflow.news.rss_adapter import FeedError, PublicRSSAdapter, validate_url
from newsflow.news.thumbnails import _HTTPSOnlyTransport
from newsflow.oauth.instagram import InstagramConnectionError

from .image_artwork import artwork, card_artwork
from .image_selection import references, selection
from .instagram import GRAPH, InstagramUploadAdapter, InstagramUploadError, _identifier
from .service import PublishingError, hash_file

STATES = {
    "preparing": "전송 중 · 반복 요청 금지", "processing": "Instagram 처리 확인 필요",
    "checking": "처리 상태 확인 중", "ready": "공개 게시 승인 대기",
    "publishing": "게시 중 · 반복 요청 금지", "published": "게시 완료",
    "published_no_link": "게시 ID 저장됨 · 링크 조회 실패", "failed": "실패 · 자동 재시도 없음",
    "unknown": "결과 불명 · Instagram에서 확인 필요",
}


def public_image_url(value):
    try:
        safe = validate_url(value)
        parsed = urlsplit(safe)
        if parsed.scheme != "https" or parsed.query:
            raise ValueError
        return safe
    except (FeedError, ValueError):
        raise PublishingError("로그인·토큰이 없는 공개 HTTPS 이미지 주소가 필요합니다.") from None


class InstagramImageAdapter(InstagramUploadAdapter):
    def create_image(self, image_url, caption, disclosure, bundle, account_id):
        if not caption.strip() or len(caption) > 2200 or disclosure not in {"disclose", "not_required"}:
            raise InstagramUploadError("invalid_input")
        data = self._request("POST", f"{GRAPH}/{_identifier(account_id)}/media", bundle, urlencode({
            "image_url": public_image_url(image_url), "caption": caption,
            "is_ai_generated": "true" if disclosure == "disclose" else "false",
        }).encode("ascii"))
        try:
            return _identifier(data.get("id"))
        except InstagramUploadError:
            raise InstagramUploadError("unknown") from None


class ImagePostService:
    def __init__(self, sessions, data_dir, connections, *, adapter=None, fetcher=None, generation=None, cards=None, delivery=None):
        self.sessions, self.connections = sessions, connections
        self.generation = generation
        self.cards, self.delivery = cards, delivery
        self.outputs = Path(data_dir) / "outputs" / "image-posts"
        self.adapter = adapter or InstagramImageAdapter()
        # Existing TLS/robots/DNS-pinning policy, with HTTPS-only redirects.
        base = PublicRSSAdapter()
        self.fetcher = fetcher or PublicRSSAdapter(_HTTPSOnlyTransport(base.transport))

    def selection(self, analysis_id=None):
        with self.sessions() as session:
            return selection(session, analysis_id)

    def create(self, article_id, *, title, body, hashtags="", photo=None, reviewed=False,
               rights=False, sources_confirmed=False, ai_disclosure="unreviewed", draft_id=None,
               analysis_id=None, rank=None, generated_id=None, card_id=None):
        if not (reviewed and rights and sources_confirmed):
            raise PublishingError("내용·출처·이미지 이용 권한을 확인해 주세요.")
        plan = None
        full_image = None
        if card_id is not None:
            if generated_id is not None or photo is not None or self.cards is None:
                raise PublishingError("Claude 카드·AI 배경·내 사진 중 하나만 선택하세요.")
            card = self.cards.get(card_id, article_id=article_id, analysis_id=analysis_id,
                                  rank=rank, draft_id=draft_id)
            if card.status != "success":
                raise PublishingError("완료된 카드 구성만 사용할 수 있습니다.")
            if card.options.get("purpose") == "full_image":
                raise PublishingError("이미지 지시문은 완성 이미지가 아닙니다. 이미지 생성 후 검토·저장하세요.")
            plan = card.result["plan"]
            ai_disclosure = "disclose"
        if generated_id is not None:
            if photo is not None or self.generation is None:
                raise PublishingError("내 사진과 AI 배경 중 하나만 선택하세요.")
            photo = self.generation.path(generated_id, article_id=article_id,
                analysis_id=analysis_id, rank=rank).read_bytes()
            generated = self.generation.get(generated_id)
            if generated.options.get("style") == "full_card":
                if generated.options.get("draft_id") != draft_id:
                    raise PublishingError("이미지와 대본 연결이 다릅니다.")
                full_image = generated
                copy = generated.evidence["source"]["plan"]
                if (title.strip(), body.strip()) != (copy["title"], copy["body"]):
                    raise PublishingError("완성 이미지의 문구는 자동 변경되지 않습니다. 생성 당시 문구를 유지하세요.")
            ai_disclosure = "disclose"  # The client cannot remove generated-image disclosure.
        title, body, hashtags = title.strip(), body.strip(), hashtags.strip()
        if (not 1 <= len(title) <= 100 or not 1 <= len(body) <= 1800 or len(hashtags) > 200
                or ai_disclosure not in {"disclose", "not_required"}
                or any(ord(c) < 32 and c not in "\n\r\t" for c in title + body + hashtags)):
            raise PublishingError("제목 100자·본문 1800자·해시태그 200자 이내로 입력하고 AI 표시를 선택하세요.")
        with self.sessions() as session:
            article = session.get(NewsArticle, article_id)
            if not article:
                raise PublishingError("뉴스를 찾을 수 없습니다.")
            sources = {"articles": [{"id": article.id, "title": article.title, "url": article.url,
                "publisher": article.publisher, "summary": article.summary,
                "published_at": article.published_at.isoformat() if article.published_at else None}],
                "fact_verification": "human_review_required"}
            publisher = article.publisher
            if draft_id is not None:
                draft = session.get(ContentDraft, draft_id)
                draft_sources = (draft.sources or {}).get("articles", []) if draft else []
                if not any(a.get("id", a.get("article_id")) == article_id for a in draft_sources):
                    raise PublishingError("선택한 뉴스에 연결된 대본이 아닙니다.")
                sources["draft_id"] = draft.id
                seen = {article.url}
                for reference in references(draft_sources):
                    url = reference.get("url")
                    if not url:
                        raise PublishingError("대본의 출처 주소가 부족합니다. 원문을 확인해 주세요.")
                    if url not in seen:
                        sources["articles"].append(deepcopy(reference))
                        seen.add(url)
            if analysis_id is not None or rank is not None:
                group = selection(session, analysis_id) if analysis_id is not None else None
                item = next((i for i in group["items"] if i["rank"] == rank), None) if group else None
                if (not item or item["article_id"] != article_id
                        or item["selection"]["draft_id"] != draft_id):
                    raise PublishingError("선정 결과·대본 연결이 바뀌었습니다. 피드 목록에서 다시 확인하세요.")
                sources["selection"] = item["selection"]
                seen = {r["url"] for r in sources["articles"]}
                for reference in item["references"]:
                    if reference["url"] not in seen:
                        sources["articles"].append(deepcopy(reference))
                        seen.add(reference["url"])
        if generated_id is not None:
            sources["generated_image_run_id"] = generated_id
        if full_image is not None:
            if full_image.options.get("claude_card_run_id") is not None:
                sources["claude_card_run_id"] = full_image.options["claude_card_run_id"]
            sources["image_provider"] = full_image.provider
            sources["full_image"] = True
        if card_id is not None:
            sources["claude_card_run_id"] = card_id
            if card.options.get("purpose") == "svg_card":
                sources["claude_svg_card"] = True
        credits = "\n\n".join(
            f"출처: {item.get('publisher') or item.get('title') or '원문'}\n{item['url']}"
            for item in sources["articles"])
        caption = f"{title}\n\n{body}\n\n{credits}"
        if hashtags:
            caption += "\n\n" + hashtags
        if ai_disclosure == "disclose":
            caption += ("\nAI 구성 뉴스 카드 · 실제 현장 사진 아님" if plan else
                        "\nAI 생성 이미지 · 실제 현장 사진 아님")
        if len(caption) > 2200:
            raise PublishingError("출처·표시를 포함한 본문이 2200자를 넘습니다. 본문을 줄여 주세요.")
        raw = (card_artwork(title, body, publisher, plan) if plan else
               artwork(title, publisher, photo, ai=ai_disclosure == "disclose", body=body)) if full_image is None else None
        if full_image is not None:
            # Preserve the API's entire composition; resize only, no local card/template overlay.
            with Image.open(BytesIO(photo)) as image:
                output = BytesIO()
                ImageOps.pad(image.convert("RGB"), (1080, 1350), method=Image.Resampling.LANCZOS,
                             color=(11, 22, 40)).save(output, format="JPEG", quality=90)
                raw = output.getvalue()
        self.outputs.mkdir(parents=True, exist_ok=True)
        name = f"image-{uuid4().hex}.jpg"
        with (self.outputs / name).open("xb") as stream:
            stream.write(raw)
        with self.sessions.begin() as session:
            post = ImagePost(article_id=article_id, title=title, caption=caption, sources=sources,
                filename=name, sha256=hashlib.sha256(raw).hexdigest(), ai_disclosure=ai_disclosure)
            session.add(post)
            for reference in sources["articles"]:
                source_id = reference.get("id", reference.get("article_id"))
                if not isinstance(source_id, int) or not session.get(NewsArticle, source_id):
                    continue
                state = session.get(NewsListState, source_id)
                if state is None:
                    session.add(NewsListState(article_id=source_id, hidden=False, used=True))
                else:
                    state.used = True
            session.flush()
            session.add(AuditLog(level="info", event="image_post_created",
                                message=f"image_post_id={post.id}; reviewed locally; no external call"))
            return post.id

    def get(self, identifier):
        with self.sessions() as session:
            post = session.get(ImagePost, identifier)
            if not post:
                raise PublishingError("이미지 게시물을 찾을 수 없습니다.")
            return post

    def path(self, identifier):
        post = self.get(identifier)
        if not re.fullmatch(r"image-[a-f0-9]{32}\.jpg", post.filename):
            raise PublishingError("이미지 파일 이름을 확인할 수 없습니다.")
        path = self.outputs / post.filename
        if path.is_symlink() or not path.is_file() or hash_file(path) != post.sha256:
            raise PublishingError("검토한 이미지가 변경되었습니다. 다시 제작·검토해 주세요.")
        return path

    def recent(self):
        with self.sessions() as session:
            return list(session.scalars(select(ImagePost).order_by(ImagePost.id.desc()).limit(12)))

    def deliveries(self, post_id):
        with self.sessions() as session:
            return list(session.scalars(select(ImagePostDelivery).where(
                ImagePostDelivery.post_id == post_id).order_by(ImagePostDelivery.id.desc())))

    def _delivery(self, identifier):
        with self.sessions() as session:
            row = session.get(ImagePostDelivery, identifier)
            if not row:
                raise PublishingError("게시 기록을 찾을 수 없습니다.")
            return row

    def _finish(self, identifier, status, **detail):
        with self.sessions.begin() as session:
            row = session.get(ImagePostDelivery, identifier)
            row.status, row.detail = status, {**row.detail, **detail}
            session.add(AuditLog(level="info", event="image_post_delivery",
                                message=f"delivery_id={identifier}; status={status}"))

    def _claim(self, identifier, expected, next_status):
        with self.sessions.begin() as session:
            result = session.execute(update(ImagePostDelivery).where(
                ImagePostDelivery.id == identifier, ImagePostDelivery.status.in_(expected)
            ).values(status=next_status))
            if result.rowcount != 1:
                raise PublishingError("이미 처리했거나 결과 확인이 필요한 요청입니다. 반복 전송하지 않습니다.")
        return self._delivery(identifier)

    def _credential(self, row):
        self.path(row.post_id)
        credential = self.connections.access_for_upload(row.account_id, consent=True)
        identity = [credential.instagram_id, credential.page_id, credential.app_id]
        if row.detail.get("identity") != identity:
            raise PublishingError("준비할 때와 게시 계정이 달라졌습니다.")
        return credential

    def _failure(self, identifier, error):
        code = error.code if isinstance(error, (InstagramUploadError, InstagramConnectionError)) else "unknown"
        known = isinstance(error, InstagramUploadError) and not error.unknown
        self._finish(identifier, "failed" if known else "unknown", error_code=code)

    def prepare(self, post_id, account_id, image_url, *, consent=False):
        if consent is not True:
            raise PublishingError("이미지 주소 확인 및 Instagram 전송에 동의해 주세요.")
        post = self.get(post_id)
        url = public_image_url(image_url) if image_url else None
        if url is None and (self.delivery is None or not self.delivery.ready()):
            raise PublishingError("BLOCKED · HTTPS 이미지 전달 서버를 준비하세요. 로컬 저장·검토는 가능합니다.")
        self.path(post_id)
        with self.sessions() as session:
            account = session.get(PlatformAccount, account_id)
            if not account or account.platform != "instagram" or not account.api_ready:
                raise PublishingError("Instagram 연결 계정을 확인하세요. 이미지 저장은 사용할 수 있습니다.")
            label = account.label
        try:
            with self.sessions.begin() as session:
                row = ImagePostDelivery(post_id=post_id, account_id=account_id,
                    media_sha256=post.sha256, status="preparing",
                    detail={"account_label": label, "automatic_retry": False})
                session.add(row)
                session.flush()
                identifier = row.id
        except IntegrityError:
            raise PublishingError("이 계정·이미지의 게시 기록이 이미 있습니다. 기존 결과를 확인하세요.") from None
        if url is None:
            try:
                url = self.delivery.upload(self.path(post_id), post.sha256)
                self._finish(identifier, "preparing", image_url=url, upload_sha256=post.sha256)
            except Exception:  # noqa: BLE001 - lost upload response may already have transferred bytes
                self._finish(identifier, "unknown", error_code="image_delivery_unknown")
                return identifier
        else:
            self._finish(identifier, "preparing", image_url=url)
        try:
            # Exact bytes only: do not publish a different/low-resolution supplied image.
            remote = self.fetcher.fetch(url, 10)
            if hashlib.sha256(remote).hexdigest() != post.sha256:
                raise PublishingError("외부 주소의 이미지가 검토한 JPEG와 다릅니다.")
            credential = self.connections.access_for_upload(account_id, consent=True)
            self._finish(identifier, "preparing",
                identity=[credential.instagram_id, credential.page_id, credential.app_id])
            container = self.adapter.create_image(url, post.caption, post.ai_disclosure,
                                                  credential.bundle, credential.instagram_id)
            self._finish(identifier, "processing", container_id=container)
        except PublishingError:
            self._finish(identifier, "failed", error_code="image_mismatch")
        except Exception as error:  # noqa: BLE001 - preserve uncertain outcomes, never echo remote data
            self._failure(identifier, error)
        return identifier

    def check(self, identifier, *, consent=False):
        if consent is not True:
            raise PublishingError("처리 상태 조회 동의가 필요합니다.")
        row = self._claim(identifier, {"processing"}, "checking")
        try:
            credential = self._credential(row)
            status = self.adapter.status(credential.bundle, row.detail["container_id"])
            self._finish(identifier, {"FINISHED": "ready", "IN_PROGRESS": "processing",
                         "ERROR": "failed", "EXPIRED": "failed"}.get(status, "unknown"))
        except Exception as error:  # noqa: BLE001 - preserve uncertain outcomes, never echo remote data
            self._failure(identifier, error)

    def publish(self, identifier, *, public_consent=False):
        if public_consent is not True:
            raise PublishingError("선택한 계정에 이미지를 공개 게시하도록 승인해 주세요.")
        row = self._claim(identifier, {"ready"}, "publishing")
        try:
            credential = self._credential(row)
            media_id = self.adapter.publish(credential.bundle, credential.instagram_id,
                                            row.detail["container_id"], public_approved=True)
            # Persist success before link lookup; a lost link must never replay publication.
            self._finish(identifier, "published_no_link", media_id=media_id)
        except Exception as error:  # noqa: BLE001 - preserve uncertain outcomes, never echo remote data
            self._failure(identifier, error)
            return
        try:
            result = self.adapter.result(credential.bundle, media_id, credential.instagram_id)
            self._finish(identifier, "published", url=result.url)
        except Exception:  # noqa: BLE001 - a link failure cannot undo confirmed publication
            self._finish(identifier, "published_no_link", error_code="link_lookup_failed")

    def recover(self):
        with self.sessions.begin() as session:
            for row in session.scalars(select(ImagePostDelivery).where(
                    ImagePostDelivery.status.in_(("preparing", "checking", "publishing")))):
                row.status = "unknown"
                row.detail = {**deepcopy(row.detail), "error_code": "interrupted", "automatic_retry": False}
