"""Run the scoped Fake suite with a disposable profile; never use an operating profile."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--targets", type=Path, default=PROJECT / "tools/pc_cloud_targets.txt")
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == PROJECT or PROJECT in output.parents:
        raise SystemExit("Keep synthetic state outside the source tree")
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # Remove inherited credentials, including vendor-specific aliases, without reading values.
    for name in list(env):
        upper = name.upper()
        if upper.endswith(("_KEY", "_TOKEN", "_SECRET")) or any(word in upper for word in ("API_KEY", "API_TOKEN", "CLIENT_SECRET")) or (
            upper.startswith(("NEWSFLOW_", "ANTHROPIC_", "ELEVENLABS_", "HIGGSFIELD_", "OPENAI_"))
        ):
            del env[name]
    env.update({
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(PROJECT / "tools") + os.pathsep + str(PROJECT / "src"),
        "NEWSFLOW_PC_CLOUD_ISOLATED": "1", "NEWSFLOW_DATA_DIR": str(output / "synthetic-profile"),
        "NEWSFLOW_PORT": "18765", "NEWSFLOW_LIVE_TEST": "0", "NEWSFLOW_AI_LIVE_TEST": "0",
        "NEWSFLOW_VALIDATION_OUTPUT": str(output), "NEWSFLOW_STUDIO_POLISH_EVIDENCE": str(output / "polish"),
        "NEWSFLOW_USABILITY_EVIDENCE": str(output / "screens"),
        "LOCALAPPDATA": str(output / "local"), "APPDATA": str(output / "roaming"),
        "TEMP": str(output / "temp"), "TMP": str(output / "temp"),
    })
    for folder in ("local", "roaming", "temp"):
        (output / folder).mkdir(exist_ok=True)
    # Local executable paths are explicit inputs, never a vendor connection.
    for name in ("NEWSFLOW_FFMPEG", "NEWSFLOW_FFPROBE", "NEWSFLOW_TEST_BROWSER_EXECUTABLE"):
        if name in os.environ:
            env[name] = os.environ[name]
    if args.wheel:
        env["NEWSFLOW_BUILT_WHEEL"] = str(args.wheel.resolve())
    targets = [line.strip() for line in args.targets.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    command = [sys.executable, "-B", "-m", "pytest", "-q", "-rs", "-p", "pc_cloud_guard",
               "--basetemp", str(output / "pytest"), "--junitxml", str(output / "pytest.xml"), *targets]
    result = subprocess.run(command, cwd=PROJECT, env=env, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
