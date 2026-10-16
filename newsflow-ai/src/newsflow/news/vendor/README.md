# Frozen robots policy

`robotparser312.py` is the unmodified CPython v3.12.10 `Lib/urllib/robotparser.py`.
Source: https://github.com/python/cpython/blob/v3.12.10/Lib/urllib/robotparser.py
SHA256: `644cc6d2b09948e8782cb1e7dea3bb39a2d83932c67e7a8eae65a711318c002c`.
License: `LICENSE-CPYTHON.txt` (CPython upstream LICENSE).

Python 3.14 changed rule matching/group semantics. Both the RSS adapter and review
tool use this snapshot to retain the accepted first-match, prefix and user-agent
policy on 3.12 and 3.14. Network fetching remains in PublicTransport; do not call
the snapshot's standalone `read()` method. Existing robots/SSRF tests remain active.
Upstream source is exempt from project style rewrites to preserve its checksum.
