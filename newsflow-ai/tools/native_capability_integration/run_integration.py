"""Windows CI only. Never imports filelock or the full NewsFlow application."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent / "native_capability"
sys.path[:0] = [str(HERE), str(NATIVE)]
if os.name != "nt" or sys.version_info[:3] != (3, 14, 7) or os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Approved Windows CI only; do not spoof CI on the host.")
for name in list(os.environ):
    if any(part in name.upper() for part in ("API_KEY", "OAUTH", "ACCESS_TOKEN", "AUTH_TOKEN", "NEWSFLOW_")):
        os.environ.pop(name, None)
workspace = Path(tempfile.mkdtemp(prefix="newsflow-contract-", dir=os.environ["RUNNER_TEMP"]))
source = HERE.parents[2]
tracked = [*HERE.glob("*.py"), HERE/"contract_snapshot.json", *NATIVE.glob("*.py")]
before = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
from verification_gate import VerificationGate, Denied
gate = VerificationGate(workspace, source)
gate.install()
def no_upstream_or_product_import(event, args):
    if event == "import" and (args[0] == "filelock" or args[0].startswith("filelock.") or
                               args[0] == "newsflow" or args[0].startswith("newsflow.")):
        raise Denied("upstream-runtime-and-product-import-not-authorized")
sys.addaudithook(no_upstream_or_product_import)
from contract_probe import inspect_installed
probe = inspect_installed(HERE/"contract_snapshot.json")
import adapter
import test_capability
import test_contract_bridge
native = adapter._Native(gate)
test_capability.GATE, test_capability.NATIVE = gate, native
test_contract_bridge.GATE, test_contract_bridge.NATIVE = gate, native
test_contract_bridge.PROBE = probe
selected = [
    "test_01_guard_first", "test_02_real_exclusive_lock_and_release",
    "test_05_raw_and_forged_handles", "test_20_external_PID_blocked_before_OS",
    "test_21_raw_DLL_blocked", "test_27_parent_junction_is_denied",
    "test_31_handle_path_mismatch_is_denied", "test_33_failed_unlock_preserves_state",
]
suite = unittest.TestSuite([
    unittest.defaultTestLoader.loadTestsFromModule(test_contract_bridge),
    unittest.TestSuite(test_capability.CapabilityTests(name) for name in selected),
])
class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.success_ids = []
    def addSuccess(self, test):
        self.success_ids.append(test.id())
        super().addSuccess(test)
result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
after = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
# Preserve synthetic state journals as evidence before cleanup; no secret values.
journals = []
for scope in workspace.glob("scope-*"):
    if scope.is_dir() and not scope.is_junction():
        for journal in scope.glob("state-*.json"):
            journals.append(json.loads(journal.read_text(encoding="utf-8")))
cleanup_errors = []
for child in list(workspace.iterdir()):
    try:
        if child.is_junction():
            child.rmdir()
        elif child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    except Exception as error:
        cleanup_errors.append({"name": child.name, "type": type(error).__name__, "message": str(error)})
evidence = {
    "commit": os.environ.get("GITHUB_SHA"), "python": sys.version.split()[0],
    "Windows": str(sys.getwindowsversion()),
    "pass": result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
    "fail": len(result.failures), "error": len(result.errors), "skip": len(result.skipped),
    "new_test_count": 24, "selected_prior_test_count": len(selected),
    "passed_test_ids": result.success_ids,
    "failures": [{"id": test.id(), "traceback": tb} for test,tb in result.failures],
    "errors": [{"id": test.id(), "traceback": tb} for test,tb in result.errors],
    "filelock_source_contract": probe,
    "source_hashes_before": before, "source_hashes_after": after,
    "source_unchanged": before == after, "native_DLL_SHA256": gate.native_hashes,
    "gate_events": gate.events, "gate_denials": gate.denials,
    "synthetic_journal_count": len(journals), "synthetic_final_journals": journals,
    "remaining_native_handles": len(native._owned_handles),
    "cleanup_errors": cleanup_errors,
    "remaining_synthetic_entries": [p.name for p in workspace.iterdir()],
    "upstream_filelock_imported": any(n=="filelock" or n.startswith("filelock.") for n in sys.modules),
    "product_imported": any(n=="newsflow" or n.startswith("newsflow.") for n in sys.modules),
    "new_processes_created": 0, "external_API_requests": 0,
    "existing_Guard_runtime_registration": "BLOCKED",
    "local_full_app": "BLOCKED / not performed", "OS_DPI": "NOT VERIFIED / unchanged",
}
(workspace/"integration-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
print("INTEGRATION_EVIDENCE_JSON="+json.dumps(evidence))
if (not result.wasSuccessful() or cleanup_errors or native._owned_handles or before != after or
    not probe["all_source_contracts_match"] or evidence["upstream_filelock_imported"] or evidence["product_imported"]):
    raise SystemExit(1)
