"""Explicit-profile portable BAT Start/Stop; no operating profile adoption.

The old candidates remain inert. A newly assembled validation layout must opt in
explicitly. Stop retains a query/synchronize-only process handle and asks the
matching private loopback session to shut down; no signal, kill, shell or retry.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass

from .lifecycle import (Blocked, ProcessIdentity, fixed_port, ordinary_absolute,
                        prepare_start, start_plan, stop_owned)

_DLL_HANDLES = []


@dataclass(frozen=True)
class ValidationConfig:
    program: Path
    profile: Path
    port: int
    installation_id: str
    open_browser: bool
    profile_kind: str = "synthetic"


def load_config(root):
    root = ordinary_absolute(root)
    layout = json.loads((root / 'app/layout.json').read_bytes())
    if layout.get('liveStartStopConnected') is not True:
        raise Blocked('live-start-stop-not-provisioned')
    if layout.get('portableFirstRun') is True:
        from .portable import load_portable
        return load_portable(root, layout)
    if layout.get('operatingProfile') == 'restored-local-operation':
        from .operation import load_operating
        return load_operating(root, layout)
    if layout.get('validationOnly') is not True:
        raise Blocked('live-validation-not-provisioned')
    if layout.get('validationProfile') == 'restored-private-validation':
        from .restored_install import load_restored
        return load_restored(root, layout)
    # Test harness metadata lives outside the immutable distributable program.
    source = ordinary_absolute(root.parent / 'validation-launch.json')
    if source.stat().st_size > 4096:
        raise Blocked('invalid-validation-configuration')
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != layout.get('validationConfigSha256'):
        raise Blocked('validation-configuration-integrity')
    raw = json.loads(content)
    if (raw.get('schemaVersion') != 1 or raw.get('syntheticOnly') is not True
            or raw.get('profileName') != 'SyntheticProfile' or type(raw.get('openBrowser')) is not bool):
        raise Blocked('synthetic-validation-only')
    import re
    if not re.fullmatch('[0-9a-f]{32}', raw.get('installationId', '')):
        raise Blocked('invalid-installation-identity')
    profile = ordinary_absolute(root.parent / 'SyntheticProfile')
    kind = 'synthetic-local-work' if layout.get('validationProfile') == 'synthetic-local-work' else 'synthetic'
    return ValidationConfig(root, profile, fixed_port(raw['port']), raw['installationId'], raw['openBrowser'], kind)


def bootstrap(config):
    if (sys.platform != 'win32' or sys.version_info[:3] != (3, 14, 7)
            or platform.machine().upper() not in {'AMD64', 'X86_64'}
            or ordinary_absolute(Path(sys.executable)) != config.program / 'app/runtime/python.exe'):
        raise Blocked('bundled-python-3147-required')
    # Explicit package DLL directory; never broaden PATH or load vendor .pth hooks.
    folder = ordinary_absolute(config.program / 'app/site-packages/pywin32_system32')
    _DLL_HANDLES.append(os.add_dll_directory(str(folder)))
    for key in list(os.environ):
        upper = key.upper()
        if (upper.startswith('NEWSFLOW_') or any(x in upper for x in (
                'OPENAI', 'ANTHROPIC', 'ELEVENLABS', 'HIGGSFIELD', 'SERPAPI',
                'OAUTH', 'YOUTUBE', 'INSTAGRAM', 'TIKTOK', 'FACEBOOK',
                'API_KEY', 'ACCESS_TOKEN', 'REFRESH_TOKEN'))):
            os.environ.pop(key, None)


def _atomic(path, data):
    temporary = path.with_suffix(path.suffix + '.new')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_session(profile):
    p = ordinary_absolute(profile / 'bat-session.private.json')
    if not p.is_file() or p.stat().st_size > 8192:
        raise Blocked('no-owned-session')
    data = json.loads(p.read_bytes())
    return ProcessIdentity(data['pid'], data['creation_id'], data['owner_sid'],
                           Path(data['executable']), data['installation_id'], data['session_nonce'])


def _profile(config, create):
    if config.profile_kind == 'portable-local-operation':
        from .portable import prepare_profile
        return prepare_profile(config, create)
    from newsflow.distribution.windows_profile import current_sid, private_directory
    import win32security
    if not config.profile.exists() and not create:
        raise Blocked('no-owned-session')
    fresh = not config.profile.exists()
    if config.profile_kind in {'restored-private-validation', 'restored-local-operation'}:
        if fresh:
            raise Blocked('restored-profile-must-be-migrated-first')
        private_directory(config.profile)
        from .restored_install import check_restored_profile
        sid = win32security.ConvertSidToStringSid(current_sid())
        check_restored_profile(config, sid)
        return sid
    private_directory(config.profile)
    marker = config.profile / 'synthetic-install.json'
    if fresh:
        _atomic(marker, {'installationId': config.installation_id, 'syntheticOnly': True})
    if not marker.is_file() or json.loads(marker.read_bytes()) != {
            'installationId': config.installation_id, 'syntheticOnly': True}:
        raise Blocked('existing-user-profile-refused')
    if any(config.profile.rglob('*.dpapi')):
        raise Blocked('real-credentials-refused')
    for folder in config.profile.iterdir():
        if folder.is_dir() and 'oauth' in folder.name.lower() and any(p.is_file() for p in folder.rglob('*')):
            raise Blocked('oauth-material-refused')
    return win32security.ConvertSidToStringSid(current_sid())


def _image_name(handle):
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    query.restype = w.BOOL
    count = w.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(count.value)
    if not query(int(handle), 0, buffer, ctypes.byref(count)):
        raise OSError('process-image-query-failed')
    return ordinary_absolute(Path(buffer.value))


def _identity(handle, pid, installation, nonce):
    import win32con
    import win32process
    import win32security
    token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
    try:
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(
            token, win32security.TokenUser)[0])
    finally:
        token.Close()
    created = win32process.GetProcessTimes(handle)['CreationTime'].isoformat()
    return ProcessIdentity(pid, created, sid, _image_name(handle), installation, nonce)


class WindowsStart:
    def check_private_profile(self, path, owner_sid):
        from newsflow.distribution.windows_profile import private_directory
        private_directory(path)

    def reserve_exclusive(self, host, port):
        from newsflow.runtime import reserve_socket
        class Lease:
            def __init__(self):
                self.host, self.port = host, port
                self.socket = reserve_socket(host, port)
            def close(self):
                self.socket.close()
        return Lease()


class SyntheticRequests:
    """Validation allows local reads and one defaults save; no generation/posting."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if (scope['type'] == 'http' and scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}
                and (scope['method'], scope['path']) not in {
                    ('POST', '/__local/claim'), ('POST', '/api/feed-batches/defaults')}):
            await send({'type': 'http.response.start', 'status': 403,
                        'headers': [(b'content-type', b'text/plain'), (b'cache-control', b'no-store')]})
            return await send({'type': 'http.response.body', 'body': b'Synthetic validation: execution disabled.'})
        return await self.app(scope, receive, send)


