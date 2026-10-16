"""Pinned official archive assets, checked before local ONNX inference."""

import hashlib
import json
import os
from pathlib import Path

from .tts import TTSError

MANIFEST = json.loads(Path(__file__).with_name("supertonic3_manifest.json").read_text(encoding="utf-8-sig"))
DEFAULT_MODELS = Path(__file__).resolve().parents[3] / "local-models/supertonic3"


def model_dir() -> Path:
    return Path(os.environ.get("NEWSFLOW_SUPERTONIC_MODELS", str(DEFAULT_MODELS))).resolve()


def verify_file(path: Path, entry: dict) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["size"]:
        return False
    digest = hashlib.sha256() if entry["sha256"] else hashlib.sha1(usedforsecurity=False)
    if not entry["sha256"]:
        digest.update(f"blob {entry['size']}\0".encode())
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == (entry["sha256"] or entry["git_blob"])


def verify_models(root: Path) -> None:
    for entry in MANIFEST["files"]:
        path = root / entry["name"]
        if not path.resolve().is_relative_to(root.resolve()) or not verify_file(path, entry):
            raise TTSError("Supertonic 3 고정 모델이 없거나 무결성 검증에 실패했습니다. 설치 도구를 확인하세요.")
