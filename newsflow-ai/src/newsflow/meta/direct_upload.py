"""Direct Meta file transport. Fixed hosts; one POST attempt; no fallback/replay."""

import re
from hashlib import sha256
from uuid import uuid4

from pydantic import SecretStr

from .contracts import MetaError
from .media import LIMIT, validate_media


def read_media(path, digest, kind):
    if path.stat().st_size > LIMIT:
        raise MetaError("media")
    raw = path.read_bytes()
    validate_media(raw, kind)
    if sha256(raw).hexdigest() != digest:
        raise MetaError("media")
    return raw


def facebook_file(graph, target, token, raw, kind, caption):
    if not re.fullmatch(r"[1-9][0-9]{0,39}", target) or not isinstance(token, SecretStr):
        raise MetaError("invalid")
    validate_media(raw, kind)
    boundary = "newsflow" + uuid4().hex
    values = {"message" if kind == "image" else "description": caption, "published": "true"}
    parts = []
    for name, value in values.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    mime, suffix = ("image/jpeg", "jpg") if kind == "image" else ("video/mp4", "mp4")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="media.{suffix}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
    )
    body = b"".join(parts) + raw + f"\r\n--{boundary}--\r\n".encode()
    host = "graph.facebook.com" if kind == "image" else "graph-video.facebook.com"
    edge = "photos" if kind == "image" else "videos"
    return graph.request(
        "POST",
        f"https://{host}/{graph.version}/{target}/{edge}",
        {
            "Authorization": "Bearer " + token.get_secret_value(),
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
        body,
    )


def instagram_file(graph, container, token, raw):
    if not re.fullmatch(r"[1-9][0-9]{0,39}", container) or not isinstance(token, SecretStr):
        raise MetaError("invalid")
    validate_media(raw, "video")
    # Never use an arbitrary URL supplied by a remote response with the user's token.
    url = f"https://rupload.facebook.com/ig-api-upload/{graph.version}/{container}"
    data = graph.request(
        "POST",
        url,
        {
            "Authorization": "OAuth " + token.get_secret_value(),
            "Content-Type": "application/octet-stream",
            "offset": "0",
            "file_size": str(len(raw)),
        },
        raw,
    )
    if data.get("success") is not True:
        raise MetaError("unknown")
    return data
