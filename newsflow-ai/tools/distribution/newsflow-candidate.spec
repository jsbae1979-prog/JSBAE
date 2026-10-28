# Private onedir candidate; reuses the existing PyInstaller layout, never launches.
import os,sys
from pathlib import Path
sys.path.insert(0,SPECPATH)
from package_contract import relative_name,ordinary_tree

p=Path(SPECPATH).parents[1];src=p/'src'
media=Path(os.environ['NEWSFLOW_BUILD_MEDIA']);manifest=Path(os.environ['NEWSFLOW_BUILD_MANIFEST'])
datas=[]
for f,rel in ordinary_tree(src/'newsflow',source=True):
    if f.suffix!='.py' or 'migrations' in rel.parts:
        datas.append((str(f),str(Path('newsflow')/Path(str(rel)).parent)))
frontend=p/'frontend/dist'
if not (frontend/'index.html').is_file():raise SystemExit('Reviewed React build required')
for f,rel in ordinary_tree(frontend):datas.append((str(f),str(Path('frontend/dist')/Path(str(rel)).parent)))
datas.append((str(manifest),'.'))
license_file=Path(sys.base_prefix)/'LICENSE.txt'
if license_file.is_file():datas.append((str(license_file),'licenses/python'))
hidden=[]
for f in (src/'newsflow').rglob('*.py'):
    rel=f.relative_to(src).with_suffix('')
    if 'migrations' in rel.parts:continue
    parts=list(rel.parts)
    if parts[-1]=='__init__':parts.pop()
    hidden.append('.'.join(parts))
hidden+=['uvicorn.protocols.http.h11_impl','uvicorn.protocols.websockets.websockets_impl','uvicorn.lifespan.on','uvicorn.loops.asyncio','sqlalchemy.dialects.sqlite','PIL.PngImagePlugin','PIL.JpegImagePlugin','PIL.WebPImagePlugin','tzdata','win32crypt']
a=Analysis([str(p/'tools/distribution/app_entry.py')],pathex=[str(src),str(p/'tools/distribution')],binaries=[(str(media/n),'media') for n in ('ffmpeg.exe','ffprobe.exe')],datas=datas,hiddenimports=sorted(set(hidden)),hookspath=[],runtime_hooks=[],excludes=['playwright','pytest','_pytest','ruff','tkinter','technical_boundary','technical_probe','step13_guard','verification_gate','guard_capability'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[('X utf8',None,'OPTION')],exclude_binaries=True,name='NewsFlowAI-Candidate',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='NewsFlowAI-Candidate')
