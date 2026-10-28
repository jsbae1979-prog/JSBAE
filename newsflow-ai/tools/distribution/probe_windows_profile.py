"""Native checks on a NEW owned synthetic root only. No app/operating data."""
import hashlib,json,os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from newsflow.distribution.windows_profile import distribution_profile,private_directory,reserve_user_socket

def main():
    root=Path(os.environ['NEWSFLOW_DISTRIBUTION_TEST_ROOT']).resolve()
    if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or not root.is_dir():raise RuntimeError('Owned workspace required')
    target=root/'native-probe'
    if target.exists():raise RuntimeError('Do not reuse a native probe root')
    target.mkdir();results={}
    profile=distribution_profile(target)
    results['private_acl_create_and_reopen']=private_directory(profile)==profile
    import win32security,win32crypt
    acl=win32security.GetFileSecurity(str(profile),win32security.DACL_SECURITY_INFORMATION)
    results['dacl_protected']=bool(acl.GetSecurityDescriptorControl()[0]&win32security.SE_DACL_PROTECTED)
    results['acl_principal_count']=acl.GetSecurityDescriptorDacl().GetAceCount()
    opaque=win32crypt.CryptProtectData(b'SYNTHETIC-NOT-A-REAL-KEY',None,None,None,None,1)
    file=profile/'synthetic-roundtrip.dpapi';file.write_bytes(opaque)
    results['dpapi_same_user_roundtrip']=win32crypt.CryptUnprotectData(file.read_bytes(),None,None,None,1)[1]==b'SYNTHETIC-NOT-A-REAL-KEY'
    before=hashlib.sha256(file.read_bytes()).hexdigest()
    results['reopen_preserves_ciphertext']=private_directory(profile)==profile and hashlib.sha256(file.read_bytes()).hexdigest()==before
    # A new intentionally unprotected inherited folder MUST be refused, not repaired.
    unsafe=target/'inherited-not-private';unsafe.mkdir()
    try:private_directory(unsafe)
    except ValueError:results['unsafe_existing_acl_rejected']=True
    else:results['unsafe_existing_acl_rejected']=False
    with reserve_user_socket() as first,reserve_user_socket() as second:
        a,b=first.getsockname()[1],second.getsockname()[1]
        results['two_owned_ports_differ']=a!=b and a!=8765 and b!=8765
    results['actual_other_windows_sid']='NOT VERIFIED'
    results['real_keys_used']=False
    results['production_data_accessed']=False
    (root/'native-profile-results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    print(json.dumps(results))
    checks=[results[k] for k in ('private_acl_create_and_reopen','dacl_protected',
        'dpapi_same_user_roundtrip','reopen_preserves_ciphertext','unsafe_existing_acl_rejected','two_owned_ports_differ')]
    if not all(checks):raise SystemExit(1)
if __name__=='__main__':main()
