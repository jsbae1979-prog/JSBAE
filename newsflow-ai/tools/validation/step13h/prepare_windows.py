"""Configure a disposable runner profile; no service credentials, no production profile."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
assert sys.version_info[:3] == (3,14,7)
source=Path(__file__).parent;project=source.parents[2]
root=Path(sys.argv[1]).resolve();assert not root.exists();assert not root.is_relative_to(project)
root.mkdir(parents=True)
for path in source.iterdir():
 if path.is_file() and path.name!='prepare_windows.py':shutil.copyfile(path,root/path.name)
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
for phase in ('security','h'):
 result=subprocess.run([sys.executable,'-I','-S','-B',str(root/'run_browser_phase.py'),phase],cwd=root,check=False)
 if result.returncode:raise SystemExit(result.returncode)
