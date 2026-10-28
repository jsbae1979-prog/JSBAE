"""Current-user-only distribution data root; no operating data/ACL migration."""
from __future__ import annotations

import os
from pathlib import Path
import socket


def unlinked(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or part.is_junction()
                            or getattr(part.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('reparse-data-path')
    return path


def _api():
    if os.name != 'nt':
        raise RuntimeError('Windows required')
    import win32api, win32con, win32file, win32security
    return win32api, win32con, win32file, win32security


def current_sid():
    api, con, _, security = _api()
    token = security.OpenProcessToken(api.GetCurrentProcess(), con.TOKEN_QUERY)
    try:
        return security.GetTokenInformation(token, security.TokenUser)[0]
    finally:
        token.Close()


def private_directory(path: Path):
    """Only create fresh private directories; fail on unsafe existing ACL/owner."""
    _, _, files, security = _api()
    path = unlinked(path)
    sid = current_sid()
    sid_text = security.ConvertSidToStringSid(sid)
    allowed = {sid_text, 'S-1-5-18', 'S-1-5-32-544'}
    if not path.parent.is_dir():
        raise ValueError('parent-required')
    if not path.exists():
        sd = security.SECURITY_DESCRIPTOR()
        acl = security.ACL()
        for text in allowed:
            acl.AddAccessAllowedAceEx(security.ACL_REVISION, 3, 0x1F01FF,
                                     security.ConvertStringSidToSid(text))
        sd.SetSecurityDescriptorOwner(sid, False)
        sd.SetSecurityDescriptorDacl(True, acl, False)
        sd.SetSecurityDescriptorControl(security.SE_DACL_PROTECTED,security.SE_DACL_PROTECTED)
        import pywintypes
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = sd
        files.CreateDirectory(str(path), attributes)
    unlinked(path)
    sd = security.GetFileSecurity(str(path),security.OWNER_SECURITY_INFORMATION|security.DACL_SECURITY_INFORMATION)
    owner = security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
    acl = sd.GetSecurityDescriptorDacl()
    if (owner != sid_text or acl is None or not
            sd.GetSecurityDescriptorControl()[0]&security.SE_DACL_PROTECTED):
        raise ValueError('wrong-owner-or-null-dacl')
    owner_access = False
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] != security.ACCESS_ALLOWED_ACE_TYPE:
            raise ValueError('unreviewed-data-ace')
        who = security.ConvertSidToStringSid(ace[2])
        if who not in allowed:
            raise ValueError('foreign-data-ace')
        owner_access |= who == sid_text and (ace[1]&0x1F01FF)==0x1F01FF
    if not owner_access:
        raise ValueError('owner-access-missing')
    return path


def distribution_profile(local_appdata: Path):
    base = Path(local_appdata)
    if not base.is_absolute() or not base.is_dir():
        raise ValueError('absolute-localappdata-required')
    root = private_directory(base/'NewsFlowAI-Desktop')
    return private_directory(root/'v1')


def reserve_user_socket():
    """OS-assigned exclusive per-launch port. No writes/queries to port 8765."""
    listener = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        listener.bind(('127.0.0.1',0))
        if listener.getsockname()[1] == 8765:
            raise ValueError('operating-port-forbidden')
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise
