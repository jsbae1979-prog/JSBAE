"""Frozen private launcher/updater. Unsigned updates cannot reach transactions."""
import json
import os
from pathlib import Path
import subprocess
import sys


def notify(message):
    # Fixed nonsecret status only; never exception details or paths containing keys.
    print(message)
    if os.name == 'nt' and sys.stdout is None:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'NewsFlow AI', 0x40)


def main():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise SystemExit('Packaged Windows private entry only')
    from newsflow.distribution.offline import OfflineInstall, OfflineBlocked, payload_check
    from newsflow.distribution.windows_profile import distribution_profile, private_directory, unlinked
    from newsflow.distribution.updates import publisher_matches, authenticode
    bundle = Path(sys._MEIPASS)
    configuration = json.loads((bundle / 'private-mode.json').read_bytes())
    mode = configuration['mode']
    local = unlinked(Path(os.environ['LOCALAPPDATA']))
    args = sys.argv[1:]
    if mode == 'update':
        # Even --help/--recover must not turn this unsigned file into an updater.
        trust = json.loads((bundle / 'publisher-trust.json').read_bytes())
        if trust.get('updatesEnabled') is not True:
            raise OfflineBlocked('Publisher certificate unavailable; update is blocked.')
        publisher_matches(Path(sys.executable), trust.get('publisherCertificateSha256', ''), authenticode)
        if args:
            raise OfflineBlocked('Unsupported update argument')
        root = unlinked(local / 'Programs/NewsFlowAI-Private')
        if not (root / 'current.json').is_file():
            raise OfflineBlocked('Private installation not found')
        import winreg
        registration = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NewsFlowAI-PrivateOffline-v1_is1'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration) as key:
            installed_at = Path(winreg.QueryValueEx(key, 'InstallLocation')[0]).absolute()
        if unlinked(installed_at) != root:
            raise OfflineBlocked('Private installation registration mismatch')
        manifest = json.loads((bundle / 'release.json').read_bytes())
        if manifest.get('source') != configuration.get('productSource'):
            raise OfflineBlocked('Migration helper and application source mismatch')
        payload = bundle / 'payload'
        payload_check(payload, manifest)
        install = OfflineInstall(root, distribution_profile(local))
        def health(slot):
            # Current-user profile remains locked by this process. This helper
            # and payload contain the same pinned source/migration revision.
            from newsflow.db.session import make_engine, migrate
            engine = make_engine(install.profile / 'newsflow.db')
            try:
                migrate(engine)
                with engine.connect() as connection:
                    if connection.exec_driver_sql('PRAGMA integrity_check').scalar() != 'ok':
                        raise OfflineBlocked('Database migration integrity failed')
            finally:
                engine.dispose()
            child = subprocess.run([str(slot / 'NewsFlowAI-Candidate.exe'), '--offline-runtime-check'],
                                   cwd=slot, capture_output=True, timeout=90)
            if child.returncode:
                raise OfflineBlocked('New version preflight/migration failed; restoring backup.')
        install.update_verified(payload, manifest, health)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, manifest['version'])
        except OSError:
            notify('Update applied. Windows app-list version needs repair; do not reapply this update.')
            raise SystemExit(3)
        notify('Offline update complete. Open NewsFlow AI normally. Backup retained.')
        return
    if mode != 'launcher':
        raise OfflineBlocked('Invalid packaged mode')
    default = local / 'Programs/NewsFlowAI-Private'
    if args and args[0] in ('--prepare-install', '--finalize-install'):
        if len(args) != 2:
            raise OfflineBlocked('Installer arguments required')
        root = unlinked(Path(args[1]).absolute())
        # Installer cannot adopt the operating tree or arbitrary machine paths.
        if root != default:
            raise OfflineBlocked('Use the current-user private installation directory.')
        if args[0] == '--prepare-install':
            if root.exists():
                raise OfflineBlocked('Existing directory: use a signed update.')
            if not root.parent.exists():
                private_directory(root.parent)
            private_directory(root)
            private_directory(root / 'slots')
            profile = distribution_profile(local)
            private_directory(profile / 'update-backups')
            return
        manifest = json.loads((root / 'initial-release.json').read_bytes())
        OfflineInstall(root, distribution_profile(local)).finalize_preinstalled(manifest)
        return
    root = unlinked(Path(sys.executable).parent)
    if root != default:
        raise OfflineBlocked('Private launcher location mismatch')
    install = OfflineInstall(root, distribution_profile(local))
    if args == ['--uninstall-programs']:
        install.remove_installed_programs()
        return
    if args == ['--recover-update']:
        install.recover()
        notify('Previous version and backed-up data restored. No update was retried.')
        return
    if args not in ([], ['--no-browser']):
        raise OfflineBlocked('Unsupported launcher argument')
    # Prevent concurrent update until the selected product has fully exited.
    from filelock import FileLock
    with FileLock(str(root / 'install.lock')).acquire(timeout=0):
        executable = install.active_executable()
        child = subprocess.Popen([str(executable), *args], cwd=executable.parent)
        try:
            code = child.wait()
        except KeyboardInterrupt:
            # CTRL_BREAK reaches the owned child in the same console group.
            # Wait for its normal lifespan cleanup; never force-kill it.
            code = child.wait(timeout=15)
        if code:
            raise OfflineBlocked('Application stopped with an error. Preserve data and inspect privately.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # No provider credentials, paths, SQL or certificate details in UI/log.
        notify('NewsFlow AI could not continue. Updates require a trusted publisher signature; close the app normally before updating. Incomplete updates require explicit recovery.')
        raise SystemExit(2)
