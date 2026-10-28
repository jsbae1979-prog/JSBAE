"""Inventory archive and stage/uninstall private bytes; never execute the frozen app."""
import argparse,hashlib,importlib.metadata,json,os,sqlite3,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from package_contract import LifecycleModel,FORBIDDEN_MODULES,canonical,verify

def main():
    if os.name!='nt' or sys.version_info[:3]!=(3,14,7):raise SystemExit('Windows Python3.14.7 required')
    ap=argparse.ArgumentParser();ap.add_argument('--build',type=Path,required=True);ap.add_argument('--workspace',type=Path,required=True);a=ap.parse_args()
    build=a.build.resolve();work=a.workspace.resolve()
    if work.exists():raise SystemExit('New synthetic stage required')
    root=build/'dist/NewsFlowAI-Candidate';manifest=json.loads((build/'payload-manifest.json').read_text(encoding='utf8'))
    verify(root,manifest)
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(root/'NewsFlowAI-Candidate.exe'));modules=archive.open_embedded_archive('PYZ.pyz').toc
    forbidden=[n for n in modules if any(n==v or n.startswith(v+'.') for v in FORBIDDEN_MODULES)]
    if forbidden:raise SystemExit('Verification module in payload')
    samples=json.loads((root/'_internal/newsflow/assets/samples/manifest.json').read_text(encoding='utf8'))
    table={r['path']:r for r in manifest['files']}
    sample_rows=[{'id':s['id'],'type':s['type'],'width':s['width'],'height':s['height'],'packaged_sha_matches_manifest':table['_internal/newsflow/assets/samples/'+s['path']]['sha256']==s['sha256'],'rightsVerified':s.get('rightsVerified',False),'license':s['license'],'source':s['source']} for s in samples['assets']]
    if not all(r['packaged_sha_matches_manifest'] for r in sample_rows):raise SystemExit('Packaged sample mismatch')
    package=build/'NewsFlowAI-Private-Payload.zip'
    if package.exists():raise SystemExit('Do not overwrite private artifact')
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for r in manifest['files']:z.write(root/r['path'],'app/'+r['path'])
        z.writestr('payload-manifest.json',json.dumps(manifest,indent=2))
    package_hash=hashlib.sha256(package.read_bytes()).hexdigest()
    (build/'NewsFlowAI-Private-Payload.sha256').write_text(package_hash+'  '+package.name+'\n',encoding='ascii')
    work.mkdir();model=LifecycleModel(work/'owned-profile')
    db=sqlite3.connect(model.data/'newsflow.db');db.execute('create table synthetic_state(k text,v text)');db.execute('insert into synthetic_state values (?,?)',('sample-hidden','true'));db.commit();db.close()
    (model.data/'opaque-key.dpapi').write_bytes(b'SYNTHETIC-PRESERVATION-SENTINEL-NOT-REAL-DPAPI')
    (model.data/'settings.json').write_text('{"synthetic":true}')
    (model.data/'user-media.bin').write_bytes(b'SYNTHETIC-USER-MEDIA')
    fingerprint=lambda:{str(p.relative_to(model.data)):hashlib.sha256(p.read_bytes()).hexdigest() for p in model.data.rglob('*') if p.is_file()}
    before=fingerprint();expected=hashlib.sha256(canonical(manifest)).hexdigest()
    model.install(root,manifest,expected);first=model.current();model.uninstall({manifest['version']:manifest});retained=before==fingerprint()
    model.install(root,manifest,expected);model.install(root,manifest,expected);reinstalled=model.current();stable=before==fingerprint()
    components=[]
    for name in ['pyinstaller','fastapi','uvicorn','jinja2','sqlalchemy','alembic','feedparser','defusedxml','python-multipart','filelock','pydantic','Pillow','pywin32','tzdata','supertonic','onnxruntime']:
        try:
            d=importlib.metadata.distribution(name);components.append({'name':name,'version':d.version,'license_expression':d.metadata.get('License-Expression'),'license_metadata':str(d.metadata.get('License',''))[:300]})
        except importlib.metadata.PackageNotFoundError:components.append({'name':name,'installed':False})
    evidence={'scope':'Private payload ZIP and filesystem staging MODEL, not actual Windows Setup or frozen app launch','Python':sys.version.split()[0],'archive_sha256':package_hash,'archive_bytes':package.stat().st_size,'payload_files':len(manifest['files']),'verification_modules':forbidden,'packaged_samples':sample_rows,'new_stage':first is not None,'uninstall_user_data_preserved':retained,'reinstall_user_data_preserved':stable,'repeat_stage_no_duplicate':first==reinstalled,'app_executed':False,'installer_compiled':False,'cross_windows_user_test':False,'public_distribution':False,'components_metadata_only':components,'license_files':[r['path'] for r in manifest['files'] if any(s in Path(r['path']).name.upper() for s in ('LICENSE','COPYING','OFL','NOTICE'))]}
    (build/'payload-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in evidence.items() if k not in {'packaged_samples','components_metadata_only','license_files'}},ensure_ascii=False))
    if not(retained and stable and first==reinstalled):raise SystemExit('Retention model failed')
if __name__=='__main__':main()
