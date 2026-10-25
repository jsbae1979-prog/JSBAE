"""Step13G.2 test-only, fail-closed boundary. Never imported by the product."""
import os,sys,json,pathlib,hashlib,ipaddress,re,sqlite3,threading,ctypes,subprocess
from urllib.parse import urlsplit,unquote,parse_qsl
ROOT=pathlib.Path(__file__).parent.resolve()
CONFIG=json.loads((ROOT/'guard-config-private.json').read_text(encoding='utf-8'))
PROJECT=pathlib.Path(CONFIG['project']).resolve()
READ_ROOTS=tuple(pathlib.Path(x).resolve() for x in CONFIG['read_roots'])
PINNED={pathlib.Path(k).resolve():v for k,v in CONFIG['binaries'].items()}
ATTEMPTS=[];ALLOWED=[];VERIFIED={};INSTALLED=False;PENDING={};ACTIVE={}
# Read permission only for hashing the single native schema adapter executable.
# This is separate from PINNED media execution and does not permit its directory.
NATIVE_READ_FILES=set()
# Bind parser before the audit barrier. No shell or command evaluation.
_shell=ctypes.WinDLL('shell32',use_last_error=True);_kernel=ctypes.WinDLL('kernel32',use_last_error=True)
_parse=_shell.CommandLineToArgvW;_parse.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];_parse.restype=ctypes.POINTER(ctypes.c_wchar_p)
_free=_kernel.LocalFree;_free.argtypes=[ctypes.c_void_p];_free.restype=ctypes.c_void_p

def deny(kind):
 ATTEMPTS.append(kind);raise PermissionError('Step13G2 boundary: '+kind)
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
 if isinstance(value,int):return None
 raw=os.fsdecode(value)
 if raw.upper() in ('NUL',r'\\.\NUL'):return None
 p=path(raw,cwd)
 if write:
  if not inside(p,ROOT) or inside(p,PROJECT):deny('write-outside-synthetic-output')
 elif not any(inside(p,b) for b in READ_ROOTS) and p not in PINNED and p not in NATIVE_READ_FILES:deny('read-outside-allowlist')
 return p
def database_path(value):
 text=os.fsdecode(value)
 if text==':memory:':return None
 if text.startswith('file:'):
  u=urlsplit(text)
  if u.netloc or u.fragment or re.search(r'%(?![0-9a-fA-F]{2})',u.path):deny('sqlite-URI-authority')
  pairs=parse_qsl(u.query,keep_blank_values=True,strict_parsing=True)
  if len(dict(pairs))!=len(pairs) or any(k not in ('mode','cache','immutable') for k,v in pairs):deny('sqlite-URI-query')
  q=dict(pairs)
  if q.get('mode','rwc') not in ('ro','rw','rwc') or q.get('cache','private')!='private' or q.get('immutable','0') not in ('0','1'):deny('sqlite-URI-mode')
  decoded=unquote(u.path)
  if '%' in decoded:deny('sqlite-double-encoding')
  if re.match(r'^/[A-Za-z]:/',decoded):decoded=decoded[1:]
  p=path(decoded)
 else:p=path(text)
 if not inside(p,ROOT) or inside(p,PROJECT):deny('non-synthetic-database')
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
 import native_boundary
 if native_boundary.recognizes_binary(argv[0]):
  return native_boundary.validate_process(executable,argv,cwd,env)
 if path(argv[0],cwd)==pathlib.Path(CONFIG["browser"]["node"]):
  import browser_boundary
  return browser_boundary.validate_node(executable,argv,cwd,env)

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

def address_check(address):
 if not isinstance(address,tuple) or len(address)<2:deny('non-IP-socket')
 host,port=str(address[0]),address[1]
 try:local=ipaddress.ip_address(host).is_loopback
 except ValueError:local=host=='localhost'
 if not local or port==8765:deny('external-or-operating-socket')