class Control:
    """Private session control in front of the unchanged LocalAccess wrapper."""
    def __init__(self, app, identity, origin, stop):
        self.app, self.identity, self.origin, self.stop = app, identity, origin, stop
        self.requested = False

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/__bat/'):
            return await self.app(scope, receive, send)
        raw = scope.get('headers', [])
        headers = {k.lower(): v.decode('latin1') for k, v in raw}
        allowed = (scope.get('client', ('',))[0] == '127.0.0.1'
                   and headers.get(b'host') == self.origin.removeprefix('http://')
                   and headers.get(b'origin') == self.origin
                   and not scope.get('query_string')
                   and headers.get(b'content-length', '0') == '0'
                   and b'transfer-encoding' not in headers
                   and all(sum(k.lower() == n for k, _ in raw) <= 1 for n in
                           (b'host', b'origin', b'x-newsflow-stop', b'content-length'))
                   and hmac.compare_digest(headers.get(b'x-newsflow-stop', '').encode('latin1'),
                                           self.identity.session_nonce.encode('ascii')))
        status = 403
        accepted = False
        if allowed and scope['path'] == '/__bat/stop' and scope['method'] == 'POST':
            status = 409 if self.requested else 202
            accepted = status == 202
            if accepted:
                self.requested = True
        body = json.dumps({'accepted': accepted}).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
        await send({'type': 'http.response.body', 'body': body})
        if accepted:
            self.stop()


class WindowsStop:
    exit_code = None
    def __init__(self, config):
        self.config = config

    def open_owned_session(self, expected):
        import win32api
        if _read_session(self.config.profile) != expected:
            raise Blocked('session-changed')
        handle = win32api.OpenProcess(0x1000 | 0x00100000, False, expected.pid)
        try:
            identity = _identity(handle, expected.pid, expected.installation_id, expected.session_nonce)
            if identity != expected:
                raise Blocked('process-identity-changed')
        except BaseException:
            handle.Close()
            raise
        backend = self
        class Lease:
            def __init__(self):
                self.identity = identity
            def request_graceful_stop(self):
                req = urllib.request.Request(f'http://127.0.0.1:{backend.config.port}/__bat/stop',
                    data=b'', method='POST', headers={'Origin': f'http://127.0.0.1:{backend.config.port}',
                                                       'X-NewsFlow-Stop': expected.session_nonce})
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, *args, **kwargs):
                        return None
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                with opener.open(req, timeout=5) as response:
                    if response.status != 202:
                        raise OSError('graceful-stop-not-accepted')
            def wait_stopped(self, timeout):
                import win32event
                import win32process
                if win32event.WaitForSingleObject(handle, int(timeout * 1000)) != win32event.WAIT_OBJECT_0:
                    return False
                backend.exit_code = win32process.GetExitCodeProcess(handle)
                return True
            def close(self):
                handle.Close()
        return Lease()


