"""Windows Actions only; Guard-first, bounded create_app, no server/lifespan."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import unittest

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;TOOLS=HERE.parent;PROJECT=HERE.parents[1];REPO=PROJECT.parent
if os.name!="nt" or sys.version_info[:3]!=(3,14,7) or os.environ.get("GITHUB_ACTIONS")!="true":
    raise SystemExit("Windows CI only. Never spoof CI on a PC.")
commit=os.environ["GITHUB_SHA"];runner=Path(os.environ["RUNNER_TEMP"]).resolve()
workspace=Path(tempfile.mkdtemp(prefix="newsflow-app-policy-",dir=runner))
evidence={"commit":commit,"python":sys.version.split()[0],"Windows":str(sys.getwindowsversion()),
          "local_app_executed":False,"OS_DPI":"NOT VERIFIED / unchanged","paid_API_SNS_calls":0,
          "security":{"pass":0,"fail":0,"error":0,"skip":0},"app_initialization":"NOT EXECUTED",
          "read_only_ASGI":"NOT EXECUTED","processes_started":0,"cleanup_errors":[]}
policy=None;bridge=None;native=None;app_module=None;result=None
old_env=os.environ.copy()
keep={k:v for k,v in old_env.items() if k.upper() in {"SYSTEMROOT","WINDIR","SYSTEMDRIVE","COMSPEC","NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","PATHEXT"}}
# No inherited credentials, proxy, provider flags, real profile or developer PATH.
os.environ.clear();os.environ.update(keep)
os.environ.update({"GITHUB_ACTIONS":"true","RUNNER_TEMP":str(runner),"TEMP":str(workspace),"TMP":str(workspace),
 "APPDATA":str(workspace/"Roaming"),"LOCALAPPDATA":str(workspace/"Local"),"USERPROFILE":str(workspace/"Profile"),
 "PATH":str(Path(sys.executable).parent),"NEWSFLOW_DATA_DIR":str(workspace/"not-used-default")})
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
manifest=json.loads((HERE/"SOURCE_HASHES.json").read_text(encoding="utf-8"))
assert {name:digest(HERE/name) for name in manifest}==manifest
borrowed=json.loads((HERE/"BORROWED_SOURCES.json").read_text(encoding="utf-8"))
for name,value in borrowed.items():assert digest(TOOLS/name)==value,name
evidence["borrowed_sources_before"]=dict(borrowed)
vendor=importlib.metadata.distribution("filelock")
assert vendor.version=="3.32.7"
package=Path(vendor.locate_file("filelock")).resolve()
vendor_before={str(p.relative_to(package)):digest(p) for p in package.rglob("*.py")}
sources={("filelock" if n=="__init__.py" else "filelock."+n[:-3]):str(package/n)
 for n in ("__init__.py","_api.py","_descriptor.py","_windows.py","_identity.py","_marker.py","_lease.py","_util.py")}
(workspace/"step13_guard.py").write_bytes((TOOLS/"native_guard_copy/guard_verification.py").read_bytes())
(workspace/"native_boundary.py").write_bytes((TOOLS/"native_guard_copy/native_boundary_original.py").read_bytes())
(workspace/"verification_gate.py").write_bytes((HERE/"verification_gate_app.py").read_bytes())
reads=[workspace,PROJECT/"src",PROJECT/"frontend/dist",HERE,TOOLS/"native_capability",
       TOOLS/"native_rtl_filelock",TOOLS/"native_guard_copy",Path(sys.prefix),Path(sys.base_prefix)]
(workspace/"guard-config-private.json").write_text(json.dumps({"project":str(workspace/"protected-project"),
 "read_roots":[str(p) for p in reads],"binaries":{},"browser":{"node":str(workspace/"no-node.exe")},
 "verification_capability_sha256":manifest["guard_capability.py"]}),encoding="utf-8")
sys.path[:0]=[str(workspace),str(HERE),str(TOOLS/"native_rtl_filelock"),str(TOOLS/"native_capability"),str(PROJECT/"src")]
assert "filelock" not in sys.modules and "newsflow.main" not in sys.modules
phase="Guard-first-bootstrap"
try:
    import step13_guard as guard
    guard.install()
    from verification_gate import VerificationGate
    gate=VerificationGate(workspace,PROJECT/"src",read_roots=reads);gate.install()
    evidence["bootstrap_read_roots_shared"]=all(str(p).lower() in gate.read_roots for p in reads)
    from guard_capability import NativeRegistration
    registration=NativeRegistration(gate,sources)
    guard.register_verification_capability(registration)
    legacy_native=set(guard._NATIVE);legacy_DLL=set(guard._SYSTEM_DLLS)
    import adapter
    native=adapter._Native(gate)
    from rtl_boundary import RtlBoundary
    bridge=RtlBoundary(native,registration);bridge.install_crt_wrappers()
    from app_policy import AppPolicy,LOCK_NAMES
    policy=AppPolicy(workspace,reads)
    registration.attach_app_policy(policy,manifest["app_policy.py"])
    policy.bridge=bridge
    data=Path(bridge.scope.root)
    for name in LOCK_NAMES:bridge.register_path(name)
    policy.install_sqlite([data/"newsflow.db",workspace/"sqlite-probe.db"])
    policy.install_threads()
    evidence["Guard_first"]=guard.INSTALLED and gate.installed and "filelock" not in sys.modules
    evidence["environment_secret_names_remaining"]=[k for k in os.environ if any(x in k.upper() for x in ("API_KEY","OAUTH","ACCESS_TOKEN","AUTH_TOKEN","PASSWORD"))]
    assert not evidence["environment_secret_names_remaining"]
    phase=policy.phase="new-security-tests"
    import test_app_policy
    test_app_policy.P=policy;test_app_policy.WORK=workspace;test_app_policy.BRIDGE=bridge
    class Result(unittest.TextTestResult):
        def __init__(self,*a,**k):super().__init__(*a,**k);self.passed=[]
        def addSuccess(self,t):self.passed.append(t.id());super().addSuccess(t)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromModule(test_app_policy))
    evidence["security"]={"pass":len(result.passed),"fail":len(result.failures),"error":len(result.errors),"skip":len(result.skipped),
       "passed_test_ids":result.passed,"failures":[{"id":t.id(),"traceback":tb} for t,tb in result.failures],
       "errors":[{"id":t.id(),"traceback":tb} for t,tb in result.errors]}
    evidence["security_facts"]=test_app_policy.RESULTS
    if not result.wasSuccessful():raise RuntimeError("Security boundary tests failed; app not started.")
    phase=policy.phase="create_app-import-and-initialize"
    import app_initialization as app_module
    evidence["app_facts"]=app_module.initialize(data,policy)
    evidence["app_initialization"]="PASS"
    phase=policy.phase="read-only-ASGI"
    import asyncio
    evidence["responses"]=asyncio.run(app_module.read_models(policy))
    evidence["read_only_ASGI"]="PASS"
except BaseException as error:
    frames=[];tb=error.__traceback__
    while tb is not None:
        frames.append({"file":tb.tb_frame.f_code.co_filename,"line":tb.tb_lineno,"function":tb.tb_frame.f_code.co_name})
        tb=tb.tb_next
    evidence["blocked"]={"phase":phase,"type":type(error).__name__,"reason":str(error),"frames":frames}
    print("APP_POLICY_BLOCKED="+json.dumps(evidence["blocked"]))
    if evidence["app_initialization"]!="PASS":evidence["app_initialization"]="BLOCKED" if phase.startswith("create_app") else "NOT EXECUTED"
    else:evidence["read_only_ASGI"]="BLOCKED"
finally:
    if policy is not None:policy.phase="explicit-cleanup"
    if app_module is not None:
        evidence["cleanup_errors"].extend(app_module.cleanup())
    if policy is not None:
        for connection in list(policy.sqlite_connections):
            try:connection.close()
            except Exception as error:evidence["cleanup_errors"].append({"resource":"SQLite","type":type(error).__name__,"reason":str(error)})
        for thread in policy.threads:thread.join(timeout=2)
    if bridge is not None:
        try:bridge.close()
        except Exception as error:evidence["cleanup_errors"].append({"resource":"FileLock","type":type(error).__name__,"reason":str(error)})
        evidence["lock_resources"]=bridge.status()
    if native is not None:evidence["remaining_native_handles"]=len(native._owned_handles)
    if policy is not None:
        evidence["policy"]=policy.status()
        evidence["guard_denials"]=guard.ATTEMPTS
        evidence["gate_denials"]=gate.denials
        evidence["legacy_DLL_symbol_tables_unchanged"]=legacy_native==set(guard._NATIVE) and legacy_DLL==set(guard._SYSTEM_DLLS)
    evidence["package_unchanged"]=vendor_before=={str(p.relative_to(package)):digest(p) for p in package.rglob("*.py")}
    # Never let an evidence read rejection mask the original Guard rejection.
    try:evidence["borrowed_sources_unchanged"]=all(digest(TOOLS/name)==value for name,value in borrowed.items())
    except Exception as error:
        evidence["borrowed_sources_unchanged"]=None
        evidence["integrity_read_blocked"]={"type":type(error).__name__,"reason":str(error)}
    try:evidence["sources_unchanged"]={name:digest(HERE/name) for name in manifest}==manifest
    except Exception as error:
        evidence["sources_unchanged"]=None
        evidence["source_read_blocked"]={"type":type(error).__name__,"reason":str(error)}
    # Remove synthetic DB/media/staged code only after every owned resource is closed.
    for child in list(workspace.iterdir()):
        try:
            if child.is_junction() or child.is_symlink():child.unlink()
            elif child.is_dir():shutil.rmtree(child)
            else:child.unlink()
        except Exception as error:evidence["cleanup_errors"].append({"resource":child.name,"type":type(error).__name__,"reason":str(error)})
    evidence["remaining_synthetic_entries"]=[p.name for p in workspace.iterdir()]
    evidence["tests_executed"]=result is not None
    evidence["final"]="CONDITIONAL" if evidence["app_initialization"]=="PASS" and evidence["read_only_ASGI"]=="PASS" else "BLOCKED"
    resources=evidence.get("lock_resources",{})
    unsafe_residue=(evidence.get("remaining_native_handles",0) or evidence.get("remaining_synthetic_entries")
        or any(resources.get(k,0) for k in ("native_handles","CRT_descriptors","native_buffers","unresolved_calls"))
        or evidence.get("policy",{}).get("threads_alive",0)
        or evidence.get("policy",{}).get("remaining_SQLite_connections",0))
    evidence["resource_cleanup_certified"]=not bool(unsafe_residue or evidence["cleanup_errors"])
    if unsafe_residue or evidence["cleanup_errors"] or not evidence["package_unchanged"] or evidence["borrowed_sources_unchanged"] is not True or evidence["sources_unchanged"] is not True:
        evidence["final"]="BLOCKED"
    (workspace/"app-policy-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    print("APP_POLICY_EVIDENCE_JSON="+json.dumps(evidence))
if evidence["final"]=="BLOCKED":raise SystemExit(2)
