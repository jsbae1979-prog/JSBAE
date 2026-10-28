import argparse,hashlib,json,os,shutil,tarfile,urllib.request
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('workspace',type=Path);a=ap.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Windows':
        raise SystemExit('Disposable native Windows CI only')
    root=a.workspace.resolve();temp=Path(os.environ['RUNNER_TEMP']).resolve()
    if root.exists() or root==temp or not root.is_relative_to(temp):raise SystemExit('Fresh Runner TEMP workspace required')
    root.mkdir();here=Path(__file__).resolve().parent
    for n in ('sources','src','evidence','prefix','build'):(root/n).mkdir()
    manifest=json.loads((here/'sources.json').read_text(encoding='utf8'))
    for r in manifest['sources']:
        archive=root/'sources'/(r['name']+'.tar.gz')
        if r.get('bundled'):shutil.copyfile(here/'source-archives'/archive.name,archive)
        else:
            with urllib.request.urlopen(r['url'],timeout=90) as response,archive.open('xb') as out:
                shutil.copyfileobj(response,out)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=r['sha256']:raise ValueError('source digest: '+r['name'])
        r['archive_bytes']=archive.stat().st_size
        dest=root/'src'/r['name'];dest.mkdir()
        with tarfile.open(archive) as t:
            if sum(m.size for m in t.getmembers())>700*1024*1024:raise ValueError('source extraction bound')
            t.extractall(dest,filter='data')
        entries=list(dest.iterdir())
        r['source_dir']=str(entries[0] if len(entries)==1 and entries[0].is_dir() else dest)
    (root/'evidence/SOURCE_INPUTS.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print('Verified source archives:',len(manifest['sources']))

if __name__=='__main__':main()