def start(config, plan):
    from filelock import FileLock
    from newsflow.config import Settings
    from newsflow.distribution.local_access import LaunchSession, LocalAccess
    import win32api
    lease = prepare_start(plan, WindowsStart())
    marker = config.profile / 'bat-session.private.json'
    bootstrap_file = config.profile / 'browser-launch.private.json'
    clean = False
    phase = 'initialize'
    try:
        with FileLock(str(config.profile / 'desktop.lock')).acquire(timeout=0):
            if marker.exists():
                raise Blocked('owned-session-unresolved-no-retry')
            credential_boundary = None
            if config.profile_kind in {'restored-private-validation', 'restored-local-operation', 'portable-local-operation'}:
                from .restored_install import disable_credential_decryption
                credential_boundary = disable_credential_decryption()
            from newsflow.main import create_app
            adapter = None
            if config.profile_kind == 'synthetic-local-work':
                from .local_work import offline_adapter
                adapter = offline_adapter()
            app = create_app(Settings(data_dir=config.profile, host='127.0.0.1', port=config.port), adapter=adapter, automatic_start=True)
            # No automatic scheduling in validation or newly adopted local operation.
            # Existing reservations/history stay intact; no product scheduler change.
            app.state.scheduler.start = lambda: None
            app.state.publishing_calendar.start = lambda: None
            import uvicorn
            session = LaunchSession(config.port)
            nonce = secrets.token_hex(32)
            handle = win32api.OpenProcess(0x1000 | 0x00100000, False, os.getpid())
            try:
                identity = _identity(handle, os.getpid(), plan.installation_id, nonce)
            finally:
                handle.Close()
            server = uvicorn.Server(uvicorn.Config(None, host='127.0.0.1', port=config.port,
                log_level='warning', access_log=False, loop='newsflow.runtime:windows_server_loop'))
            if config.profile_kind == 'restored-private-validation':
                from .restored_install import RestoredRequests
                request_boundary = RestoredRequests(LocalAccess(app, session))
            elif config.profile_kind in {'restored-local-operation', 'portable-local-operation'}:
                from .operation import OperatingRequests
                request_boundary = OperatingRequests(LocalAccess(app, session))
            elif config.profile_kind == 'synthetic-local-work':
                from .local_work import LocalWorkRequests
                request_boundary = LocalWorkRequests(LocalAccess(app, session))
            else:
                request_boundary = SyntheticRequests(LocalAccess(app, session))
            protected = Control(request_boundary, identity, session.origin,
                                lambda: setattr(server, 'should_exit', True))
            server.config.app = protected
            _atomic(marker, {'pid': identity.pid, 'creation_id': identity.creation_id,
                'owner_sid': identity.owner_sid, 'executable': str(identity.executable),
                'installation_id': identity.installation_id, 'session_nonce': identity.session_nonce})
            _atomic(bootstrap_file, {'url': session.launch_url()})
            def ready():
                while not server.started and not server.should_exit:
                    time.sleep(.05)
                if server.started:
                    print(f'READY: http://127.0.0.1:{config.port}/studio/dashboard (local authentication required)', flush=True)
                    if config.open_browser:
                        import webbrowser
                        opened = bool(webbrowser.open(session.launch_url(), new=1))
                        _atomic(config.profile / 'browser-open-result.json', {'requested': True, 'accepted': opened})
            thread = threading.Thread(target=ready, daemon=True)
            thread.start()
            phase = 'serve'
            try:
                server.run(sockets=[lease.socket])
                clean = server.started and protected.requested
            finally:
                server.should_exit = True
                thread.join(timeout=2)
            if not clean:
                raise Blocked('shutdown-result-not-confirmed')
            _atomic(config.profile / 'last-exit.json', {'result': 'STOPPED', 'exitCode': 0,
                                                     'installationId': plan.installation_id,
                                                     'credentialBoundary': credential_boundary})
            marker.unlink()
            bootstrap_file.unlink(missing_ok=True)
            print('STOPPED: owned session closed normally; exit=0.', flush=True)
            return 0
    except BaseException as error:
        # Cancellation/failure is not converted into a successful stop.
        _atomic(config.profile / 'last-exit.json', {'result': 'FAILED_OR_UNKNOWN', 'exitCode': 1,
            'phase': phase, 'errorType': type(error).__name__, 'installationId': plan.installation_id})
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            return 1
        raise
    finally:
        lease.close()


def dispatch(action, root):
    config = load_config(root)
    bootstrap(config)
    sid = _profile(config, create=action == 'start')
    plan = start_plan(config.program, config.profile, config.port, sid, config.installation_id)
    if action == 'start':
        return start(config, plan)
    expected = _read_session(config.profile)
    backend = WindowsStop(config)
    result = stop_owned(plan, expected, backend, timeout=20)
    if result == 'STOPPED' and backend.exit_code == 0:
        print('STOPPED: owned process exited with code 0.', flush=True)
        return 0
    print('UNKNOWN_OR_FAILED: no force termination or automatic retry.', file=sys.stderr)
    return 3
