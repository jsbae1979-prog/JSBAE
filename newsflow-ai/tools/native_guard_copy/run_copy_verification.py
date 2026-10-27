"""CI-only real verification Guard copy + native/CRT boundary. Never starts app."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[2]
NATIVE=HERE.parent/"native_capability"
CONTRACT=HERE.parent/"native_capability_integration"
if os.name!="nt" or sys.version_info[:3]!=(3,14,7) or os.environ.get("GITHUB_ACTIONS")!="true":
    raise SystemExit("Approved Windows CI only; do not spoof a local CI environment.")
for key in list(os.environ):
    if any(x in key.upper() for x in ("API_KEY","OAUTH","ACCESS_TOKEN","AUTH_TOKEN","NEWSFLOW_")):
        os.environ.pop(key,None)
manifest=json.loads((HERE/"SOURCE_HASHES.json").read_text(encoding="utf-8"))
provenance=json.loads((HERE/"GUARD_COPY_PROVENANCE.json").read_text(encoding="utf-8"))
before={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in manifest}
assert before==manifest
assert before["guard_original.py"]==provenance["original_guard_sha256"]
assert before["guard_verification.py"]==provenance["verification_guard_sha256"]
original=ast.parse((HERE/"guard_original.py").read_bytes())
copy=ast.parse((HERE/"guard_verification.py").read_bytes())
old_defs={n.name:n for n in original.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
new_defs={n.name:n for n in copy.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
for name,node in old_defs.items():
    other=new_defs[name]
    if name=="audit": other.body=other.body[1:]
    if name=="_guarded_windll": other.body=other.body[2:]
    assert ast.dump(node,include_attributes=False)==ast.dump(other,include_attributes=False),name
# Existing module statements are unchanged, with only appended hook definitions.
for old,new in zip(original.body,copy.body):
    if isinstance(old,(ast.FunctionDef,ast.ClassDef)):
        continue
    assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)
workspace=Path(tempfile.mkdtemp(prefix="newsflow-guard-copy-",dir=os.environ["RUNNER_TEMP"]))
(workspace/"step13_guard.py").write_bytes((HERE/"guard_verification.py").read_bytes())
(workspace/"native_boundary.py").write_bytes((HERE/"native_boundary_original.py").read_bytes())
config={"project":str(workspace/"protected-project"),
        "read_roots":[str(workspace),str(SOURCE),sys.prefix,sys.base_prefix],
        "binaries":{},"browser":{"node":str(workspace/"no-approved-node.exe")},
        "verification_capability_sha256":manifest["guard_capability.py"]}
(workspace/"guard-config-private.json").write_text(json.dumps(config),encoding="utf-8")
sys.path[:0]=[str(workspace),str(HERE),str(NATIVE),str(CONTRACT)]
import step13_guard as guard
facts={"provenance":provenance,"registration_before_install_denied":False,"initialization_order":[]}
try:
    guard.register_verification_capability(None)
except PermissionError:
    facts["registration_before_install_denied"]=True
else:
    raise AssertionError("registration succeeded before Guard")
guard.install()
facts["initialization_order"].append("verification-Guard-copy-installed")
from verification_gate import VerificationGate
gate=VerificationGate(workspace,SOURCE)
gate.install()
facts["initialization_order"].append("capability-gate-installed")
from guard_capability import NativeRegistration
registration=NativeRegistration(gate)
guard.register_verification_capability(registration)
facts["initialization_order"].append("registered-source-pinned-capability")
native_keys_before=set(guard._NATIVE)
DLL_keys_before=set(guard._SYSTEM_DLLS)
from contract_probe import inspect_installed
upstream_source=inspect_installed(CONTRACT/"contract_snapshot.json")
import adapter
native=adapter._Native(gate)
facts["initialization_order"].append("native-binding-after-registration")
import test_copy_boundary
import test_capability
test_copy_boundary.NATIVE=native
test_copy_boundary.REGISTRATION=registration
test_copy_boundary.GUARD=guard
test_copy_boundary.FACTS=facts
test_capability.GATE,test_capability.NATIVE=gate,native
selected=["test_27_parent_junction_is_denied","test_31_handle_path_mismatch_is_denied"]
suite=unittest.TestSuite([
    unittest.defaultTestLoader.loadTestsFromModule(test_copy_boundary),
    unittest.TestSuite(test_capability.CapabilityTests(name) for name in selected)])
class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.passed=[]
    def addSuccess(self,test):
        self.passed.append(test.id()); super().addSuccess(test)
result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
after={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in manifest}
cleanup_errors=[]
for child in list(workspace.iterdir()):
    try:
        if child.is_junction(): child.rmdir()
        elif child.is_dir() and not child.is_symlink(): shutil.rmtree(child)
        else: child.unlink()
    except Exception as error:
        cleanup_errors.append({"name":child.name,"type":type(error).__name__,"message":str(error)})
import native_boundary
states=[b.status() for b in test_copy_boundary.ALL_BOUNDARIES]
facts["legacy_DLL_symbol_tables_unchanged"]=native_keys_before==set(guard._NATIVE) and DLL_keys_before==set(guard._SYSTEM_DLLS)
evidence={"commit":os.environ.get("GITHUB_SHA"),"python":sys.version.split()[0],
 "Windows":str(sys.getwindowsversion()),
 "pass":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
 "fail":len(result.failures),"error":len(result.errors),"skip":len(result.skipped),
 "new_tests":27,"selected_previous_tests":len(selected),"passed_test_ids":result.passed,
 "failures":[{"id":t.id(),"traceback":tb} for t,tb in result.failures],
 "errors":[{"id":t.id(),"traceback":tb} for t,tb in result.errors],
 "guard_copy":facts,"filelock_source_contract":upstream_source,
 "new_source_hashes_before":before,"new_source_hashes_after":after,
 "source_unchanged":before==after,"native_DLL_SHA256":gate.native_hashes,
 "capability_private_binding_count":registration.native_dispatches,
 "capability_CRT_dispatch_count":registration.crt_dispatches,
 "guard_denials":guard.ATTEMPTS,"gate_denials":gate.denials,
 "remaining_native_handles":len(native._owned_handles),
 "remaining_CRT_descriptors":sum(s["descriptors"] for s in states),
 "remaining_buffers":sum(s["buffers"] for s in states),
 "unresolved_transfers":sum(s["unresolved_transfers"] for s in states),
 "descriptor_boundary_final_states":states,"cleanup_errors":cleanup_errors,
 "remaining_synthetic_entries":[p.name for p in workspace.iterdir()],
 "native_boundary_launches":len(native_boundary.LAUNCHES),
 "legacy_owned_handles":len(guard._OWNED_HANDLES),
 "product_imported":any(n=="newsflow" or n.startswith("newsflow.") for n in sys.modules),
 "upstream_filelock_full_imported":"filelock" in sys.modules,
 "Rtl_native_conversion_and_free":"BLOCKED; Python-owned buffers only",
 "host_full_app":"NOT PERFORMED","OS_DPI":"NOT VERIFIED / unchanged",
 "paid_API_SNS_requests":0}
(workspace/"copy-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
print("GUARD_COPY_EVIDENCE_JSON="+json.dumps(evidence))
if (not result.wasSuccessful() or cleanup_errors or native._owned_handles or
    evidence["remaining_CRT_descriptors"] or evidence["remaining_buffers"] or evidence["unresolved_transfers"] or
    before!=after or not facts["legacy_DLL_symbol_tables_unchanged"] or
    not upstream_source["all_source_contracts_match"] or evidence["product_imported"] or evidence["native_boundary_launches"]):
    raise SystemExit(1)
