"""Separate packaged desktop entry. Never used by the existing operating entry."""
from pathlib import Path
import os
import signal
import sys
import threading
import webbrowser

from .local_access import LaunchSession, LocalAccess
from .windows_profile import distribution_profile, reserve_user_socket


def run():
    if sys.platform != 'win32':
        raise SystemExit('Windows desktop only')
    root = distribution_profile(Path(os.environ.get('LOCALAPPDATA','')))
    from filelock import FileLock
    from newsflow.config import Settings
    from newsflow.paths import prepare_data_dir
    import uvicorn
    with FileLock(str(root/'desktop.lock')).acquire(timeout=0), reserve_user_socket() as listener:
        prepare_data_dir(root)
        session = LaunchSession(listener.getsockname()[1])
        from newsflow.main import create_app
        app = create_app(Settings(data_dir=root,port=session.port))
        protected = LocalAccess(app,session)
        server = uvicorn.Server(uvicorn.Config(protected,host='127.0.0.1',port=session.port,
            log_level='warning',access_log=False,loop='newsflow.runtime:windows_server_loop'))
        # Only hand the fragment to the current user's browser after HTTP is ready.
        def open_ready():
            while not server.started and not server.should_exit:
                threading.Event().wait(.05)
            if server.started:
                webbrowser.open(session.launch_url(),new=1)
        opener = threading.Thread(target=open_ready,daemon=True)
        opener.start()
        previous = signal.signal(signal.SIGBREAK,signal.default_int_handler)
        try:
            server.run(sockets=[listener])
        finally:
            server.should_exit = True
            signal.signal(signal.SIGBREAK,previous)
            opener.join(timeout=1)
