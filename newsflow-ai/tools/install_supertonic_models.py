"""Explicit one-time official model download. Runtime synthesis never downloads assets."""

import concurrent.futures
import ssl
import urllib.request
from uuid import uuid4

from newsflow.video.supertonic_assets import DEFAULT_MODELS, MANIFEST, verify_file


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("Non-HTTPS model redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(entry):
    root = DEFAULT_MODELS.resolve()
    target = root / entry["name"]
    if not target.resolve().is_relative_to(root):
        raise ValueError("Invalid model path")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not verify_file(target, entry):
            raise ValueError("Existing model failed integrity check; preserved without overwrite")
        return entry["name"]
    temporary = target.with_name(target.name + ".download-" + uuid4().hex)
    uri = f"https://huggingface.co/{MANIFEST['repository']}/resolve/{MANIFEST['revision']}/{entry['name']}"
    opener = urllib.request.build_opener(SecureRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(uri, timeout=60) as response, temporary.open("xb") as output:
        size = 0
        for block in iter(lambda: response.read(1024 * 1024), b""):
            size += len(block)
            if size > entry["size"]:
                raise ValueError("Model size exceeded pinned manifest")
            output.write(block)
    if not verify_file(temporary, entry):
        raise ValueError("Model integrity check failed; partial file retained for diagnosis")
    temporary.rename(target)
    return entry["name"]


if __name__ == "__main__":
    print("Downloading pinned official Supertonic 3 archive; approximately 401 MB; no API inference.", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for name in executor.map(download, MANIFEST["files"]):
            print("Verified:", name, flush=True)
