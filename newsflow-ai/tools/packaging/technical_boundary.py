"""Build-only boundary. Not imported by the product or shipped as a release policy."""
from pathlib import Path
import ctypes, hashlib, ipaddress, json, os, socket, sys

def install():
    if not getattr(sys, "frozen", False) or sys.version_info[:3] != (3,14,7):
        raise SystemExit("Frozen Windows Python 3.14.7 required")
    if len(sys.argv)!=3 or sys.argv[1] not in ("probe","serve"):
        raise SystemExit("Internal technical build requires explicit synthetic profile")
    root=Path(sys.argv[2]).resolve()
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise SystemExit("Invalid synthetic root")
    marker=root/"synthetic-only.json"
    if json.loads(marker.read_text())!={"kind":"NewsFlow-Step15A-SYNTHETIC","port":18765}:
        raise SystemExit("Synthetic marker required")
    bundle=Path(sys._MEIPASS).resolve()
    if root.is_relative_to(bundle) or bundle.is_relative_to(root):
        raise SystemExit("Separate output root required")
    for key in list(os.environ):
        if any(x in key.upper() for x in ("API_KEY","TOKEN","SECRET","PASSWORD","HF_KEY","OAUTH")):
            raise SystemExit("Credential-like environment refused")
    os.environ.update(NEWSFLOW_DATA_DIR=str(root/"AppData/Local/NewsFlowAI"),
        NEWSFLOW_PORT="18765",NEWSFLOW_HOST="127.0.0.1",
        LOCALAPPDATA=str(root/"AppData/Local"),APPDATA=str(root/"AppData/Roaming"),
        USERPROFILE=str(root/"home"),HOME=str(root/"home"),TEMP=str(root/"temp"),TMP=str(root/"temp"),
        NEWSFLOW_FFMPEG=str(bundle/"media/ffmpeg.exe"),NEWSFLOW_FFPROBE=str(bundle/"media/ffprobe.exe"),
        NEWSFLOW_FONT_PATH=str(bundle/"newsflow/character/assets/NotoSansKR.ttf"))
    for name in ("temp","home","AppData/Local","AppData/Roaming"):(root/name).mkdir(parents=True,exist_ok=True)
    os.chdir(root)
    windows=Path(os.environ["SystemRoot"]).resolve()
    allowed_read=(root,bundle,windows)
    archive=Path(sys.executable).resolve()
    shell=ctypes.WinDLL("shell32",use_last_error=True)
    parse=shell.CommandLineToArgvW;parse.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];parse.restype=ctypes.POINTER(ctypes.c_wchar_p)
    free=ctypes.WinDLL("kernel32").LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
    def split_args(value):
        if isinstance(value,list):return value
        if not isinstance(value,str):deny("process arguments")
        count=ctypes.c_int();items=parse(value,ctypes.byref(count))
        if not items:deny("process parse")
        try:return [items[n] for n in range(count.value)]
        finally:free(items)
    binaries={str((bundle/"media"/n).resolve()).lower():hashlib.sha256((bundle/"media"/n).read_bytes()).hexdigest() for n in ("ffmpeg.exe","ffprobe.exe")}
    manifest=json.loads((bundle/"technical-media.json").read_text())
    assert {Path(k).name:v for k,v in binaries.items()}==manifest
    import technical_media
    technical_media.configure(root,binaries)
    events=[]
    def under(path,roots):
        if isinstance(path,int):return True
        if path is None:return False
        q=Path(os.fsdecode(path)).resolve()
        return any(q.is_relative_to(a) for a in roots)
    def deny(reason):
        events.append(reason)
        (root/"boundary-denials-safe.json").write_text(json.dumps(events))
        raise PermissionError("Technical boundary: "+reason)
    def audit(event,args):
        if event=="open":
            path,mode,flags=args
            if isinstance(path,str) and path.lower()==os.devnull.lower():return
            write=bool((flags or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)) or isinstance(mode,str) and any(x in mode for x in "wax+")
            if not under(path,(root,) if write else allowed_read) and not (not write and not isinstance(path,int) and Path(path).resolve()==archive):deny("file access")
        elif event in ("os.remove","os.mkdir","os.rmdir","os.chmod","os.utime","os.truncate"):
            if not under(args[0],(root,)):deny("filesystem write")
        elif event in ("os.rename","os.link","os.symlink"):
            if not all(under(p,(root,)) for p in args[:2]):deny("filesystem move/link")
        elif event=="sqlite3.connect":
            path=str(args[0])
            if path!=":memory:" and not under(path,(root,)):deny("database")
        elif event=="socket.getaddrinfo":
            if args[0] not in ("127.0.0.1","localhost") or args[1]==8765:deny("external DNS")
        elif event in ("socket.connect","socket.bind"):
            address=args[1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1") or address[1]==8765:
                deny("external socket")
        elif event=="subprocess.Popen":
            technical_media.validate_process(*args)
        elif event in ("os.system","os.exec","os.spawn","ctypes.dlsym/handle"):
            deny("unsupported execution")
    sys.addaudithook(audit)
    (root/"runtime-safe.json").write_text(json.dumps({"Python":sys.version.split()[0],"frozen":True,
        "python_on_PATH":False,"bundled_runtime":True,"production_profile_used":False,
        "external_network_policy":"loopback only excluding operating port; no supplier transport","normal_vs_forced_exit_separate":True},indent=2))
    return root,bundle
