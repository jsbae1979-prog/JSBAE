"""Windows CI only: real Rtl APIs and unchanged filelock, no application."""
import ast
import hashlib
import importlib.metadata
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
TOOLS=HERE.parent;OLD=TOOLS/"native_guard_copy";NATIVE=TOOLS/"native_capability";CONTRACT=TOOLS/"native_capability_integration"
if os.name!="nt" or sys.version_info[:3]!=(3,14,7) or os.environ.get("GITHUB_ACTIONS")!="true":
    raise SystemExit("Windows CI only; do not spoof CI locally.")
for key in list(os.environ):
    if any(x in key.upper() for x in ("API_KEY","OAUTH","ACCESS_TOKEN","AUTH_TOKEN","NEWSFLOW_")):os.environ.pop(key,None)
workspace=Path(tempfile.mkdtemp(prefix="newsflow-real-filelock-",dir=os.environ["RUNNER_TEMP"]))
def startup_failure(kind,value,tb):
    evidence={"commit":os.environ.get("GITHUB_SHA"),"startup_blocked":True,"tests_executed":False,
              "error_type":kind.__name__,"reason":str(value),
              "pass":0,"fail":0,"error":0,"skip":0,
              "full_app_executed":False,"native_resources":"not certified after incomplete startup"}
    try:
        (workspace/"real-filelock-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
        print("REAL_FILELOCK_EVIDENCE_JSON="+json.dumps(evidence))
    finally:sys.__excepthook__(kind,value,tb)
sys.excepthook=startup_failure
manifest=json.loads((HERE/"SOURCE_HASHES.json").read_text(encoding="utf-8"))
before={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in manifest}
assert before==manifest
borrowed=json.loads((HERE/"BORROWED_SOURCES.json").read_text(encoding="utf-8"))
def borrowed_hash(name):
    data=(TOOLS/name).read_bytes()
    # The repository pins .py to LF; JSON may check out as CRLF on Windows.
    # Only CRLF -> LF normalization is allowed for this metadata, not value changes.
    return hashlib.sha256(data.replace(b"\r\n",b"\n") if name.endswith(".json") else data).hexdigest()
borrowed_raw_hashes={name:hashlib.sha256((TOOLS/name).read_bytes()).hexdigest() for name in borrowed}
for name,digest in borrowed.items():
    assert borrowed_hash(name)==digest,name
dist=importlib.metadata.distribution("filelock")
assert dist.version=="3.32.7"
package_root=Path(dist.locate_file("filelock")).resolve()
vendor_before={str(p.relative_to(package_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in package_root.rglob("*.py")}
sources={("filelock" if name=="__init__.py" else "filelock."+name[:-3]):str(package_root/name)
         for name in ("__init__.py","_api.py","_descriptor.py","_windows.py","_identity.py","_marker.py","_lease.py","_util.py")}
assert "filelock" not in sys.modules
(workspace/"step13_guard.py").write_bytes((OLD/"guard_verification.py").read_bytes())
(workspace/"native_boundary.py").write_bytes((OLD/"native_boundary_original.py").read_bytes())
(workspace/"verification_gate.py").write_bytes((HERE/"verification_gate_copy.py").read_bytes())
config={"project":str(workspace/"protected-project"),"read_roots":[str(workspace),str(SOURCE),sys.prefix,sys.base_prefix],
"binaries":{},"browser":{"node":str(workspace/"no-node.exe")},"verification_capability_sha256":manifest["guard_capability.py"]}
(workspace/"guard-config-private.json").write_text(json.dumps(config),encoding="utf-8")
sys.path[:0]=[str(workspace),str(HERE),str(NATIVE),str(CONTRACT)]
import step13_guard as guard
guard.install()
from verification_gate import VerificationGate
gate=VerificationGate(workspace,SOURCE);gate.install()
from guard_capability import NativeRegistration
registration=NativeRegistration(gate,sources)
guard.register_verification_capability(registration)
native_keys=set(guard._NATIVE);dll_keys=set(guard._SYSTEM_DLLS)
from contract_probe import inspect_installed
probe=inspect_installed(CONTRACT/"contract_snapshot.json")
assert probe["all_source_contracts_match"]
import adapter
native=adapter._Native(gate)
from rtl_boundary import RtlBoundary
bridge=RtlBoundary(native,registration)
bridge.install_crt_wrappers()
FACTS={"Guards_installed_before_filelock":guard.INSTALLED and gate.installed and "filelock" not in sys.modules,
       "source_contract_match":probe["all_source_contracts_match"]}
import filelock
FACTS["actual_package_import"]=filelock.__version__
FACTS["actual_FileLock_class"]=filelock.FileLock.__module__+"."+filelock.FileLock.__name__
code_objects=[filelock.BaseFileLock.acquire.__code__,filelock.BaseFileLock.release.__code__,
              filelock.WindowsFileLock._acquire.__code__,filelock.WindowsFileLock._release.__code__]
import test_real_filelock
test_real_filelock.B=bridge;test_real_filelock.FACTS=FACTS
import test_capability
test_capability.GATE=gate;test_capability.NATIVE=native
selected=["test_27_parent_junction_is_denied","test_31_handle_path_mismatch_is_denied"]
suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(test_real_filelock),
 unittest.TestSuite(test_capability.CapabilityTests(name) for name in selected)])
class Result(unittest.TextTestResult):
    def __init__(self,*a,**k):super().__init__(*a,**k);self.passed=[]
    def addSuccess(self,test):self.passed.append(test.id());super().addSuccess(test)
result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
status_before_close=bridge.status()
close_errors=[]
try:bridge.close()
except Exception as error:close_errors.append({"type":type(error).__name__,"message":str(error)})
status=bridge.status()
vendor_after={str(p.relative_to(package_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in package_root.rglob("*.py")}
after={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in manifest}
unchanged_codes=all(a is b for a,b in zip(code_objects,[
 filelock.BaseFileLock.acquire.__code__,filelock.BaseFileLock.release.__code__,
 filelock.WindowsFileLock._acquire.__code__,filelock.WindowsFileLock._release.__code__]))
cleanup_errors=[]
for child in list(workspace.iterdir()):
    try:
        if child.is_junction():child.rmdir()
        elif child.is_dir() and not child.is_symlink():shutil.rmtree(child)
        else:child.unlink()
    except Exception as error:cleanup_errors.append({"name":child.name,"type":type(error).__name__,"message":str(error)})
import native_boundary
evidence={"commit":os.environ.get("GITHUB_SHA"),"python":sys.version.split()[0],"Windows":str(sys.getwindowsversion()),
"pass":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
"fail":len(result.failures),"error":len(result.errors),"skip":len(result.skipped),
"new_tests":26,"selected_previous_tests":2,"passed_test_ids":result.passed,
"failures":[{"id":t.id(),"traceback":tb} for t,tb in result.failures],
"errors":[{"id":t.id(),"traceback":tb} for t,tb in result.errors],
"facts":FACTS,"filelock_methods_not_replaced":unchanged_codes,
"filelock_source_hashes_before":vendor_before,"filelock_source_hashes_after":vendor_after,
"filelock_package_files_unchanged":vendor_before==vendor_after,
"native_status_before_scope_close":status_before_close,"native_status_after_scope_close":status,
"remaining_native_handles":len(native._owned_handles),"close_errors":close_errors,
"cleanup_errors":cleanup_errors,"remaining_synthetic_entries":[p.name for p in workspace.iterdir()],
"source_hashes_before":before,"source_hashes_after":after,"source_unchanged":before==after,
"borrowed_sources_unchanged":all(borrowed_hash(name)==digest for name,digest in borrowed.items()),
"borrowed_raw_hashes":borrowed_raw_hashes,
"borrowed_JSON_hash_rule":"CRLF-to-LF only; all code uses exact byte SHA256",
"legacy_DLL_symbol_tables_unchanged":native_keys==set(guard._NATIVE) and dll_keys==set(guard._SYSTEM_DLLS),
"native_DLL_SHA256":gate.native_hashes,"guard_denials":guard.ATTEMPTS,"gate_denials":gate.denials,
"private_native_bindings":registration.native_bindings,"filelock_facade_bindings":registration.facade_bindings,
"CRT_calls":registration.crt_calls,"native_boundary_launches":len(native_boundary.LAUNCHES),
"product_imported":any(n=="newsflow" or n.startswith("newsflow.") for n in sys.modules),
"host_app_executed":False,"OS_DPI":"NOT VERIFIED / unchanged","paid_API_SNS_calls":0}
(workspace/"real-filelock-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
print("REAL_FILELOCK_EVIDENCE_JSON="+json.dumps(evidence))
if (not result.wasSuccessful() or close_errors or cleanup_errors or native._owned_handles
 or status["native_handles"] or status["CRT_descriptors"] or status["native_buffers"] or status["unresolved_calls"]
 or vendor_before!=vendor_after or before!=after or not unchanged_codes or evidence["product_imported"]
 or not evidence["legacy_DLL_symbol_tables_unchanged"] or evidence["native_boundary_launches"]):
    raise SystemExit(1)
