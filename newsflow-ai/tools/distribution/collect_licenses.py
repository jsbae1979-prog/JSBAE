"""Copy installed license notices for modules in an inventoried private payload.

Metadata collection is NOT a declaration of complete corresponding source or
commercial redistribution clearance. No package/app module is imported.
"""
import argparse,hashlib,importlib.metadata as md,json,re,shutil
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--exe',type=Path,required=True);ap.add_argument('--frontend',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise SystemExit('New license output required')
    a.output.mkdir(parents=True)
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(a.exe));modules=archive.open_embedded_archive('PYZ.pyz').toc
    mapping=md.packages_distributions()
    names=sorted({n for mod in modules for n in mapping.get(mod.split('.')[0],[])})
    rows=[]
    for name in names:
        d=md.distribution(name);slug=re.sub('[^a-zA-Z0-9_.-]','_',name)
        docs=[]
        for f in d.files or []:
            if not any(x in f.name.upper() for x in ('LICENSE','COPYING','NOTICE','OFL')):continue
            source=Path(d.locate_file(f))
            if not source.is_file() or source.stat().st_size>250000:continue
            target=a.output/'python'/slug/str(f).replace('..','_')
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            docs.append({'path':str(target.relative_to(a.output)).replace('\\','/'),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        rows.append({'name':name,'version':d.version,'license_expression':d.metadata.get('License-Expression'),'license_metadata':str(d.metadata.get('License',''))[:400],'notices':docs,'complete_source_verified':False})
    js=[]
    for package in ['react','react-dom','lucide-react','scheduler']:
        direct=a.frontend/'node_modules'/package
        candidates=[direct] if (direct/'package.json').is_file() else list((a.frontend/'node_modules/.pnpm').glob(package+'@*/node_modules/'+package))
        if not candidates:js.append({'name':package,'found':False});continue
        root=candidates[0];data=json.loads((root/'package.json').read_text(encoding='utf8'));docs=[]
        for f in root.iterdir():
            if f.is_file() and any(x in f.name.upper() for x in ('LICENSE','COPYING','NOTICE')):
                target=a.output/'javascript'/package/f.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target);docs.append(str(target.relative_to(a.output)).replace('\\','/'))
        js.append({'name':package,'version':data.get('version'),'license_metadata':data.get('license'),'notices':docs})
    result={'status':'INCOMPLETE-NOT-RELEASE-CLEARANCE','python_components':rows,'browser_runtime_components':js,'node_runtime_shipped':False,'ffmpeg_complete_corresponding_source':False,'sample_rights_verified':False}
    (a.output/'THIRD_PARTY_INVENTORY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (a.output/'NOTICE.txt').write_text('NewsFlow AI private distribution preparation.\nLicense texts are copied unmodified from installed distributions.\nFFmpeg GPL corresponding-source/build materials and sample redistribution rights remain unresolved.\nThis collection does NOT authorize public release.\n',encoding='utf8')
    print(json.dumps({'python_components':len(rows),'python_missing_notice':[r['name'] for r in rows if not r['notices']],'browser_components':js,'notice_files':sum(len(r['notices']) for r in rows)}))
if __name__=='__main__':main()
