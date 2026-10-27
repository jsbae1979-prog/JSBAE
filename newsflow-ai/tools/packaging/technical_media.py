"""Technical-build media validation reused from the accepted test Guard.
No native Python, Node, browser or arbitrary binary exception is present.
"""
import ctypes
import hashlib
import os
import pathlib
import re

ROOT=None;PINNED={};VERIFIED={};ALLOWED=[];ATTEMPTS=[]
_shell=ctypes.WinDLL("shell32",use_last_error=True)
_parse=_shell.CommandLineToArgvW;_parse.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];_parse.restype=ctypes.POINTER(ctypes.c_wchar_p)
_free=ctypes.WinDLL("kernel32").LocalFree;_free.argtypes=[ctypes.c_void_p];_free.restype=ctypes.c_void_p
def configure(root,binaries):
 global ROOT,PINNED
 ROOT=root;PINNED={pathlib.Path(k).resolve():v for k,v in binaries.items()}
def deny(reason):
 ATTEMPTS.append(reason);raise PermissionError("Technical media boundary: "+reason)
def inside(p,base):return p==base or p.is_relative_to(base)
def path(value,cwd=None):
 try:
  raw=os.fsdecode(value)
  if '\x00' in raw or raw.startswith(('\\\\','//')):deny('device-UNC-or-invalid-path')
  p=pathlib.Path(raw)
  if not p.is_absolute():p=(pathlib.Path(cwd) if cwd else pathlib.Path.cwd())/p
  if ':' in str(p)[2:]:deny('ADS-path')
  return p.resolve()
 except PermissionError:raise
 except (ValueError,OSError,TypeError):deny('unresolvable-path')
def check_file(value,write=False,cwd=None):
 p=path(value,cwd)
 if not inside(p,ROOT):deny("outside-synthetic-media")
 return p
def split_windows(args):
 if isinstance(args,(tuple,list)):
  if not args or not all(isinstance(x,(str,bytes,os.PathLike)) for x in args):deny('invalid-argv')
  return [os.fsdecode(x) for x in args]
 if not isinstance(args,str) or not args or len(args)>32767 or '\x00' in args:deny('invalid-commandline')
 count=ctypes.c_int();data=_parse(args,ctypes.byref(count))
 if not data:deny('invalid-commandline')
 try:return [data[i] for i in range(count.value)]
 finally:_free(data)
FLAGS={'-hide_banner','-nostdin','-n','-y','-an','-vn','-shortest','-show_streams','-show_format','-show_packets','-show_frames','-version'}
VALUES={'-loglevel','-v','-f','-format_whitelist','-i','-t','-ss','-sseof','-frames:v','-vframes','-r','-framerate','-loop','-stream_loop','-c:v','-c:a','-codec:v','-codec:a','-c','-preset','-crf','-pix_fmt','-ar','-ac','-b:a','-vf','-af','-filter:v','-filter:a','-filter_complex','-map','-movflags','-threads','-filter_threads','-filter_complex_threads','-safe','-protocol_whitelist','-of','-print_format','-show_entries','-select_streams','-vsync','-s','-s:v','-read_intervals','-video_track_timescale','-tag:v','-color_range','-colorspace','-color_primaries','-color_trc','-map_metadata','-flags','-fflags','-sws_flags','-fps_mode','-sample_fmt','-channel_layout'}
FORMATS={'lavfi','concat','mp4','mov','matroska','webm','image2','image2pipe','wav','s16le','f32le','rawvideo','null'}
def media_path(value,cwd,output=False):
 if value in ('-','pipe:1') and output:return None
 if value=='-':deny('stdin-media-input')
 if '://' in value or value.lower().startswith(('file:','pipe:','crypto:','concat:','data:','http:','https:','tcp:','udp:')):deny('media-protocol')
 return check_file(value,write=output,cwd=cwd)