def audit(event,args):
 if event in ('socket.connect','socket.bind','socket.sendto','socket.sendmsg'):address_check(args[-1])
 elif event=='socket.getaddrinfo':
  if args[0] not in (None,'','localhost'):
   try:local=ipaddress.ip_address(str(args[0])).is_loopback
   except ValueError:local=False
   if not local:deny('external-DNS')
 elif event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
  mode=args[1] or '';flags=args[2] or 0
  write=(isinstance(mode,str) and any(v in mode for v in 'wax+')) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_TRUNC))
  check_file(args[0],write)
 elif event=='sqlite3.connect':database_path(args[0])
 elif event in ('sqlite3.enable_load_extension','sqlite3.load_extension'):deny('sqlite-native-extension')
 elif event=='subprocess.Popen':
  approved=validate_process(*args);PENDING[threading.get_ident()]=approved
 elif event in ('os.system','os.startfile','os.startfile/2','os.exec','os.posix_spawn','os.spawn','ctypes.dlopen','ctypes.dlsym','ctypes.dlsym/handle'):deny('unapproved-native-execution')
 elif event=='_winapi.CreateProcess':
  # Only an in-progress wrapper call plus the preceding audited Popen can enter.
  tid=threading.get_ident();pending=PENDING.pop(tid,None);active=ACTIVE.get(tid)
  if not pending or pending!=active:deny('native-process-without-approved-Popen')
  if args[0] is not None and path(args[0],args[2])!=path(pending[0]):deny('native-executable-mismatch')
  if not inside(path(args[2] or os.getcwd()),ROOT):deny('native-cwd')
 elif event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.utime'):check_file(args[0],True)
 elif event in ('os.rename','os.link','os.symlink'):check_file(args[0],True);check_file(args[1],True)
 elif event in ('os.listdir','os.scandir') and args and args[0] is not None and not isinstance(args[0],int):check_file(args[0])

# Fixed Windows file/DPAPI operations for synthetic profiles only. This is not
# a general DLL escape: no arbitrary DLL, symbol, process or networking function.
_SYSTEM_DLLS={n:ctypes.WinDLL(str(pathlib.Path(os.environ['SystemRoot'])/'System32'/(n+'.dll')),use_last_error=True) for n in ('kernel32','crypt32','advapi32')}
_SIGNATURES={
 'kernel32':{'CreateFileW':([ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p],ctypes.c_void_p),'CloseHandle':([ctypes.c_void_p],ctypes.c_int),'GetFinalPathNameByHandleW':([ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32],ctypes.c_uint32),'SetFileInformationByHandle':([ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32],ctypes.c_int),'LocalFree':([ctypes.c_void_p],ctypes.c_void_p),'GetCurrentProcess':([],ctypes.c_void_p),'GetCurrentThread':([],ctypes.c_void_p)},
 'crypt32':{n:([ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p],ctypes.c_int) for n in ('CryptProtectData','CryptUnprotectData')},
 'advapi32':{'OpenProcessToken':([ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p],ctypes.c_int),'OpenThreadToken':([ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_void_p],ctypes.c_int),'GetTokenInformation':([ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p],ctypes.c_int),'ConvertSidToStringSidW':([ctypes.c_void_p,ctypes.c_void_p],ctypes.c_int)}}
_NATIVE={}
for _dll,_symbols in _SIGNATURES.items():
 for _symbol,(_types,_result) in _symbols.items():
  _function=getattr(_SYSTEM_DLLS[_dll],_symbol);_function.argtypes=_types;_function.restype=_result;_NATIVE[(_dll,_symbol)]=_function
