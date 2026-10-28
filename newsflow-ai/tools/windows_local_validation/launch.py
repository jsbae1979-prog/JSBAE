"""Launch exactly one owned local validation child with a new synthetic profile."""
import argparse,json,os
from pathlib import Path
import subprocess,sys,time

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',required=True);parser.add_argument('--diagnostic',action='store_true');args=parser.parse_args()
    if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or sys.getwindowsversion().build<22000 or sys.getwindowsversion().product_type!=1:raise SystemExit('Windows11 workstation Python3.14.7 required')
    root=Path(args.workspace).resolve()
    # No overwrite/reuse, no traversal or reparse parent, no operating data.
    if root.exists() or not root.parent.is_dir() or any(p.is_symlink() or p.is_junction() for p in (root.parent,*root.parent.parents)):raise SystemExit('Fresh ordinary synthetic directory required')
    root.mkdir();(root/'owned-test-profile.json').write_text(json.dumps({'version':1,'synthetic':True,'source':'local-validation-runner'}),encoding='utf8')
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','PATHEXT'}}
    for name in ('Roaming','Local','Profile','Temp'):(root/name).mkdir()
    env.update({'APPDATA':str(root/'Roaming'),'LOCALAPPDATA':str(root/'Local'),'USERPROFILE':str(root/'Profile'),'HOME':str(root/'Profile'),'TEMP':str(root/'Temp'),'TMP':str(root/'Temp'),'PATH':str(Path(sys.executable).parent),'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','NEWSFLOW_DATA_DIR':str(root/'unused-default')})
    command=[sys.executable,'-B',str(Path(__file__).with_name('runner.py')),'--workspace',str(root)]
    if args.diagnostic:command.append('--diagnostic')
    log=(root/'process.log').open('w',encoding='utf8')
    child=subprocess.Popen(command,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    (root/'owned-process.json').write_text(json.dumps({'pid':child.pid,'python':sys.executable,'port':18765}),encoding='utf8')
    print('Owned validation profile: '+str(root),flush=True)
    try:
        while child.poll() is None:
            if (root/'ready.json').exists():print('Ready: http://127.0.0.1:18765/studio/dashboard',flush=True);break
            time.sleep(.2)
        code=child.wait()
        print('Owned child exited: '+str(code),flush=True)
    except KeyboardInterrupt:
        (root/'STOP').touch()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Exceptional owned-child cleanup, never reported as normal shutdown.
            (root/'forced-cleanup.json').write_text('{"forced":true}',encoding='utf8');child.kill();child.wait()
    finally:log.close()
if __name__=='__main__':main()
