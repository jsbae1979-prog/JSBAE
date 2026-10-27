"""Configure a disposable runner profile; no service credentials, no production profile."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

assert sys.version_info[:3] == (3,14,7)
source=Path(__file__).parent;project=source.parents[2]
root=Path(sys.argv[1]).resolve();assert not root.exists();assert not root.is_relative_to(project)
root.mkdir(parents=True)
for path in (source.parent/'step13h').iterdir():
 if path.is_file() and path.name!='prepare_windows.py':shutil.copyfile(path,root/path.name)
for filename in ('run_browser_phase.py','browser_bootstrap.py','test_guard_security.py'):
 shutil.copyfile(source/filename,root/filename)
for name in ('home/AppData/Local','home/AppData/Roaming','temp','artifacts'):(root/name).mkdir(parents=True,exist_ok=True)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
import playwright

node=Path(playwright.__file__).parent/'driver/node.exe';cli=node.parent/'package/cli.js'
chrome=Path(os.environ['NEWSFLOW_TEST_BROWSER_EXECUTABLE']).resolve()
ffmpeg=Path(os.environ['NEWSFLOW_FFMPEG']).resolve();ffprobe=Path(os.environ['NEWSFLOW_FFPROBE']).resolve()
fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
reads=[root,project,Path(sys.prefix),Path(sys.base_prefix),fonts]
browser={'node':str(node),'node_SHA256':sha(node),'cli':str(cli),'cli_SHA256':sha(cli),'chrome':str(chrome),'chrome_SHA256':sha(chrome),'preload':str(root/'node_boundary.cjs'),'preload_SHA256':sha(root/'node_boundary.cjs')}
(root/'guard-config-private.json').write_text(json.dumps({'root':str(root),'project':str(project),'read_roots':list(map(str,reads)),'binaries':{str(ffmpeg):sha(ffmpeg),str(ffprobe):sha(ffprobe)},'browser':browser}),encoding='utf-8')
(root/'node-config-private.json').write_text(json.dumps({'root':str(root),'chrome':str(chrome),'chrome_SHA256':sha(chrome),'operating':str(root.parent/'forbidden-operating-profile'),'allowed_reads':list(map(str,reads+[chrome.parent,Path(os.environ.get('WINDIR','C:/Windows'))])),'log':str(root/'node-events-private.jsonl')}),encoding='utf-8')
(root/'runtime-config-private.json').write_text(json.dumps({'project':str(project),'runtime':sys.prefix,'fixture_vendor':str(root)}),encoding='utf-8')
# Infrastructure setup has finished. Each test child starts under the original Guard.
summaries=[]
for phase in ('security','i_contracts','i_tiktok3','i_sns_contracts','h','hflow'):
 result=subprocess.run([sys.executable,'-I','-S','-B',str(root/'run_browser_phase.py'),phase],cwd=root,check=False)
 if result.returncode:
  log=root/(phase+'-process.log')
  if log.exists():
   print('Synthetic test child diagnostic:',log.read_text(encoding='utf-8',errors='replace')[-12000:],flush=True)
  raise SystemExit(result.returncode)

 import xml.etree.ElementTree as ET
 suites=list(ET.parse(root/phase/'pytest.xml').iter('testsuite'))
 summary={'phase':phase,**{key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}}
 cases=list(ET.parse(root/phase/'pytest.xml').iter('testcase'))
 expected={'security':78,'i_contracts':24,'i_tiktok3':65,'i_sns_contracts':314,'h':123,'hflow':1}[phase]
 summary['testcase_records']=len(cases)
 summary['expected_records']=expected
 evidence_path=root/'ci-collected-IDs-safe.json'
 prior=json.loads(evidence_path.read_text()) if evidence_path.exists() else []
 prior.append({'phase':phase,'suite_tests':summary['tests'],'testcase_records':len(cases),'expected_records':expected,'IDs':[c.get('classname','')+'::'+c.get('name','') for c in cases]})
 evidence_path.write_text(json.dumps(prior,indent=2))
 log=root/(phase+'-process.log')
 if log.exists():
  for line in log.read_text(encoding='utf-8',errors='replace').splitlines():
   if ' passed' in line or ' failed' in line or ' error' in line:print('pytest-summary: '+line[-600:],flush=True)
 assert len(cases)==expected and summary['tests']==expected, 'CI test ID count mismatch; never treat missing cases as PASS'
 assert all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in cases)
 summaries.append(summary)
 print(json.dumps(summary),flush=True)
(root/'ci-summary-safe.json').write_text(json.dumps({'Python':'3.14.7','phases':summaries,'real_provider_calls':0,'operating_profile_used':False}),encoding='utf-8')
