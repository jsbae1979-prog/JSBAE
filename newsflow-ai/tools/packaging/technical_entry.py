"""Internal Step15-A binary. Requires a fresh, marked synthetic profile; never deploy."""
from pathlib import Path
import json, os, sys
import multiprocessing
multiprocessing.freeze_support()
if __name__ == "__main__":
    from technical_boundary import install
    root, bundle = install()
    from technical_probe import probe, serve
    if sys.argv[1] == "probe":
        probe(root, bundle)
    elif sys.argv[1] == "serve":
        serve(root, bundle)
    else:
        raise SystemExit("Unknown technical mode")
