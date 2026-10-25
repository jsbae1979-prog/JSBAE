"""Real deny-before-I/O checks, synthetic files and pinned local FFmpeg only."""
from pathlib import Path
import os,sqlite3,socket,subprocess,ctypes,json
import pytest
import step13_guard as g

def binary(name='ffmpeg'):
 return next(p for p in g.PINNED if p.stem==name)
def test_windows_none_executable_and_explicit_path_are_parsed(tmp_path):
 args=[str(binary()),'-version']
 assert g.validate_process(None,subprocess.list2cmdline(args),str(tmp_path),{})==args
 assert g.validate_process(str(binary()),args,str(tmp_path),{})==args
@pytest.mark.parametrize('argv',[['ffmpeg','-version'],['cmd.exe','/c','echo x'],['powershell.exe','-NoProfile'],['claude','--version'],['codex','--version'],['curl','https://example.com']])
def test_arbitrary_or_relative_executable_is_denied(tmp_path,argv):
 with pytest.raises(PermissionError):subprocess.run(argv,cwd=tmp_path,env={})
def test_shell_is_denied_before_creation(tmp_path):
 with pytest.raises(PermissionError,match='shell-prohibited'):subprocess.run([str(binary()),'-version'],shell=True,cwd=tmp_path,env={})
def test_separate_executable_cannot_disagree(tmp_path):
 with pytest.raises(PermissionError):g.validate_process(str(binary('ffprobe')),[str(binary()),'-version'],str(tmp_path),{})
@pytest.mark.parametrize('tail',[
 ['-i','https://example.com/test.mp4','x.mp4'],['-i','file:C:/outside.mp4','x.mp4'],
 ['-i',r'\\server\share\a.mp4','x.mp4'],['-i','C:/outside:a','x.mp4'],
 ['-f','lavfi','-i','movie=https://example.com/x','x.mp4'],
 ['-f','lavfi','-i','testsrc2=size=16x16:duration=1','-vf','movie=/outside.mp4','x.mp4'],
 ['-report'],['-protocol_whitelist','file,http','x.mp4'],['-safe','0','x.mp4'],
 ['-format_whitelist','hls,mov','x.mp4'],['-f','hls','x.mp4'],['-i','x.m3u8','x.mp4'],['-y',str(Path(__file__).parent.parent/'never-write.mp4')]])
def test_network_filter_path_and_option_injection_denied(tmp_path,tail):
 with pytest.raises(PermissionError):g.validate_process(None,[str(binary()),*tail],str(tmp_path),{})
def test_modified_hash_denies_without_running(monkeypatch,tmp_path):
 b=binary();monkeypatch.setitem(g.PINNED,b,'0'*64);g.VERIFIED.pop(b,None)
 with pytest.raises(PermissionError,match='hash'):g.validate_process(None,[str(b),'-version'],str(tmp_path),{})
 g.VERIFIED.pop(b,None)
@pytest.mark.parametrize('uri',['file://remote/share/a.db','file:///C:/outside.db?mode=ro','file:///C:/outside.db?mode=ro&mode=rw','https://example.com/a.db','file:///C:/a%252f.db?mode=ro'])
def test_sqlite_bad_uri_denied(uri):
 with pytest.raises((PermissionError,ValueError)):g.database_path(uri)
def test_sqlite_local_uri_and_attach_boundary(tmp_path):
 p=tmp_path/'local.db'
 with sqlite3.connect(p) as con:con.execute('create table example(value)');con.execute('insert into example values(42)')
 with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as con:
  assert con.execute('select value from example').fetchone()==(42,)
  with pytest.raises(sqlite3.DatabaseError):con.execute("ATTACH DATABASE 'C:/outside.db' AS forbidden")
 with sqlite3.connect(':memory:') as con:assert con.execute('select 1').fetchone()==(1,)