def validate_lavfi(value):
 # Preserve the existing generator policy. One bounded numeric hue fixture is also safe data.
 if re.fullmatch(r'(?:testsrc2?|color|anullsrc|sine)=[A-Za-z0-9_:=.,+#@/\-]+',value) and '/' not in value:return
 match=re.fullmatch(r'testsrc2?=size=(\d{1,4})x(\d{1,4}):rate=(\d{1,3}):duration=(\d{1,2}),hue=H=2\*PI\*t/([1-9]\d?)',value)
 if match:
  width,height,rate,seconds,divisor=map(int,match.groups())
  if 1<=width<=4096 and 1<=height<=4096 and 1<=rate<=120 and 1<=seconds<=60 and 1<=divisor<=60:return
 deny('unsafe-lavfi')

def validate_filter(value):
 # A whole setsar ratio is arithmetic, never a path or an extra filter chain.
 if re.fullmatch(r'setsar=[1-9]\d{0,2}/[1-9]\d{0,2}',value):return
 if re.search(r'(?i)(movie|amovie|subtitles|drawtext|zmq|sendcmd|asendcmd|frei0r|ladspa|lv2|[a-z]+://|[/\\])',value):deny('unsafe-filter')

def validate_process(executable,args,cwd,env):
 argv=split_windows(args)
 binary=path(argv[0],cwd)
 if not pathlib.Path(argv[0]).is_absolute() or binary not in PINNED:deny('unapproved-executable')
 if executable is not None and (not pathlib.Path(os.fsdecode(executable)).is_absolute() or path(executable,cwd)!=binary):deny('executable-argv-mismatch')
 work=path(cwd or os.getcwd())
 if not inside(work,ROOT):deny('process-cwd')
 actualenv=os.environ if env is None else env
 if any(k.upper()=='FFREPORT' or k.upper().endswith(('_KEY','_TOKEN','_PASSWORD','_SECRET')) for k in actualenv):deny('process-secret-or-report-env')
 st=binary.stat();stamp=(st.st_size,st.st_mtime_ns)
 if VERIFIED.get(binary)!=stamp:
  if hashlib.sha256(binary.read_bytes()).hexdigest()!=PINNED[binary]:deny('binary-hash-mismatch')
  VERIFIED[binary]=stamp
 fmt=None;i=1;positions=[];inputs=[]
 while i<len(argv):
  v=argv[i]
  if v in FLAGS:i+=1;continue
  if v!='-' and v.startswith('-') and v not in VALUES:deny('unapproved-media-option')
  if v in VALUES:
   if i+1>=len(argv):deny('missing-option-value')
   val=argv[i+1]
   if any(c in val for c in '\r\n\x00'):deny('control-in-argv')
   if v=='-f':
    if val not in FORMATS:deny('unapproved-demuxer')
    fmt=val
   elif v=='-i':
    if fmt=='lavfi':
     validate_lavfi(val)
    else:
     inp=media_path(val,work);inputs.append(inp)
     # Local playlist contents cannot smuggle any URL or path outside the output root.
     if inp and (fmt=='concat' or inp.suffix.lower()=='.txt'):
      for line in inp.read_text(encoding='utf-8-sig').splitlines():
       m=re.fullmatch(r"file '([A-Za-z0-9_.-]+)'",line)
       if not m:deny('unsafe-concat-manifest')
       media_path(m[1],inp.parent)
    fmt=None
   elif v=='-protocol_whitelist' and set(val.split(','))-{'file','pipe'}:deny('protocol-whitelist')
   elif v=='-safe' and val!='1':deny('unsafe-concat-mode')
   elif v=='-format_whitelist' and set(val.split(','))-{'mov','mp4','m4a','3gp','3g2','mj2','matroska','webm'}:deny('format-whitelist')
   elif v in ('-vf','-af','-filter:v','-filter:a','-filter_complex'):
    validate_filter(val)
   elif '://' in val or val.startswith(('\\\\','//')):deny('network-in-option')
   i+=2;continue
  positions.append(v);i+=1
 probe=binary.stem.lower()=='ffprobe'
 if len(positions)>1:deny('multiple-positional-outputs')
 for v in positions:media_path(v,work,output=not probe)
 if any(p and p.suffix.lower() in ('.m3u8','.m3u','.sdp','.ffconcat') for p in inputs):deny('playlist-input')
 ALLOWED.append(binary.stem)
 return argv