class _Blob(ctypes.Structure):_fields_=[('cbData',ctypes.c_uint32),('pbData',ctypes.c_void_p)]
_OWNED_HANDLES={};_TOKEN_HANDLES=set();_MINTED_CIPHERTEXT=set()
def _number(value):return value.value if isinstance(value,ctypes.c_void_p) else value
def _native_handle_path(handle):
 buffer=ctypes.create_unicode_buffer(32768)
 count=_NATIVE[('kernel32','GetFinalPathNameByHandleW')](handle,buffer,len(buffer),0)
 if not 0<count<len(buffer):deny('native-file-path')
 text=buffer.value
 if text.startswith('\\\\?\\'):text=text[4:]
 p=path(text)
 if not inside(p,ROOT):deny('native-file-outside-synthetic-root')
 return p
class _GuardedFunction:
 def __init__(self,dll,symbol):self.dll,self.symbol=dll,symbol
 def __call__(self,*args):
  d,n=self.dll,self.symbol;function=_NATIVE[(d,n)]
  if n=='CreateFileW':
   p=check_file(args[0],write=bool(args[1]&0x40010000))
   if p is None or not inside(p,ROOT) or args[4]!=3 or args[1]&~0x80010000:deny('native-file-mode-or-root')
   handle=function(*args)
   if handle not in (None,ctypes.c_void_p(-1).value):
    try:
     opened=_native_handle_path(handle)
     if opened!=p:deny('native-file-reparse-race')
    except BaseException:_NATIVE[('kernel32','CloseHandle')](handle);raise
    _OWNED_HANDLES[handle]=(p,bool(args[1]&0x10000))
   return handle
  if n in ('GetFinalPathNameByHandleW','SetFileInformationByHandle'):
   handle=_number(args[0])
   if handle not in _OWNED_HANDLES:deny('unowned-native-file-handle')
   actual=_native_handle_path(handle)
   if actual!=_OWNED_HANDLES[handle][0]:deny('native-file-handle-moved')
   if n=='SetFileInformationByHandle':
    if not _OWNED_HANDLES[handle][1] or args[1]!=4 or args[3]!=1:deny('native-file-disposition')
    check_file(actual,True)
   return function(*args)
  if n=='CloseHandle':
   handle=_number(args[0])
   if handle not in _OWNED_HANDLES and handle not in _TOKEN_HANDLES:deny('unowned-native-handle-close')
   _OWNED_HANDLES.pop(handle,None);_TOKEN_HANDLES.discard(handle);return function(*args)
  if n in ('CryptProtectData','CryptUnprotectData'):
   blob=ctypes.cast(args[0],ctypes.POINTER(_Blob)).contents
   if not 0<blob.cbData<=1024*1024 or args[5]!=1:deny('native-crypto-shape')
   source=ctypes.string_at(blob.pbData,blob.cbData)
   if n=='CryptUnprotectData' and hashlib.sha256(source).hexdigest() not in _MINTED_CIPHERTEXT:deny('non-test-minted-ciphertext')
   result=function(*args)
   if result and n=='CryptProtectData':
    output=ctypes.cast(args[6],ctypes.POINTER(_Blob)).contents
    if not 0<output.cbData<=1024*1024:deny('native-crypto-output')
    _MINTED_CIPHERTEXT.add(hashlib.sha256(ctypes.string_at(output.pbData,output.cbData)).hexdigest())
   return result
  if n in ('OpenProcessToken','OpenThreadToken'):
   expected=_NATIVE[('kernel32','GetCurrentProcess' if n=='OpenProcessToken' else 'GetCurrentThread')]()
   if _number(args[0])!=expected or args[1]!=8:deny('native-token-query-only')
   result=function(*args)
   if result:_TOKEN_HANDLES.add(ctypes.cast(args[-1],ctypes.POINTER(ctypes.c_void_p)).contents.value)
   return result
  if n=='GetTokenInformation' and (_number(args[0]) not in _TOKEN_HANDLES or args[1]!=1):deny('native-token-user-only')
  return function(*args)
class _GuardedDLL:
 def __init__(self,name):self.name=name
 def __getattr__(self,symbol):
  if (self.name,symbol) not in _NATIVE:deny('unapproved-native-symbol')
  return _GuardedFunction(self.name,symbol)
