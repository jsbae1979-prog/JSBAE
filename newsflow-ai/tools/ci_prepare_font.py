"""Pinned SIL-OFL Korean CI font; verify SHA256, no TLS bypass."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = "https://raw.githubusercontent.com/google/fonts/b38c5c93af322c45f633e17ac440ec1e6c94d489/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf"
SHA256 = "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    target = parser.parse_args().target
    with urlopen(URL, timeout=30) as response:
        data = response.read(15_000_001)
    if len(data) > 15_000_000 or hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("Korean font checksum validation failed.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output:
        output.write(data)
    print("Pinned Korean font SHA256 verified (SIL Open Font License; google/fonts/ofl/notosanskr/OFL.txt).")


if __name__ == "__main__":
    main()