def test_operating_read_and_outside_write_denied(tmp_path):
 with pytest.raises(PermissionError):(Path(__file__).parent.parent/'forbidden-operating-profile/newsflow-ai/pyproject.toml').read_bytes()
 outside=Path(__file__).parent.parent/'never-write.txt'
 with pytest.raises(PermissionError):outside.write_text('forbidden')
 assert not outside.exists()
@pytest.mark.parametrize('host,port',[('203.0.113.2',443),('127.0.0.1',8765),('::1',8765)])
def test_network_boundary_without_transmission(host,port):
 with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM) as s:
  with pytest.raises(PermissionError):s.connect((host,port))
def test_udp_and_system_execution_denied():
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
  with pytest.raises(PermissionError):s.sendto(b'NO SEND',('203.0.113.2',443))
 with pytest.raises(PermissionError):os.system('echo MUST_NOT_RUN')
 with pytest.raises(PermissionError):ctypes.WinDLL('wininet')
def test_pinned_ffmpeg_and_ffprobe_run_without_network(tmp_path):
 for name in ('ffmpeg','ffprobe'):
  result=subprocess.run([str(binary(name)),'-version'],cwd=tmp_path,env={},capture_output=True,check=True,timeout=10)
  assert result.stdout.startswith(name.encode()+b' version')
 target=tmp_path/'synthetic.mp4'
 subprocess.run([str(binary()),'-v','error','-nostdin','-f','lavfi','-i','color=c=red:s=64x64:d=0.2','-c:v','libx264','-pix_fmt','yuv420p',str(target)],cwd=tmp_path,env={},capture_output=True,check=True,timeout=20)
 assert target.stat().st_size>100
 subprocess.run([str(binary()),'-v','error','-i',str(target),'-f','null','-'],cwd=tmp_path,env={},capture_output=True,check=True,timeout=10)
 metadata=json.loads(subprocess.run([str(binary('ffprobe')),'-v','error','-format_whitelist','mov,mp4,m4a,3gp,3g2,mj2,matroska,webm','-show_format','-of','json',str(target)],cwd=tmp_path,env={},capture_output=True,check=True,timeout=10).stdout)
 assert float(metadata['format']['duration'])>.1


def test_direct_native_creation_without_popen_context_is_denied(tmp_path):
 with pytest.raises(PermissionError,match='without-approved-Popen'):
  g.audit('_winapi.CreateProcess',(None,str(binary())+' -version',str(tmp_path)))


def test_native_file_handle_is_limited_to_synthetic_root(tmp_path):
 p=tmp_path/'owned.txt';p.write_bytes(b'synthetic')
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 handle=kernel.CreateFileW(str(p),0x80000000,1,None,3,0x80,None)
 assert handle not in (None,ctypes.c_void_p(-1).value)
 kernel.CloseHandle(handle)
 with pytest.raises(PermissionError):kernel.CreateFileW(r'C:\forbidden-operating-profile\newsflow-ai\pyproject.toml',0x80000000,1,None,3,0x80,None)
 with pytest.raises(PermissionError):kernel.CreateFileW(str(p),0x40000000,0,None,3,0x80,None)
 with pytest.raises(PermissionError):kernel.CreateFileW(str(p),0x80000000,0,None,2,0x80,None)

def test_native_process_and_network_symbols_are_not_available():
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 with pytest.raises(PermissionError):kernel.CreateProcessW
 with pytest.raises(PermissionError):ctypes.WinDLL('wininet')
 with pytest.raises(PermissionError):kernel.CloseHandle(1234567)

def test_dpapi_can_only_decrypt_this_process_minted_synthetic_blob():
 from newsflow.oauth.vault import _DPAPI,VaultError
 cipher=_DPAPI();plain=bytearray(b'SYNTHETIC_GUARD_ONLY');entropy=bytearray(b'SYNTHETIC_ENTROPY')
 encrypted=cipher.protect(plain,entropy)
 assert cipher.unprotect(encrypted,entropy)==plain
 with pytest.raises(VaultError):cipher.unprotect(bytearray(b'NOT_MINTED_BY_TEST'),entropy)

