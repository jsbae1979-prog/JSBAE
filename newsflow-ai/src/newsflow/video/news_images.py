"""Rights-checked article assets. Rendering never fetches a URL or searches the web."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from newsflow.news.thumbnails import thumbnail_url
from .engine import load_image, RenderError

MAX_BYTES = 20 * 1024 * 1024
ORIGINS = {"representative": 0, "collected": 1, "search": 2}


class NewsImageError(ValueError):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NewsImages:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.assets = self.root / "assets"
        self.records = self.root / "news-images"

    def safe(self, path, base):
        path, base = Path(path), Path(base)
        if not path.is_relative_to(base):
            raise NewsImageError("이미지 경로를 확인하세요.")
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise NewsImageError("이미지 연결 경로는 사용할 수 없습니다.")
            if part == self.root:
                break
        if not path.resolve().is_relative_to(base.resolve()):
            raise NewsImageError("이미지 경로를 확인하세요.")
        return path

    def asset(self, name):
        if (not isinstance(name, str) or not name or len(name) > 255 or Path(name).name != name
                or any(c in name for c in "\\/:\x00") or Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg"}):
            raise NewsImageError("허용된 로컬 이미지 파일을 선택하세요.")
        path = self.safe(self.assets / name, self.assets)
        load_image(path).close()
        return path

    def remember(self, article, name, *, source_url, rights_basis, origin="collected"):
        """Called only after explicit rights confirmation, not from RSS collection."""
        if origin not in ORIGINS or not isinstance(rights_basis, str) or not 3 <= len(rights_basis.strip()) <= 400:
            raise NewsImageError("이미지 사용권 근거를 입력하세요.")
        if not thumbnail_url(source_url) or not thumbnail_url(article.url):
            raise NewsImageError("기사와 이미지 출처를 확인하세요.")
        source = self.asset(name)
        self.safe(self.records, self.records).mkdir(exist_ok=True)
        # Freeze a clean, content-addressed PNG; preserve the user's original file.
        output = BytesIO()
        with load_image(source) as image:
            image.save(output, format="PNG")
        raw = output.getvalue()
        if len(raw) > MAX_BYTES:
            raise NewsImageError("이미지는 20MB 이하로 준비하세요.")
        sha = hashlib.sha256(raw).hexdigest()
        frozen = self.safe(self.assets / ("news-" + sha + ".png"), self.assets)
        if frozen.exists():
            if digest(frozen) != sha:
                raise NewsImageError("저장한 이미지의 무결성을 확인하세요.")
        else:
            with frozen.open("xb") as handle:
                handle.write(raw)
        row = {"version": 1, "article_id": article.id, "article_url": article.url,
               "publisher": article.publisher, "source_url": source_url, "name": frozen.name,
               "sha256": sha, "rights_basis": rights_basis.strip(), "origin": origin,
               "rights_confirmed_at": datetime.now(UTC).isoformat()}
        record = self.safe(self.records / (str(article.id) + "-" + uuid4().hex + ".json"), self.records)
        with record.open("x", encoding="utf-8") as handle:
            json.dump(row, handle, ensure_ascii=False)
        return row

    def import_thumbnail(self, article, metadata, adapter, *, rights_basis):
        """Explicit rights-confirmed import of the DB-bound thumbnail, never arbitrary URLs."""
        if (metadata.article_id != article.id or metadata.source_article_url != article.url
                or not thumbnail_url(metadata.url) or not 3 <= len(rights_basis.strip()) <= 400):
            raise NewsImageError("대표 이미지 출처와 사용권을 확인하세요.")
        for row in self.candidates(article):
            if row["source_url"] == metadata.url and row["origin"] == "representative":
                return row
        raw = adapter.fetch(metadata.url, 6)
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
            raise NewsImageError("이미지 크기를 확인하세요.")
        import warnings
        from PIL import Image, ImageOps
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 16_000_000:
                        raise NewsImageError("이미지 형식·픽셀 수를 확인하세요.")
                    clean = ImageOps.exif_transpose(image).convert("RGB")
                    output = BytesIO()
                    clean.save(output, format="PNG")
        except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise NewsImageError("이미지 형식·픽셀 수를 확인하세요.") from None
        content = output.getvalue()
        if len(content) > MAX_BYTES:
            raise NewsImageError("이미지 크기를 확인하세요.")
        name = "news-" + hashlib.sha256(content).hexdigest() + ".png"
        path = self.safe(self.assets / name, self.assets)
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(content)
        return self.remember(article, name, source_url=metadata.url,
                             rights_basis=rights_basis, origin="representative")

    def candidates(self, article):
        result = []
        if not self.records.exists():
            return result
        self.safe(self.records, self.records)
        for path in sorted(self.records.glob(str(article.id) + "-*.json"))[:256]:
            try:
                self.safe(path, self.records)
                if path.stat().st_size > 8192:
                    continue
                row = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(row, dict) or not isinstance(row.get("rights_basis"), str):
                    continue
                if (row.get("version") != 1 or row.get("article_id") != article.id
                        or row.get("article_url") != article.url or row.get("origin") not in ORIGINS
                        or not row.get("rights_confirmed_at") or not 3 <= len(row.get("rights_basis", "")) <= 400
                        or not thumbnail_url(row.get("source_url"))):
                    continue
                if digest(self.asset(row["name"])) != row["sha256"]:
                    continue
                result.append(row)
            except (OSError, ValueError, TypeError, KeyError, RenderError):
                continue
        return sorted(result, key=lambda x: (ORIGINS[x["origin"]], x["source_url"], x["sha256"]))

    def choose(self, session, sources, count, manual=None, article_ids=None):
        from newsflow.db.models import NewsArticle
        linked = {a.get("id", a.get("article_id")) for a in sources.get("articles", [])}
        linked = {i for i in linked if type(i) is int and i > 0}
        articles = {i: session.get(NewsArticle, i) for i in linked}
        if article_ids is not None and len(article_ids) != count:
            raise NewsImageError("장면별 뉴스 연결을 확인하세요.")
        rows, names = [], []
        for position in range(count):
            manual_name = (manual or [""] * count)[position]
            row = {"position": position, "mode": "card", "reason": "사용권이 확인된 연결 이미지 없음"}
            name = ""
            if manual_name == "__card__":
                row["reason"] = "사용자가 기본 카드 선택"
            elif manual_name:
                path = self.asset(manual_name)
                name = manual_name
                row = {"position": position, "mode": "manual", "name": name, "sha256": digest(path)}
            else:
                identifier = article_ids[position] if article_ids is not None else (next(iter(linked)) if len(linked) == 1 else None)
                if identifier is not None and identifier not in linked:
                    raise NewsImageError("대본 출처에 포함된 뉴스만 연결할 수 있습니다.")
                article = articles.get(identifier)
                options = self.candidates(article) if article else []
                if options:
                    row = {**options[0], "position": position, "mode": "automatic"}
                    name = row["name"]
                elif len(linked) > 1 and identifier is None:
                    row["reason"] = "장면과 기사의 연결 확인 필요"
            rows.append(row)
            names.append(name)
        return names, rows
