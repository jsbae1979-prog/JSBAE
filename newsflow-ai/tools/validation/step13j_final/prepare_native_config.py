"""Register hashes for this isolated test run; never executes native programs."""
from pathlib import Path
import hashlib,json,os,sys

ROOT=Path(__file__).resolve().parent
assert sys.version_info[:3]==(3,14,7)
runtime=json.loads((ROOT/'runtime-config-private.json').read_text(encoding='utf-8-sig'))
project=Path(runtime['project']).resolve()
assert project.is_relative_to(ROOT) and project.name=='newsflow-ai'
python=Path(runtime['runtime']).resolve()/'Scripts/python.exe'
assert python.resolve()==Path(sys.executable).resolve()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
powershell=(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe').resolve()
vendor=Path(runtime['fixture_vendor']).resolve()
assert sorted(x.name for x in vendor.iterdir() if x.is_dir() and not x.name.endswith('.dist-info'))==['tzdata']
os_names={'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS'}
trusted_os={k.upper():v for k,v in os.environ.items() if k.upper() in os_names}
assert all(k in trusted_os for k in ('SYSTEMROOT','WINDIR','COMSPEC'))
assert Path(trusted_os['SYSTEMROOT']).resolve()==Path(trusted_os['WINDIR']).resolve()
assert Path(trusted_os['COMSPEC']).resolve()==Path(trusted_os['SYSTEMROOT']).resolve()/'System32/cmd.exe'
config={'os_environment':trusted_os,'fixture_vendor':str(vendor),'vendor_python_hashes':{str(p.relative_to(vendor)).replace('\\','/'):sha(p) for p in sorted(vendor.rglob('*.py'))},'Python':'3.14.7','python':str(python.resolve()),'python_SHA256':sha(python),
 'powershell':str(powershell),'powershell_SHA256':sha(powershell),
 'PowerShell_version':'NOT VERIFIED; executable content pinned, no version process executed',
 'source_hashes':{},'code_baseline_commit':'0a59bfb41eec6b243e4470f67cd53c1e7cd07e52'}
for key,name in [('bootstrap','native_child_bootstrap.py'),('boundary','native_boundary.py'),('guard','step13_guard.py')]:
 p=ROOT/name;config[key]=str(p);config[key+'_SHA256']=sha(p)
for rel in ('src/newsflow/main.py','src/newsflow/diagnostics.py','src/newsflow/operations/startup.py',
            'tools/ui_preview.py','tools/ci_feed_review.py','tools/pc_cloud_guard.py',
            'tests/test_autopilot_state.py','tests/test_oauth_callback.py','tests/test_creator_preview_boundary.py',
            'tests/test_pc_cloud_entrypoint.py'):
 p=project/rel;assert p.is_file();config['source_hashes'][rel]=sha(p)
manifest=ROOT/'baseline-code/manifest-safe.json'
assert manifest.is_file()
config['baseline_manifest_SHA256']=sha(manifest)
(ROOT/'native-config-private.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
print(json.dumps({'Python':'3.14.7','source_files':len(config['source_hashes']),'bridges_pinned':3,'PowerShell_identity_validate_only':True,'native_processes_executed':0}))
