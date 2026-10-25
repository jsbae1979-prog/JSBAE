"""Build a disposable CI source/profile and run only approved final phases."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

assert os.name == "nt" and sys.version_info[:3] == (3, 14, 7)
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

source = Path(__file__).resolve().parent
checkout = source.parents[2]
root = Path(sys.argv[1]).resolve()
assert not root.exists() and not root.is_relative_to(checkout) and not checkout.is_relative_to(root)
definitions = json.loads((source / "phases-safe.json").read_text(encoding="utf-8-sig"))["phases"]
assert all(type(item["expected"]) is int and item["expected"] > 0 for item in definitions), (
    "Freeze phase testcase counts from reviewed local XML before CI; never guess coverage"
)
root.mkdir(parents=True)
project = root / "worktree/newsflow-ai"
project.mkdir(parents=True)

# Copy only checked-out source/tests/tools and required top-level launch manifests.
# No .git, docs/reports, environment files, databases, backups or user media roots.
ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache",
                                ".venv", "validation-output", "dist", "build", ".git")
for directory in ("src", "tests", "tools"):
    source_tree = checkout / directory
    assert not source_tree.is_symlink() and not source_tree.is_junction()
    for entry in source_tree.rglob("*"):
        assert not entry.is_symlink() and not entry.is_junction(), "Source fixture links are not permitted"
    shutil.copytree(source_tree, project / directory, ignore=ignore, symlinks=False)
for name in ("pyproject.toml", "requirements-dev.lock", "requirements-supertonic.lock",
             "run.bat", "setup.bat", "README.md", "AGENTS.md", "START_HERE.html"):
    shutil.copyfile(checkout / name, project / name)

# Existing reviewed browser/FFmpeg boundary; final native overlay comes from core review.
for name in ("step13_guard.py", "step13_fixtures.py", "browser_boundary.py", "node_boundary.cjs",
             "test_browser_boundary_security.py", "test_news_image_gui_flow.py",
             "evidence-env-keys-safe.json", "original91-IDs-safe.json"):
    shutil.copyfile(source.parent / "step13h" / name, root / name)
for name in ("run_browser_phase.py", "browser_bootstrap.py", "test_guard_security.py"):
    shutil.copyfile(source.parent / "step13j" / name, root / name)
for name in ("native_boundary.py", "native_child_bootstrap.py", "prepare_native_config.py",
             "test_native_boundary_security.py", "step13_guard.py"):
    shutil.copyfile(source / name, root / name)
# A reviewed final fixture overlay is required for native child cleanup and immutable code fixtures.
for name in ("step13_fixtures.py", "browser_bootstrap.py", "run_browser_phase.py"):
    if (source / name).is_file():
        shutil.copyfile(source / name, root / name)
for name in ("j_native-targets-safe.json", "j_models-targets-safe.json",
             "j_mode_gui-targets-safe.json", "j_flow-targets-safe.json"):
    shutil.copyfile(source / name, root / name)
(root / "j_native_security-targets-safe.json").write_text(
    json.dumps([str(root / "test_native_boundary_security.py")]), encoding="utf-8"
)
for path in ("home/AppData/Local", "home/AppData/Roaming", "temp", "artifacts"):
    (root / path).mkdir(parents=True, exist_ok=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Validate exact immutable baseline bytes, not mutable operating sources or Git refs.
manifest = json.loads((source / "baseline-code-manifest-safe.json").read_text(encoding="utf-8-sig"))
baseline = checkout.parent / ".step13j-code-baseline"
assert subprocess.run(["git", "-C", str(baseline), "rev-parse", "HEAD"], check=True,
                      capture_output=True, text=True).stdout.strip() == manifest["commit"]
for relative, expected in manifest["files"].items():
    # Read raw Git blob bytes, not checkout bytes: .gitattributes may force CRLF.
    raw = subprocess.run(
        ["git", "-C", str(baseline), "show", "--no-textconv", "--no-ext-diff",
         manifest["commit"] + ":" + relative],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    assert hashlib.sha256(raw).hexdigest() == expected, "Pinned baseline blob mismatch"
    dest = root / "baseline-code/files" / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as output:
        output.write(raw)
    assert sha(dest) == expected
(root / "baseline-code/manifest-safe.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(root / "baseline-integrity-safe.json").write_text(json.dumps({
    "commit": manifest["commit"], "files_verified": len(manifest["files"]),
    "content_mismatches": 0, "operating_Git_used": False,
    "read_method": "pinned Git blob binary stdout; checkout line endings unused",
}), encoding="utf-8")

import tzdata
vendor = root / "fixture-vendor"
shutil.copytree(Path(tzdata.__file__).parent, vendor / "tzdata", ignore=ignore)

import playwright
node = Path(playwright.__file__).parent / "driver/node.exe"
cli = node.parent / "package/cli.js"
chrome = Path(os.environ["NEWSFLOW_TEST_BROWSER_EXECUTABLE"]).resolve()
ffmpeg = Path(os.environ["NEWSFLOW_FFMPEG"]).resolve()
ffprobe = Path(os.environ["NEWSFLOW_FFPROBE"]).resolve()
for binary in (node, cli, chrome, ffmpeg, ffprobe):
    assert binary.is_file() and not binary.is_symlink()
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
reads = [root, project, Path(sys.prefix), Path(sys.base_prefix), fonts]
browser = {"node": str(node), "node_SHA256": sha(node), "cli": str(cli), "cli_SHA256": sha(cli),
           "chrome": str(chrome), "chrome_SHA256": sha(chrome),
           "preload": str(root / "node_boundary.cjs"), "preload_SHA256": sha(root / "node_boundary.cjs")}
(root / "guard-config-private.json").write_text(json.dumps({
    "root": str(root), "project": str(project), "read_roots": list(map(str, reads)),
    "binaries": {str(ffmpeg): sha(ffmpeg), str(ffprobe): sha(ffprobe)}, "browser": browser,
}), encoding="utf-8")
(root / "node-config-private.json").write_text(json.dumps({
    "root": str(root), "chrome": str(chrome), "chrome_SHA256": sha(chrome),
    "operating": str(root.parent / "forbidden-operating-profile"),
    "allowed_reads": list(map(str, reads + [chrome.parent, Path(os.environ.get("WINDIR", "C:/Windows"))])),
    "log": str(root / "node-events-private.jsonl"),
}), encoding="utf-8")
(root / "runtime-config-private.json").write_text(json.dumps({
    "project": str(project), "runtime": sys.prefix, "fixture_vendor": str(vendor),
}), encoding="utf-8")
subprocess.run([sys.executable, "-I", "-S", "-B", str(root / "prepare_native_config.py")],
               cwd=root, check=True)

# Helpers are setup code only; every test child is launched through the reviewed Job+Guard.
sys.path.insert(0, str(source))
from summarize import record_phase, write_summary
summaries = []
write_summary(root, definitions, summaries)
for definition in definitions:
    phase = definition["name"]
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(root / "run_browser_phase.py"), phase],
                            cwd=root, check=False)
    expected_ids = None
    if definition.get("expected_ids_file"):
        expected_ids = json.loads((source / definition["expected_ids_file"]).read_text(encoding="utf-8-sig"))
    summary = record_phase(root, phase, definition["expected"], result.returncode, expected_ids)
    summaries.append(summary)
    write_summary(root, definitions, summaries)
    log = root / (phase + "-process.log")
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if " passed" in line or " failed" in line or " error" in line:
                print("pytest-summary: " + line[-600:], flush=True)
    if summary["status"] != "PASS":
        # Keep raw synthetic diagnostics only on the disposable runner, never upload them.
        print("Phase failed; safe failure IDs and bounded redacted diagnostics recorded. Raw child logs remain on this runner.", flush=True)
        raise SystemExit(result.returncode or 1)






