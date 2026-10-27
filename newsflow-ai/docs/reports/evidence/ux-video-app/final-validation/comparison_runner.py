import json, os, subprocess, sys, hashlib
from pathlib import Path
from datetime import datetime, timezone
root = Path(sys.argv[1]).resolve()
label = sys.argv[2]
output = Path('/tmp/newsflow-final-comparison')
env = {k:v for k,v in os.environ.items() if not (k.startswith('NEWSFLOW_') or k in {'OPENAI_API_KEY','ANTHROPIC_API_KEY','PYTEST_ADDOPTS'})}
env['NEWSFLOW_TEST_BROWSER_EXECUTABLE'] = '/usr/bin/chromium'
env['PYTHONPATH'] = str(output/'harness') + os.pathsep + str(root/'src')
command = [sys.executable, '-m', 'pytest', '-q', '-rs', '-p', 'cloud_validation_browser', '--junitxml=result.xml']
meta = {'label':label, 'cwd':str(root),'command':command, 'python':sys.version,
        'started_utc':datetime.now(timezone.utc).isoformat(),
        'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd='/workspace/JSBAE',text=True).strip() if label=='final' else '590ffd447eebf76b9429c22a3354dbfa239dec16',
        'browser':'/usr/bin/chromium','browser_plugin_sha256':hashlib.sha256((output/'harness/cloud_validation_browser.py').read_bytes()).hexdigest(),
        'manifest_sha256':hashlib.sha256((root/'pyproject.toml').read_bytes()).hexdigest(),
        'dependencies_sha256':hashlib.sha256((output/'dependencies.json').read_bytes()).hexdigest(),
        'live_environment_removed':True}
with (output/f'{label}.log').open('w') as log:
    result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
meta.update(exit_code=result.returncode, ended_utc=datetime.now(timezone.utc).isoformat())
(output/f'{label}-run.json').write_text(json.dumps(meta,indent=2))
(root/'result.xml').replace(output/f'{label}.xml')
print(json.dumps(meta,indent=2))
sys.exit(result.returncode)