def test_native_crypto_disallows_machine_scope():
 blob=g._Blob();blob.cbData=1;data=ctypes.create_string_buffer(b'x');blob.pbData=ctypes.cast(data,ctypes.c_void_p).value
 with pytest.raises(PermissionError):ctypes.WinDLL('crypt32').CryptProtectData(ctypes.byref(blob),None,None,None,None,4,ctypes.byref(g._Blob()))

@pytest.mark.parametrize('ratio', ['4/3', '1/1', '16/9'])
def test_safe_sar_is_arithmetic_only(tmp_path, ratio):
 args=[str(binary()),'-f','lavfi','-i','testsrc2=size=16x16:duration=1','-vf','setsar='+ratio,'-t','1',str(tmp_path/'out.mp4')]
 assert g.validate_process(None,args,str(tmp_path),{})==args

@pytest.mark.parametrize('value', ['setsar=1/0','setsar=../3','setsar=4/3,movie=/outside','setsar=4/3;amovie=http://outside','setsar=4/3,drawtext=text=x','setsar=4/3\\file'])
def test_ratio_exception_cannot_smuggle_paths_or_filters(value):
 with pytest.raises(PermissionError):g.validate_filter(value)

def test_bounded_testsrc_hue_is_allowed():
 g.validate_lavfi('testsrc2=size=480x360:rate=30:duration=5,hue=H=2*PI*t/5')

@pytest.mark.parametrize('value', [
 'testsrc2=size=480x360:rate=30:duration=5,hue=H=2*PI*t/0',
 'testsrc2=size=9000x360:rate=30:duration=5,hue=H=2*PI*t/5',
 'testsrc2=size=480x360:rate=999:duration=5,hue=H=2*PI*t/5',
 'testsrc2=size=480x360:rate=30:duration=99,hue=H=2*PI*t/5',
 'testsrc2=size=480x360:rate=30:duration=5,hue=H=2*PI*t/5,movie=http://outside',
 'testsrc2=size=480x360:rate=30:duration=5,hue=H=2*PI*t/../5',
])
def test_hue_exception_is_bounded_and_not_general_expression_execution(value):
 with pytest.raises(PermissionError):g.validate_lavfi(value)

@pytest.mark.parametrize('value', [r'C:\forbidden-operating-profile', r'D:\forbidden-backup-A', str(Path(__file__).parent.parent/'backup-B')])
def test_operating_and_backup_roots_still_deny_content_reads(value):
 with pytest.raises(PermissionError):g.check_file(value)

def test_sqlite_uri_roundtrip_stays_synthetic_and_attach_outside_is_denied(tmp_path):
 from contextlib import closing
 path=tmp_path/'synthetic.sqlite3'
 uri=path.as_uri()+'?mode=rwc&cache=private'
 assert g.database_path(uri)==path.resolve()
 with closing(sqlite3.connect(uri,uri=True)) as conn:
  conn.execute('create table fixture_value(value integer)')
  conn.execute('insert into fixture_value values(7)')
  assert conn.execute('select value from fixture_value').fetchone()==(7,)
  with pytest.raises(sqlite3.DatabaseError):conn.execute("ATTACH DATABASE 'C:/forbidden-operating-profile/not-accessed.db' AS denied")
 assert not (Path(__file__).parent/'not-accessed.db').exists()

@pytest.mark.parametrize('name', [r'C:\Program Files\Google\Chrome\Application\chrome.exe', r'C:\unapproved\playwright\node.exe'])
def test_browser_and_driver_are_still_not_approved_executables(tmp_path,name):
 with pytest.raises(PermissionError,match='unapproved-executable'):subprocess.run([name,'--version'],cwd=tmp_path,env={})
 assert {p.stem.lower() for p in g.PINNED}=={'ffmpeg','ffprobe'}
