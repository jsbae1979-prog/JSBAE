"""Build/inventory a private candidate only. No installer/application execution."""
import argparse,hashlib,importlib.metadata,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from package_contract import inventory,FORBIDDEN_MODULES

def main():
    if os.name!='nt' or sys.version_info[:3]!=(3,14,7):raise SystemExit('Windows Python3.14.7 required')
    if importlib.metadata.version('pyinstaller')!='6.22.3':raise SystemExit('Reuse reviewed PyInstaller6.22.3')
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--media-dir',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve();media=args.media_dir.resolve();project=Path(__file__).resolve().parents[2]
    if output.exists() or output.is_relative_to(project) or project.is_relative_to(output):raise SystemExit('New separate output required')
    pins={'ffmpeg.exe':'3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec','ffprobe.exe':'f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52'}
    if any(not (media/n).is_file() or hashlib.sha256((media/n).read_bytes()).hexdigest()!=h for n,h in pins.items()):raise SystemExit('Trusted media digest mismatch')
    output.mkdir()
    for n in ('home/Local','home/Roaming','temp','cache'):(output/n).mkdir(parents=True)
    media_manifest=output/'media-integrity.json';media_manifest.write_text(json.dumps(pins),encoding='utf8')
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS'}}
    env.update(PATH=str(Path(sys.executable).parent)+os.pathsep+str(Path(env['SYSTEMROOT'])/'System32'),USERPROFILE=str(output/'home'),HOME=str(output/'home'),LOCALAPPDATA=str(output/'home/Local'),APPDATA=str(output/'home/Roaming'),TEMP=str(output/'temp'),TMP=str(output/'temp'),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PYINSTALLER_CONFIG_DIR=str(output/'cache'),NEWSFLOW_BUILD_MEDIA=str(media),NEWSFLOW_BUILD_MANIFEST=str(media_manifest))
    with (output/'build.log').open('wb') as log:
        result=subprocess.run([sys.executable,'-I','-B','-m','PyInstaller','--noconfirm','--workpath',str(output/'work'),'--distpath',str(output/'dist'),str(Path(__file__).with_name('newsflow-candidate.spec'))],cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT)
    summary={'Python':sys.version.split()[0],'PyInstaller':'6.22.3','exit':result.returncode,'app_executed':False,'installer_compiled':False,'public_distribution':False}
    if result.returncode==0:
        root=output/'dist/NewsFlowAI-Candidate';exe=root/'NewsFlowAI-Candidate.exe'
        files=inventory(root)
        from PyInstaller.archive.readers import CArchiveReader
        archive=CArchiveReader(str(exe));modules=archive.open_embedded_archive('PYZ.pyz').toc
        forbidden=[n for n in modules if any(n==v or n.startswith(v+'.') for v in FORBIDDEN_MODULES)]
        if forbidden:raise SystemExit('Verification/test module in archive')
        samples=json.loads((root/'_internal/newsflow/assets/samples/manifest.json').read_text(encoding='utf8'))
        missing=[r['id'] for r in samples['assets'] if not (root/'_internal/newsflow/assets/samples'/r['path']).is_file()]
        package={'schemaVersion':1,'appId':'NewsFlowAI','version':'0.6.0b1-internal','internalOnly':True,'distributionAllowed':False,'sourceBase':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),'files':files}
        (output/'payload-manifest.json').write_text(json.dumps(package,indent=2),encoding='utf8')
        summary.update(exe_bytes=exe.stat().st_size,exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),file_count=len(files),payload_bytes=sum(r['bytes'] for r in files),sample_count=len(samples['assets']),sample_missing=missing,verification_modules=forbidden,python_runtime=(root/'_internal/python314.dll').is_file(),react=(root/'_internal/frontend/dist/index.html').is_file(),media_binaries=all((root/'_internal/media'/n).is_file() for n in pins),sample_rights_verified=all(r.get('rightsVerified') is True for r in samples['assets']))
    (output/'build-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary));raise SystemExit(result.returncode)
if __name__=='__main__':main()
