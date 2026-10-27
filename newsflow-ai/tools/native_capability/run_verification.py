"""Standalone Windows CI entry point. Does NOT start/import the NewsFlow app."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if os.name != "nt" or sys.version_info[:3] != (3, 14, 7) or os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native verification is approved on Windows CI only; host full-app path remains blocked.")
# Credential values are neither read, printed nor copied into evidence.
credential_names = [name for name in os.environ if any(part in name.upper()
    for part in ("API_KEY", "OAUTH", "ACCESS_TOKEN", "AUTH_TOKEN", "NEWSFLOW_"))]
for name in credential_names:
    os.environ.pop(name, None)
workspace = Path(tempfile.mkdtemp(prefix="newsflow-native-", dir=os.environ["RUNNER_TEMP"]))
source = HERE.parents[2]
hashes_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in HERE.glob("*.py")}
from verification_gate import VerificationGate
gate = VerificationGate(workspace, source)
gate.install()
# Guard-first: the adapter and its DLLs are first imported/bound after gate install.
import adapter
import test_capability
native = adapter._Native(gate)
test_capability.GATE, test_capability.NATIVE = gate, native
suite = unittest.defaultTestLoader.loadTestsFromModule(test_capability)
class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.success_ids = []
    def addSuccess(self, test):
        self.success_ids.append(test.id())
        super().addSuccess(test)
result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
hashes_after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in HERE.glob("*.py")}
cleanup_failures = []
for child in list(workspace.iterdir()):
    try:
        if child.is_junction():
            child.rmdir()  # Remove the synthetic junction itself, never follow it.
        elif child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    except Exception as exc:
        cleanup_failures.append({"name": child.name, "error_type": type(exc).__name__,
                                 "message": str(exc)})
evidence = {
    "python": platform.python_version(), "platform": "Windows " + str(sys.getwindowsversion()),
    "commit": os.environ.get("GITHUB_SHA"), "workspace": str(workspace),
    "tests_run": result.testsRun,
    "pass": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
    "fail": len(result.failures), "error": len(result.errors), "skip": len(result.skipped),
    "passed_test_ids": result.success_ids,
    "remaining_native_handles": len(native._owned_handles),
    "failures": [{"id": test.id(), "traceback": tb} for test, tb in result.failures],
    "errors": [{"id": test.id(), "traceback": tb} for test, tb in result.errors],
    "gate_events": gate.events, "gate_denials": gate.denials,
    "native_DLL_SHA256": gate.native_hashes,
    "adapter_source_hashes_before": hashes_before,
    "adapter_source_hashes_after": hashes_after,
    "source_unchanged_during_tests": hashes_before == hashes_after,
    "cleanup_failures": cleanup_failures,
    "remaining_synthetic_entries": [p.name for p in workspace.iterdir()],
    "credential_environment_scrubbed": True,
    "processes_started": 0, "external_requests": 0,
    "full_app_execution": "NOT PERFORMED", "host_Guard_integration": "NOT VERIFIED",
    "OS_DPI": "NOT VERIFIED",
    "blocked_calls": ["OpenProcess", "GetProcessTimes",
        "RtlDosPathNameToNtPathName_U_WithStatus", "RtlFreeUnicodeString"],
}
path = workspace / "evidence.json"
path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print("EVIDENCE=" + str(path))
print("NATIVE_EVIDENCE_JSON=" + json.dumps(evidence, ensure_ascii=False))
if not result.wasSuccessful() or cleanup_failures or native._owned_handles or hashes_before != hashes_after:
    raise SystemExit(1)
