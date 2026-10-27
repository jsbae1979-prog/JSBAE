"""Native Windows before/after fixture comparison; product code remains unchanged."""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from ci_final_windows_ui import BASE, PRODUCT, results

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = '446236f639640260d358eabec73f15fd67998155'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'win32', 'Native Windows required'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    assert not subprocess.check_output(['git','diff','--name-only', PRODUCT,'HEAD','--',
        'newsflow-ai/src','newsflow-ai/tests','newsflow-ai/run.bat','newsflow-ai/pyproject.toml'],cwd=ROOT.parent)
    summary = {'sha': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'product_sha':PRODUCT,'baseline_sha':BASE,'old_fixture_sha':PREVIOUS,
        'python':sys.version,'platform':platform.platform(),'cases':{},'real_external_calls':0}
    old = subprocess.check_output(['git','show',PREVIOUS+':newsflow-ai/tools/test_windows_final_flow.py'],cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='newsflow-flow-compare-') as tmp:
        temp = Path(tmp)
        for label, sha in [('baseline', BASE), ('product', PRODUCT)]:
            archive = subprocess.check_output(['git','archive',sha,'newsflow-ai/src',
                'newsflow-ai/tests','newsflow-ai/pyproject.toml'],cwd=ROOT.parent)
            tree = temp/label
            tree.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(tree,filter='data')
            project = tree/'newsflow-ai'
            validation = project/'validation_tools'
            validation.mkdir()
            (validation/'test_old_flow.py').write_bytes(old)
            (validation/'test_fixed_flow.py').write_bytes((ROOT/'tools/test_windows_final_flow.py').read_bytes())
            for variant in ('old','fixed'):
                name = label+'-'+variant
                evidence = out/name
                evidence.mkdir()
                env = os.environ.copy()
                env['PYTHONPATH'] = os.pathsep.join(map(str,[project/'src',project/'tests',ROOT/'tools']))
                env['NEWSFLOW_VALIDATION_OUTPUT'] = str(evidence)
                env['NEWSFLOW_DATA_DIR'] = str(temp/(name+'-unused-profile'))
                command = [sys.executable,'-m','pytest','-q','-rs','-p','windows_final_guard',
                    '-p','flow_failure_diagnostics',str(validation/f'test_{variant}_flow.py'),
                    '--junitxml='+str(evidence/'tests.xml')]
                with (evidence/'pytest.txt').open('w',encoding='utf-8') as log:
                    run = subprocess.run(command,cwd=project,env=env,stdout=log,stderr=subprocess.STDOUT,
                                         timeout=900,check=False)
                result = results(evidence/'tests.xml')
                result.update(exit_code=run.returncode,command=command)
                summary['cases'][name] = result
                print(name,result['counts'],'exit',run.returncode,flush=True)
                (out/'comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        for label in ('baseline','product'):
            old_result = summary['cases'][label+'-old']
            assert old_result['counts'] == {'passed':0,'failed':2,'error':0,'skipped':0}, old_result
            for mode in ('openai','claude_api'):
                diagnostic = json.loads((out/(label+'-old')/f'diagnostic-{mode}.json').read_text(encoding='utf-8'))
                assert diagnostic['jobs'][0]['error_code'] == 'script_auto_review'
                assert diagnostic['fake_calls'] == ['search','analysis','script']
                codes = {n['code'] for n in diagnostic['drafts'][0]['notes'] if n['level']=='warning'}
                assert {'explainer_spoken_hook','explainer_spoken_closing',
                        'explainer_synthetic_context','narration_sentence_limit'} <= codes
            fixed = summary['cases'][label+'-fixed']
            assert fixed['exit_code'] == 0 and fixed['counts'] == {'passed':2,'failed':0,'error':0,'skipped':0}, fixed
    summary['conclusion'] = 'PASS: old fixture fails closed on both SHAs; corrected fixture completes on both'
    (out/'comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
