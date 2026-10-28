"""Path, fixed-port reservation and owned graceful-stop contracts.

Backends are injected capabilities. This module has no subprocess, shell,
network, native-process or application-start implementation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from newsflow.distribution.windows_profile import unlinked


class Blocked(ValueError):
    """A public, non-sensitive reason code; never include native exception text."""


def ordinary_absolute(value: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise Blocked('absolute-local-path-required')
    if '..' in path.parts or any(':' in part or any(ord(c) < 32 for c in part) for part in path.parts[1:]):
        raise Blocked('parent-or-stream-path-refused')
    try:
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise Blocked('linked-or-unavailable-path')
        return unlinked(path)
    except (OSError, ValueError):
        raise Blocked('linked-or-unavailable-path') from None


def separated(program: Path, profile: Path) -> tuple[Path, Path]:
    program, profile = ordinary_absolute(program), ordinary_absolute(profile)
    if program == profile or program.is_relative_to(profile) or profile.is_relative_to(program):
        raise Blocked('program-profile-overlap')
    if not program.is_dir():
        raise Blocked('program-root-missing')
    if profile.exists() and not profile.is_dir():
        raise Blocked('profile-directory-required')
    return program, profile


def fixed_port(value: int) -> int:
    if type(value) is not int or not 1024 <= value <= 65535 or value == 8765:
        raise Blocked('invalid-or-operating-port')
    return value


@dataclass(frozen=True)
class StartPlan:
    program: Path
    profile: Path
    port: int
    owner_sid: str
    installation_id: str
    host: str = field(default='127.0.0.1', init=False)


def start_plan(program: Path, profile: Path, port: int, owner_sid: str, installation_id: str) -> StartPlan:
    program, profile = separated(program, profile)
    if not re.fullmatch(r'S-1-(?:\d+-)+\d+', owner_sid):
        raise Blocked('owner-identity-required')
    if not re.fullmatch('[0-9a-f]{32}', installation_id):
        raise Blocked('installation-identity-required')
    return StartPlan(program, profile, fixed_port(port), owner_sid, installation_id)


def inspect_layout(plan: StartPlan) -> None:
    """Inspect bytes only. Metadata is not proof of a runnable Python install."""
    file = ordinary_absolute(plan.program / 'app/layout.json')
    if not file.is_file() or file.stat().st_size > 2 * 1024 * 1024:
        raise Blocked('runtime-layout-missing')
    try:
        layout = json.loads(file.read_bytes())
        required = {
            'app/runtime/python.exe', 'app/runtime/python314.dll',
            'app/frontend/dist/index.html', 'tools/ffmpeg.exe', 'tools/ffprobe.exe',
        }
        if (type(layout['schemaVersion']) is not int or layout['schemaVersion'] != 1 or layout['pythonVersion'] != '3.14.7'
                or layout['architecture'] != 'AMD64' or not isinstance(layout['files'], list)
                or len(layout['files']) > 20000):
            raise Blocked('runtime-layout-incompatible')
        from .zip_update import payload_name
        seen = set()
        for row in layout['files']:
            name = payload_name(row['path'])
            if name.casefold() in seen:
                raise Blocked('duplicate-runtime-file')
            seen.add(name.casefold())
            target = ordinary_absolute(plan.program / name)
            if (type(row['bytes']) is not int or row['bytes'] < 0
                    or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                    or not target.is_file() or target.stat().st_size != row['bytes']
                    or hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']):
                raise Blocked('runtime-file-mismatch')
            required.discard(name)
        if required:
            raise Blocked('required-runtime-file-missing')
    except (KeyError, TypeError, OSError, ValueError) as error:
        if isinstance(error, Blocked):
            raise
        raise Blocked('invalid-runtime-layout') from None


class PortLease(Protocol):
    host: str
    port: int

    def close(self) -> None: ...


class StartBackend(Protocol):
    def check_private_profile(self, path: Path, owner_sid: str) -> None: ...
    def reserve_exclusive(self, host: str, port: int) -> PortLease: ...


def prepare_start(plan: StartPlan, backend: StartBackend) -> PortLease:
    """Reserve exactly one port; return its still-held lease, never start app."""
    # Revalidate paths instead of trusting a caller-created dataclass.
    expected = start_plan(plan.program, plan.profile, plan.port, plan.owner_sid, plan.installation_id)
    if plan != expected:
        raise Blocked('changed-start-plan')
    inspect_layout(plan)
    backend.check_private_profile(plan.profile, plan.owner_sid)
    try:
        lease = backend.reserve_exclusive(plan.host, plan.port)
    except OSError:
        raise Blocked('port-unavailable-no-fallback') from None
    if lease.host != plan.host or lease.port != plan.port:
        lease.close()
        raise Blocked('port-reservation-mismatch')
    return lease


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation_id: str
    owner_sid: str
    executable: Path
    installation_id: str
    session_nonce: str = field(repr=False)


class OwnedProcessLease(Protocol):
    """Identity, request and wait must refer to the same retained OS handle."""
    identity: ProcessIdentity
    def request_graceful_stop(self) -> None: ...
    def wait_stopped(self, timeout: float) -> bool: ...
    def close(self) -> None: ...


class StopBackend(Protocol):
    def open_owned_session(self, expected: ProcessIdentity) -> OwnedProcessLease: ...


def stop_owned(plan: StartPlan, expected: ProcessIdentity, backend: StopBackend, *, timeout: float = 15) -> str:
    """No PID-name enumeration, force-kill or retry; backend has no kill API."""
    if plan != start_plan(plan.program, plan.profile, plan.port, plan.owner_sid, plan.installation_id):
        raise Blocked('changed-start-plan')
    if (type(expected.pid) is not int or expected.pid <= 0
            or not isinstance(expected.creation_id, str) or not 0 < len(expected.creation_id) <= 128
            or expected.owner_sid != plan.owner_sid or expected.installation_id != plan.installation_id
            or not re.fullmatch('[0-9a-f]{64}', expected.session_nonce)
            or ordinary_absolute(expected.executable) != plan.program / 'app/runtime/python.exe'
            or type(timeout) not in (int, float) or not 0 < timeout <= 30):
        raise Blocked('not-owned-session')
    lease = backend.open_owned_session(expected)
    try:
        if lease.identity != expected:
            raise Blocked('process-identity-changed')
        try:
            lease.request_graceful_stop()
            return 'STOPPED' if lease.wait_stopped(timeout) is True else 'UNKNOWN_NO_RETRY'
        except (TimeoutError, OSError):
            return 'UNKNOWN_NO_RETRY'
    finally:
        lease.close()
