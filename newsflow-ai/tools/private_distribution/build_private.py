"""Local private candidates only. No upload, certificate bypass or app launch."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(args, cwd, env, log):
    with log.open('wb') as stream:
        code = subprocess.run([str(x) for x in args], cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT).returncode
    if code:
        raise RuntimeError('Build failed: ' + log.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--media-root', type=Path, required=True)
    ap.add_argument('--iscc', type=Path, required=True)
    ap.add_argument('--reuse-runtime', type=Path)
    args = ap.parse_args()
    if os.name != 'nt' or sys.version_info[:3] != (3, 14, 7) or importlib.metadata.version('pyinstaller') != '6.22.3':
        raise SystemExit('Reviewed Windows Python3.14.7 / PyInstaller6.22.3 required')
    here = Path(__file__).resolve().parent
    project = here.parents[1]
    sys.path.insert(0, str(project / 'src'))
    sys.path.insert(0, str(here.parent / 'distribution'))
    from package_contract import inventory
    from newsflow.distribution.offline import tree
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(project) or project.is_relative_to(output):
        raise SystemExit('New private separate output required')
    output.mkdir()
    for name in ('home/Local', 'home/Roaming', 'temp', 'cache', 'helpers', 'candidates', 'recipes'):
        (output / name).mkdir(parents=True)
    media_root = args.media_root.resolve()
    media = media_root / 'prefix/bin'
    evidence = media_root / 'evidence'
    pins = {name: hashlib.sha256((media / name).read_bytes()).hexdigest() for name in ('ffmpeg.exe', 'ffprobe.exe')}
    source_inputs = json.loads((evidence / 'SOURCE_INPUTS.json').read_text())
    expected = json.loads((here.parent / 'ffmpeg_source_candidate/sources.json').read_text())
    if [(r['name'], r['sha256']) for r in source_inputs['sources']] != [(r['name'], r['sha256']) for r in expected['sources']]:
        raise SystemExit('Pinned source provenance mismatch')
    version = subprocess.check_output([str(media / 'ffmpeg.exe'), '-version'], text=True)
    if '--disable-network' not in version or '--enable-gpl' not in version:
        raise SystemExit('Unexpected source-built media configuration')
    (output / 'media-integrity.json').write_text(json.dumps(pins))
    env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS'}}
    env.update(PATH=str(Path(sys.executable).parent) + os.pathsep + str(Path(env['SYSTEMROOT']) / 'System32'),
               USERPROFILE=str(output / 'home'), HOME=str(output / 'home'), LOCALAPPDATA=str(output / 'home/Local'),
               APPDATA=str(output / 'home/Roaming'), TEMP=str(output / 'temp'), TMP=str(output / 'temp'),
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYINSTALLER_CONFIG_DIR=str(output / 'cache'),
               NEWSFLOW_BUILD_MEDIA=str(media), NEWSFLOW_BUILD_MANIFEST=str(output / 'media-integrity.json'))
    samples = project / 'docs/artifacts/sample-replacement-candidates-v2-20261028'
    catalog = json.loads((samples / 'manifest.json').read_text(encoding='utf8'))
    if len(catalog['assets']) != 12 or any(r.get('rightsVerified') is not False for r in catalog['assets']):
        raise SystemExit('Private unverified candidate samples only')
    recipe = (here.parent / 'distribution/newsflow-candidate.spec').read_text()
    recipe = recipe.replace("p=Path(SPECPATH).parents[1];src=p/'src'", 'p=Path(' + repr(str(project)) + ");src=p/'src'")
    recipe = recipe.replace("if f.suffix!='.py' or 'migrations' in rel.parts:", "if (f.suffix!='.py' or 'migrations' in rel.parts) and rel.parts[:2] != ('assets','samples'):")
    insertion = ["samples=Path(" + repr(str(samples)) + ")"]
    for row in catalog['assets']:
        insertion.append('datas.append((' + repr(str(samples / row['path'])) + ',' + repr(str(Path('newsflow/assets/samples') / Path(row['path']).parent)) + '))')
        if row.get('poster'):
            poster = row['poster']
            insertion.append('datas.append((' + repr(str(samples / poster['path'])) + ',' + repr(str(Path('newsflow/assets/samples') / Path(poster['path']).parent)) + '))')
    insertion.append('datas.append((' + repr(str(samples / 'manifest.json')) + ",'newsflow/assets/samples'))")
    # Minimal candidate provenance/notices are offline and travel with the bytes.
    notices = output / 'notices'
    shutil.copytree(project / 'docs/reports/sample-ffmpeg-rights-20261028/candidate-source-licenses', notices / 'source-licenses')
    shutil.copytree(evidence, notices / 'ffmpeg-build-evidence', ignore=shutil.ignore_patterns('*.log', '*FUNCTIONAL*'))
    for name in ('PROVENANCE_MANIFEST.json', 'GENERATION_RECORDS.json', 'RIGHTS_BASIS.md'):
        shutil.copyfile(samples / name, notices / name)
    (notices / 'PRIVATE_CANDIDATE.txt').write_text('UNSIGNED PRIVATE VERIFICATION ONLY. Samples rightsVerified:false. No external delivery. GPL corresponding sources must accompany any future transfer. No public update server.\n')
    insertion.append('for f,rel in ordinary_tree(Path(' + repr(str(notices)) + ")):datas.append((str(f),str(Path('licenses/private-candidate')/Path(str(rel)).parent)))")
    recipe = recipe.replace('frontend=p/', '\n'.join(insertion) + '\nfrontend=p/', 1)
    # Spec resides beside package_contract so the unchanged inventory helpers load.
    recipe_path = output / 'recipes/private-app.spec'
    recipe_path.write_text(recipe, encoding='utf8')
    shutil.copyfile(here.parent / 'distribution/package_contract.py', recipe_path.parent / 'package_contract.py')
    base = output / 'app-dist/NewsFlowAI-Candidate'
    if args.reuse_runtime:
        # Reuse compiled Python/React only when the exact source/resource bytes
        # still match. Media and sample resources are selected again below.
        prior = args.reuse_runtime.resolve()
        saved = json.loads((prior / 'runtime-source-index.json').read_text())
        current = []
        from package_contract import ordinary_tree, verify
        for folder, label in [(project / 'src/newsflow', 'src'), (project / 'frontend/dist', 'frontend')]:
            for file, relative in ordinary_tree(folder, source=True):
                current.append({'path': label + '/' + str(relative), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
        current.append({'path': 'app_entry.py', 'sha256': hashlib.sha256((here.parent / 'distribution/app_entry.py').read_bytes()).hexdigest()})
        if saved != current:
            raise SystemExit('Prepared runtime source changed; rebuild required')
        old_bundle = prior / 'dist/NewsFlowAI-Candidate'
        verify(old_bundle, json.loads((prior / 'payload-manifest.json').read_text()))
        shutil.copytree(old_bundle, base)
        owned_samples = base / '_internal/newsflow/assets/samples'
        if not owned_samples.resolve().is_relative_to(output) or owned_samples.is_symlink() or owned_samples.is_junction():
            raise SystemExit('Owned cloned sample directory required')
        for file in sorted(owned_samples.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if file.is_file():
                file.unlink()
            else:
                file.rmdir()
        for row in catalog['assets']:
            target = owned_samples / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(samples / row['path'], target)
            if row.get('poster'):
                poster = row['poster']
                target = owned_samples / poster['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(samples / poster['path'], target)
        shutil.copyfile(samples / 'manifest.json', owned_samples / 'manifest.json')
        for name in pins:
            shutil.copyfile(media / name, base / '_internal/media' / name)
        shutil.copyfile(output / 'media-integrity.json', base / '_internal/media-integrity.json')
        shutil.copytree(notices, base / '_internal/licenses/private-candidate')
    else:
        run([sys.executable, '-I', '-B', '-m', 'PyInstaller', '--noconfirm', '--workpath', output / 'app-work', '--distpath', output / 'app-dist', recipe_path], output, env, output / 'app-build.log')
    inventory(base)
    from newsflow.samples.catalog import Samples
    loaded, warning = Samples(None, output / 'unused-data', None, root=base / '_internal/newsflow/assets/samples').catalog()
    if len(loaded) != 12 or warning:
        raise SystemExit('Packaged sample catalog/posters invalid')
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(base / 'NewsFlowAI-Candidate.exe'))
    modules = archive.open_embedded_archive('PYZ.pyz').toc
    from package_contract import FORBIDDEN_MODULES
    if any(n == v or n.startswith(v + '.') for n in modules for v in FORBIDDEN_MODULES):
        raise SystemExit('Test Guard in private product')
    manifests = {}
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip()
    for number, sequence in [('1.0.0', 1), ('1.1.0', 2)]:
        slot = output / ('payload-' + number)
        shutil.copytree(base, slot)
        (slot / '_internal/private-release.json').write_text(json.dumps({'version': number, 'source': source, 'internalOnly': True, 'distributionAllowed': False}))
        manifest = dict(appId='NewsFlowAI', channel='private-offline', version=number, sequence=sequence,
                        supportedFrom=['1.0.0'] if sequence == 2 else [], source=source,
                        rightsVerified=False, publisherSigned=False, files=tree(slot))
        file = output / ('release-' + number + '.json')
        file.write_text(json.dumps(manifest, indent=2))
        manifests[number] = manifest
    # A helper is frozen separately to keep the stable launcher independent of slots.
    # The two payloads share product source; only release metadata differ. Existing
    # genuine two-source-version recovery evidence remains a separate reused result.
    for mode, filename in [('launcher', 'NewsFlowAI'), ('update', 'NewsFlowAI_Update_v1.1.0')]:
        data = output / ('helper-' + mode)
        data.mkdir()
        (data / 'private-mode.json').write_text(json.dumps({'mode': mode, 'productSource': source}))
        shutil.copyfile(project / 'src/newsflow/distribution/publisher-trust.json', data / 'publisher-trust.json')
        command = [sys.executable, '-I', '-B', '-m', 'PyInstaller', '--noconfirm', '--onefile', '--name', filename,
                   '--paths', project / 'src', '--workpath', output / ('helper-work-' + mode),
                   '--specpath', output / 'recipes', '--distpath', output / 'helpers',
                   '--add-data', str(data / 'private-mode.json') + ';.',
                   '--add-data', str(data / 'publisher-trust.json') + ';.',
                   '--add-data', str(project / 'src/newsflow/distribution/verify_authenticode.ps1') + ';newsflow/distribution',
                   '--add-data', str(project / 'src/newsflow/db/migrations') + ';newsflow/db/migrations',
                   '--hidden-import', 'sqlalchemy.dialects.sqlite', '--hidden-import', 'win32security',
                   '--hidden-import', 'win32api', '--hidden-import', 'win32file', '--hidden-import', 'pywintypes',
                   '--exclude-module', 'pytest', '--exclude-module', 'playwright']
        if mode == 'update':
            command += ['--add-data', str(output / 'payload-1.1.0') + ';payload',
                        '--add-data', str(output / 'release-1.1.0.json') + ';.']
            # Embedded exact filename, not a dynamic external manifest.
            shutil.copyfile(output / 'release-1.1.0.json', data / 'release.json')
            command[-2:] = ['--add-data', str(data / 'release.json') + ';.']
        command += [here / 'private_entry.py']
        run(command, output, env, output / ('helper-' + mode + '.log'))
    run([args.iscc, '/Qp', '/DAppBundle=' + str(output / 'payload-1.0.0'),
         '/DLauncher=' + str(output / 'helpers/NewsFlowAI.exe'), '/DReleaseManifest=' + str(output / 'release-1.0.0.json'),
         '/DPrivateOutput=' + str(output / 'candidates'), here / 'private-installer.iss'], output, env, output / 'installer-build.log')
    shutil.copyfile(output / 'helpers/NewsFlowAI_Update_v1.1.0.exe', output / 'candidates/NewsFlowAI_Update_v1.1.0.exe')
    summary = dict(scope='Unsigned internal verification only; no external delivery', source=source,
                   sameProductCodeDifferentReleaseMetadata=True, publisherSigned=False, releaseReady=False,
                   sampleCount=12, sampleRightsVerified=False, media=pins, testGuardsIncluded=False,
                   files={p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                          for p in (output / 'candidates').glob('*.exe')})
    (output / 'PRIVATE_BUILD_SUMMARY.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
