"""Compare identical bounded suites on native Windows, using synthetic fixtures only."""
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
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'fbadd460d3005fca5c5aa613a78fd7c926c87be6'
PRODUCT = 'f6aedc5db10ac7df9e6ce7b2b7f8aab7f5c6bdac'
TARGETS = [
    'tests/test_creator_ui.py', 'tests/test_studio_design_system.py',
    'tests/test_studio_structure.py', 'tests/test_studio_structure_browser.py',
    'tests/test_workspace_access.py', 'tests/test_workspace_access_browser.py',
    'tests/test_settings_simplification.py', 'tests/test_settings_streamlined_browser.py',
    'tests/test_publish_save_browser.py', 'tests/test_studio_dashboard_polish.py',
    'tests/test_unified_publishing_gui.py', 'tests/test_image_posts.py',
    'tests/test_image_selection.py',
    'tests/test_production_dpapi.py::test_real_windows_production_dpapi_restart_tampering_account_binding',
]


def results(path: Path) -> dict:
    if not path.exists():
        return {'counts': {}, 'cases': {}, 'collection_failed': True}
    cases = {}
    counts = dict.fromkeys(('passed', 'failed', 'error', 'skipped'), 0)
    for case in ET.parse(path).iter('testcase'):
        status = next((x for x in ('failure', 'error', 'skipped') if case.find(x) is not None), 'passed')
        status = 'failed' if status == 'failure' else status
        key = case.get('classname', '') + '::' + case.get('name', '')
        cases[key] = status
        counts[status] += 1
    return {'counts': counts, 'cases': cases}


def run(tree: Path, targets: list[str], label: str, output: Path) -> dict:
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(map(str, [tree/'src', tree/'tests', ROOT/'tools']))
    env['NEWSFLOW_STUDIO_POLISH_EVIDENCE'] = str(output/label/'polish')
    env['NEWSFLOW_SETTINGS_EVIDENCE'] = str(output/label/'settings')
    command = [sys.executable, '-m', 'pytest', '-q', '-rs', '-p', 'windows_final_guard',
               *targets, f'--junitxml={output/label}.xml']
    with (output/f'{label}.txt').open('w', encoding='utf-8') as log:
        outcome = subprocess.run(command, cwd=tree, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 timeout=900, check=False)
    summary = results(output/f'{label}.xml')
    summary.update(exit_code=outcome.returncode, command=command)
    print(label, summary['counts'], 'exit', outcome.returncode, flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--historical-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Native Windows required')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # The CI change must not silently alter the approved product or its existing tests.
    changed = subprocess.check_output(['git', 'diff', '--name-only', PRODUCT, 'HEAD', '--',
        'newsflow-ai/src', 'newsflow-ai/run.bat', 'newsflow-ai/pyproject.toml', 'newsflow-ai/tests'],
        cwd=ROOT.parent, text=True)
    assert not changed, changed
    historical = json.loads((ROOT/'docs/reports/evidence/regression-57-resolution/selection.json').read_text())['matched']
    assert len(historical) == 57
    # Four historical parameter IDs changed before this UI work. Run the full
    # corresponding functions, preserving all current parameter assertions.
    renamed = ('tests/test_gui.py::test_render',
               'tests/test_realcontent.py::test_external_ai_failures_map_to_actionable_codes')
    mapping = {node: node.split('[', 1)[0] for node in historical if node.startswith(renamed)}
    historical_targets = list(dict.fromkeys(mapping.get(node, node) for node in historical))
    summary = {'sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'product_sha': PRODUCT, 'baseline_sha': BASE, 'python': sys.version,
        'windows': platform.platform(), 'product_and_existing_tests_unchanged': True,
        'external_services': 'blocked by test guard; no real credentials',
        'historical_parameter_mapping': mapping, 'historical_ids': historical, 'groups': {}}
    archive = subprocess.check_output(['git', 'archive', BASE, 'newsflow-ai/src', 'newsflow-ai/tests',
                                      'newsflow-ai/pyproject.toml'], cwd=ROOT.parent)
    with tempfile.TemporaryDirectory(prefix='newsflow-final-baseline-') as temp:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(temp, filter='data')
        baseline = Path(temp)/'newsflow-ai'
        groups = [('historical57', historical_targets)] if args.historical_only else [
            ('scoped', TARGETS), ('historical57', historical_targets)]
        for group, targets in groups:
            old = run(baseline, targets, f'{group}-baseline', out)
            new = run(ROOT, targets, f'{group}-final', out)
            fail = lambda data: {key for key, value in data['cases'].items() if value in ('failed', 'error')}
            summary['groups'][group] = {'baseline': old, 'final': new,
                'new_failure_ids': sorted(fail(new)-fail(old)), 'common_failure_ids': sorted(fail(new)&fail(old)),
                'missing_final_cases': sorted(old['cases'].keys()-new['cases'].keys())}
            (out/'comparison.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(g['final']['exit_code'] != 0 for g in summary['groups'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
