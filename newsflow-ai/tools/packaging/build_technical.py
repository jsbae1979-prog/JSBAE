"""Build an internal synthetic-only onedir bundle; does not install or launch."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    if os.name!="nt" or sys.version_info[:3]!=(3,14,7):
        raise SystemExit("Windows Python 3.14.7 required")
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--media-dir",type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();media=args.media_dir.resolve()
    project=Path(__file__).resolve().parents[2]
    if output.exists() or output.is_relative_to(project) or project.is_relative_to(output):
        raise SystemExit("A new, separate technical build directory is required")
    import PyInstaller
    if PyInstaller.__version__!="6.22.3":raise SystemExit("Pin PyInstaller 6.22.3 in a separate build venv")
    binaries={}
    for name in ("ffmpeg.exe","ffprobe.exe"):
        binary=media/name
        if not binary.is_file() or binary.is_symlink():raise SystemExit("Actual trusted FFmpeg binaries required")
        binaries[name]=hashlib.sha256(binary.read_bytes()).hexdigest()
    output.mkdir()
    for name in ("home","temp","home/Local","home/Roaming"):(output/name).mkdir(parents=True,exist_ok=True)
    manifest=output/"technical-media.json";manifest.write_text(json.dumps(binaries))
    env={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","COMSPEC","PATHEXT","PROCESSOR_ARCHITECTURE","NUMBER_OF_PROCESSORS","OS"}}
    env.update(PATH=str(Path(sys.executable).parent)+os.pathsep+str(Path(env["SYSTEMROOT"])/"System32"),
               USERPROFILE=str(output/"home"),HOME=str(output/"home"),LOCALAPPDATA=str(output/"home/Local"),
               APPDATA=str(output/"home/Roaming"),TEMP=str(output/"temp"),TMP=str(output/"temp"),
               NEWSFLOW_BUILD_MEDIA=str(media),NEWSFLOW_BUILD_MANIFEST=str(manifest))
    with (output/"build.log").open("wb") as log:
        result=subprocess.run([sys.executable,"-I","-B","-m","PyInstaller","--noconfirm",
            "--workpath",str(output/"work"),"--distpath",str(output/"dist"),
            str(Path(__file__).with_name("newsflow-technical.spec"))],
            cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT,check=False)
    exe=output/"dist/NewsFlowAI-Technical/NewsFlowAI-Technical.exe"
    summary={"exit":result.returncode,"Python":sys.version.split()[0],"tool":"PyInstaller6.22.3",
             "exe_exists":exe.is_file(),"public_distribution":False,"production_profile":False}
    if exe.is_file():summary["exe_sha256"]=hashlib.sha256(exe.read_bytes()).hexdigest()
    (output/"build-safe.json").write_text(json.dumps(summary,indent=2))
    raise SystemExit(result.returncode)
if __name__=="__main__":main()
