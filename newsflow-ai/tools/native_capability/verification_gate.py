"""Verification-only gate. Never imported by the product or existing host Guard.

Trusted Python harness, not an OS sandbox against arbitrary Python reflection.
No application, provider, DPAPI, subprocess or network capability is granted.
"""
from __future__ import annotations
import contextlib
import ctypes
import hashlib
import ntpath
import os
from pathlib import Path
import sys
import threading
import uuid

class Denied(PermissionError):
    pass

SYMBOLS = {
    "ntdll.dll": frozenset({"NtCreateFile", "RtlNtStatusToDosError"}),
    "kernel32.dll": frozenset({"CreateFileW", "CloseHandle",
        "GetFileInformationByHandle", "GetFinalPathNameByHandleW",
        "LockFileEx", "UnlockFileEx"}),
}

def dos_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise Denied("invalid-path")
    if value.startswith(("\\\\", "\\", "/")) or "/" in value:
        raise Denied("UNC-device-or-ambiguous-path")
    drive, tail = ntpath.splitdrive(value)
    if len(drive) != 2 or not drive[0].isascii() or not drive[0].isalpha() or drive[1] != ":" or not tail.startswith("\\"):
        raise Denied("absolute-local-drive-required")
    if ":" in tail:
        raise Denied("ADS")
    parts = tail[1:].split("\\") if tail != "\\" else []
    for part in parts:
        base = part.split(".")[0].upper()
        if (not part or part in (".", "..") or part.endswith((" ", ".")) or
            any(c in part for c in '<>"|?*') or any(ord(c) < 32 for c in part) or
            base in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or
            (len(base) == 4 and base[:3] in {"COM", "LPT"} and base[3].isdigit())):
            raise Denied("ambiguous-or-reserved-component")
    return ntpath.normcase(ntpath.normpath(value))

def within(path, root):
    try:
        return ntpath.commonpath((path, root)) == root
    except ValueError:
        return False

class Grant:
    __slots__ = ("root",)
    def __init__(self, root):
        self.root = root

class VerificationGate:
    def __init__(self, workspace: Path, source: Path):
        if os.name != "nt" or sys.version_info[:3] != (3, 14, 7):
            raise Denied("Windows-Python-3.14.7-required")
        self.workspace = dos_path(str(workspace))
        self.source = dos_path(str(source))
        self.read_roots = (self.workspace, self.source, dos_path(sys.base_prefix),
                           dos_path(sys.prefix))
        self.system32 = dos_path(str(Path(os.environ["SystemRoot"]) / "System32"))
        self.grants = {}
        self.installed = False
        self.binding = threading.local()
        self.bound = False
        self.native_hashes = {}
        self.denials = {}
        self.events = []
    def deny(self, reason):
        self.denials[reason] = self.denials.get(reason, 0) + 1
        raise Denied(reason)
    def install(self):
        if self.installed:
            self.deny("gate-already-installed")
        sys.addaudithook(self.audit)
        self.installed = True
        self.events.append("gate-installed-before-adapter-import-and-DLL-binding")
    def new_scope(self):
        if not self.installed:
            self.deny("guard-first-required")
        root = Path(self.workspace) / ("scope-" + uuid.uuid4().hex)
        root.mkdir()
        grant = Grant(dos_path(str(root)))
        self.grants[grant] = (grant.root, False)
        return grant
    def claim(self, grant):
        if type(grant) is not Grant or grant not in self.grants or self.grants[grant][1]:
            self.deny("foreign-or-consumed-scope-grant")
        root, _ = self.grants[grant]
        if grant.root != root:
            self.deny("scope-grant-path-tampered")
        self.grants[grant] = (root, True)
        return root
    @contextlib.contextmanager
    def _binding_only(self):
        if not self.installed or self.bound or getattr(self.binding, "active", False):
            self.deny("native-binding-not-authorized")
        self.bound = True
        self.binding.active = True
        try:
            yield
        finally:
            self.binding.active = False
    def audit(self, event, args):
        if event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg",
                     "socket.getaddrinfo", "subprocess.Popen", "_winapi.CreateProcess",
                     "os.system", "os.startfile", "os.startfile/2", "os.exec",
                     "os.posix_spawn", "os.spawn"}:
            self.deny("network-or-process-denied:" + event)
        if event == "ctypes.dlopen":
            if not getattr(self.binding, "active", False):
                self.deny("raw-DLL-denied")
            path = dos_path(str(args[0]))
            name = ntpath.basename(path)
            if name not in SYMBOLS or ntpath.dirname(path) != self.system32:
                self.deny("unapproved-DLL")
        if event in {"ctypes.dlsym", "ctypes.dlsym/handle"}:
            name = args[1]
            library = getattr(args[0], "_name", "")
            if (not getattr(self.binding, "active", False) or
                dos_path(str(library)) != ntpath.join(self.system32, ntpath.basename(str(library))) or
                name not in SYMBOLS.get(ntpath.basename(str(library)).lower(), ())):
                self.deny("unapproved-native-symbol")
        if event in {"ctypes.string_at", "ctypes.wstring_at", "ctypes.memoryview_at", "ctypes.call_function"}:
            self.deny("arbitrary-native-memory-or-call")
        if event in {"sqlite3.enable_load_extension", "sqlite3.load_extension"}:
            self.deny("SQLite-extension-denied")
        if event == "sqlite3.connect" and args[0] != ":memory:":
            self.deny("SQLite-not-needed-in-native-verification")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = dos_path(os.fsdecode(os.path.abspath(args[0])))
            mode, flags = args[1] or "", args[2] or 0
            write = any(c in str(mode) for c in "wax+") or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if write and not within(path, self.workspace):
                self.deny("write-outside-synthetic-workspace")
            if not write and not any(within(path, r) for r in self.read_roots + (self.system32,)):
                self.deny("read-outside-verification-roots")
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime",
                     "os.rename", "os.link", "os.symlink"}:
            values = args[:2] if event in {"os.rename", "os.link", "os.symlink"} else args[:1]
            for value in values:
                if isinstance(value, (str, bytes, os.PathLike)):
                    path = dos_path(os.fsdecode(os.path.abspath(value)))
                    if not within(path, self.workspace):
                        self.deny("mutation-outside-synthetic-workspace")
    def dll_path(self, name):
        path = Path(self.system32) / name
        self.native_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return str(path)
