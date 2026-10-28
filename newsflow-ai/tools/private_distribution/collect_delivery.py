"""Create local corresponding-source sidecar; never uploads executable files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--media-root', required=True, type=Path)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--manual', required=True, type=Path)
    args = parser.parse_args()
    sidecar = args.build / 'candidates/corresponding-sources'
    if sidecar.exists():
        raise SystemExit('Preserve existing sidecar; fresh path required')
    sidecar.mkdir()
    sources = json.loads((args.media_root / 'evidence/SOURCE_INPUTS.json').read_text())
    rows = []
    for row in sources['sources']:
        name = row['name'] + '.tar.gz'
        path = args.media_root / 'sources' / name
        if digest(path) != row['sha256']:
            raise SystemExit('Source digest changed')
        shutil.copyfile(path, sidecar / name)
        rows.append({'file': name, 'sha256': row['sha256'], 'commit': row['commit'], 'license': row['license']})
    shutil.copytree(args.media_root / 'evidence', sidecar / 'build-evidence')
    shutil.copyfile(args.recipe, sidecar / 'build-local-media.sh')
    shutil.copytree(args.build / 'notices/source-licenses', sidecar / 'source-licenses')
    binding = {'scope': 'Local private verification candidate only', 'releaseReady': False,
               'sourcePatches': [], 'sourceArchives': rows,
               'recipeSha256': digest(sidecar / 'build-local-media.sh'),
               'binaryHashes': json.loads((args.build / 'PRIVATE_BUILD_SUMMARY.json').read_text())['media'],
               'sourceDelivery': 'Keep this sidecar with the corresponding binaries; not an expiring CI link.',
               'legalClearance': 'Not asserted. Runtime/system-library exceptions, source completeness and all asset rights remain release-review conditions.'}
    (sidecar / 'BINARY_SOURCE_BINDING.json').write_text(json.dumps(binding, indent=2))
    shutil.copyfile(args.manual, args.build / 'candidates/PRIVATE_INSTALL_UPDATE_GUIDE.md')
    binaries = {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in (args.build / 'candidates').glob('*.exe')}
    (args.build / 'candidates/SHA256SUMS.json').write_text(json.dumps(binaries, indent=2))
    (args.build / 'candidates/PRIVATE_CANDIDATE_ONLY.txt').write_text('UNSIGNED DEVELOPMENT VERIFICATION ONLY. DO NOT DELIVER TO USERS. rightsVerified:false. Real publisher certificate, asset rights, corresponding-source clearance and signed offline update verification are required. No public release or operating replacement is authorized.\n')
    print(json.dumps({'correspondingSources': len(rows), 'binaryFiles': list(binaries), 'publicUpload': False}))


if __name__ == '__main__':
    main()