def _guarded_windll(name,*args,**kwargs):
 if not isinstance(name,str) or name.lower() not in _SYSTEM_DLLS:deny('unapproved-native-DLL')
 return _GuardedDLL(name.lower())

def install():
 global INSTALLED
 if INSTALLED:return
 native_config=ROOT/'native-config-private.json'
 if native_config.is_file():
  native_data=json.loads(native_config.read_text(encoding='utf-8-sig'))
  expected=(pathlib.Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe').resolve()
  if pathlib.Path(native_data['powershell']).resolve()!=expected or not re.fullmatch(r'[0-9a-f]{64}',native_data.get('powershell_SHA256','')):deny('native-read-file-config')
  NATIVE_READ_FILES.add(expected)
 # Defense-in-depth belongs only to this test launcher: every native media input
 # receives a file/pipe-only protocol whitelist before the audit and CreateProcess.
 original_popen_init=subprocess.Popen.__init__
 def media_popen(self,args,*pos,**kwargs):
  if kwargs.get('shell',False) or (len(pos)>7 and pos[7]):deny('shell-prohibited')
  argv=split_windows(args)
  import native_boundary
  if native_boundary.recognizes_binary(argv[0]):
   args,kwargs=native_boundary.prepare_spawn(args,pos,kwargs)
   argv=split_windows(args)
  binary=path(argv[0],kwargs.get('cwd'))
  if binary in PINNED:
   secured=[argv[0]]
   if binary.stem.lower()=='ffprobe':secured+=['-protocol_whitelist','file']
   for item in argv[1:]:
    if item=='-i':secured+=['-protocol_whitelist','file']
    secured.append(item)
   args=secured
  if binary==pathlib.Path(CONFIG["browser"]["node"]):kwargs["cwd"]=str(ROOT)
  approved=validate_process(kwargs.get('executable'),args,kwargs.get('cwd'),kwargs.get('env'))
  tid=threading.get_ident();ACTIVE[tid]=approved
  try:return original_popen_init(self,args,*pos,**kwargs)
  finally:
   ACTIVE.pop(tid,None);PENDING.pop(tid,None);native_boundary.clear_launch()
 subprocess.Popen.__init__=media_popen
 import native_boundary
 native_boundary.install_run_boundary()
 ctypes.WinDLL=_guarded_windll
 sys.addaudithook(audit);INSTALLED=True
 # SQLite ATTACH bypasses Python open. A test-only authorizer closes that gap.
 original=sqlite3.connect
 class SyntheticConnection(sqlite3.Connection):
  def __init__(self,*args,**kwargs):
   super().__init__(*args,**kwargs)
   def authorize(action,arg1,arg2,db,trigger):
    if action==sqlite3.SQLITE_ATTACH:
     try:database_path(arg1)
     except (PermissionError,ValueError):return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK
   self.set_authorizer(authorize)
 def connect(*args,**kwargs):
  if 'factory' not in kwargs:kwargs['factory']=SyntheticConnection
  return original(*args,**kwargs)
 sqlite3.connect=connect;sqlite3.dbapi2.connect=connect

def pytest_sessionfinish(session,exitstatus):
 import native_boundary
 native_boundary.write_evidence(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])
 out=pathlib.Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
 (out/'strict-guard.json').write_text(json.dumps({'denied':ATTEMPTS,'allowed_binary_counts':{k:ALLOWED.count(k) for k in set(ALLOWED)},'exitstatus':exitstatus,'installed_before_pytest_import':True,'only_pinned_FFmpeg_ffprobe_media_allowed':True,'only_registered_pinned_Node_entry_allowed':True,'browser_child_validated_by_Node_preload':True,'global_guard_disabled':False,'external_network_allowed':False,'operating_file_contents_allowed':False,'fixed_guarded_Python_children_only':True,'PowerShell_identity_validate_only':True}),encoding='utf-8')

