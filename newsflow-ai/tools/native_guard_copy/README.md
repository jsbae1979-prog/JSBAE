# Verification Guard copy + native/CRT boundary

This folder is CI-only and is not connected to a NewsFlow product entry point.
It never imports the operating Guard, changes installed filelock or starts an app.

guard_original.py is an exact byte copy of the reviewed original Guard.
guard_verification.py preserves every existing module statement and function;
only an early capability dispatch in audit and a private binding dispatch in
_guarded_windll are inserted. Single-use registration helpers are appended.
GUARD_COPY_PROVENANCE.json and guard_copy.patch describe the exact delta.
The global DLL/symbol tables are unchanged.

The unchanged native_boundary dependency is staged only because the original
Guard installer requires it. Its launch paths/configuration are not activated.
No child bootstrap, preimport or application code in its string constants runs.

The CI launcher writes synthetic configuration into a fresh temporary directory,
installs the actual Guard copy first, installs the existing capability gate,
registers a source-pinned provider and only then binds the unchanged native adapter.
The provider delegates only its reviewed fixed binding context and exact DLL hash
reads. It never adds NTDLL to a general allowlist. Raw public DLL/CRT calls still deny.

descriptor_boundary.py privately transfers newly owned test-file handles to the
CRT via open_osfhandle. After successful transfer the CRT owns them; os.close,
never native CloseHandle, closes those descriptors. Borrowed native handles are
validated against the registered fd, final path and file ID. No raw fd/handle
is returned publicly. Unexpected unprovable transfer/close outcomes are
quarantined and block success rather than guessing ownership or replaying.

Prepared path buffers are Python-owned, registered one-component relative names,
kept alive across synchronous NtCreateFile and protected against in-use/double
release. This is NOT RtlDosPathNameToNtPathName_U_WithStatus allocation/free
compatibility. Native Rtl conversion/free remains BLOCKED. Upstream unmodified
filelock import is attempted once AFTER both Guards in a negative probe and
must still fail closed; it is not preloaded or represented as runtime success.

The trust model is reviewed Python harness code, not hostile Python reflection
or a process/OS sandbox. Existing 39/32 PASS is reused; this CI runs only new
copy/CRT/buffer tests and two selected reparse/final-path boundary checks.
