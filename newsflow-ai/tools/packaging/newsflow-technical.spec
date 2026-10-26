# Internal one-directory technical bundle; not an installer or public release.
import os, json, hashlib
from pathlib import Path
p=Path(SPECPATH).parents[1]
src=p/"src"
media=Path(os.environ["NEWSFLOW_BUILD_MEDIA"]).resolve()
datas=[]
for f in (src/"newsflow").rglob("*"):
    if f.is_file() and "__pycache__" not in f.parts:
        rel=f.relative_to(src)
        if f.suffix!=".py" or "migrations" in rel.parts:
            datas.append((str(f),str(rel.parent)))
hidden=[]
for f in (src/"newsflow").rglob("*.py"):
    rel=f.relative_to(src).with_suffix("")
    if "migrations" in rel.parts:continue
    parts=list(rel.parts)
    if parts[-1]=="__init__":parts.pop()
    hidden.append(".".join(parts))
hidden += ["uvicorn.protocols.http.h11_impl","uvicorn.protocols.websockets.websockets_impl",
           "uvicorn.lifespan.on","uvicorn.loops.asyncio","sqlalchemy.dialects.sqlite",
           "PIL.PngImagePlugin","PIL.JpegImagePlugin","PIL.WebPImagePlugin","tzdata","win32crypt"]
binaries=[(str(media/n),"media") for n in ("ffmpeg.exe","ffprobe.exe")]
manifest=Path(os.environ["NEWSFLOW_BUILD_MANIFEST"])
datas.append((str(manifest),"."))
a=Analysis([str(p/"tools/packaging/technical_entry.py")],
    pathex=[str(src),str(p/"tools/packaging")],binaries=binaries,datas=datas,
    hiddenimports=sorted(set(hidden)),hookspath=[],runtime_hooks=[],
    excludes=["playwright","pytest","ruff","tkinter"],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name="NewsFlowAI-Technical",
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name="NewsFlowAI-Technical")
