# Real Rtl ownership + unchanged filelock (verification only)

Windows CI / Python 3.14.7 only. No host app, DPI, operating data or provider call.

The existing Guard copy and original native adapter are reused unchanged.
A new copy of verification_gate adds only instance-owned, once-only binding of
RtlDosPathNameToNtPathName_U_WithStatus and RtlFreeUnicodeString, plus exact
thread/address/length reads of ledger-owned native output. Its global SYMBOLS
table and all file/network/process/database restrictions are preserved.

guard_capability supplies filelock's reviewed module imports with fixed Python
native-call facades, not a raw DLL. Package argument metadata cannot change the
real ABI. Calls require the unchanged package's source-attested function frame
and Python-owned output containers; caller pointers are not passed blindly.
Process symbols may be declared at import but always deny execution.

rtl_boundary uses actual Rtl allocation/free and NtCreateFile. It records the
native allocation separately from the caller's Python structure, validates
converted NT bytes, pins ancestors and a registered anchor, then checks the real
opened handle path/file ID/reparse state. Arbitrary/foreign/double/in-use frees
deny before native free. Unknown ownership stays quarantined and cannot pass
cleanup. Normal CRT ownership transfers are captured by verification-only
msvcrt/os.close wrappers; package classes and methods are not replaced.

The FileLock tests use the actually installed filelock 3.32.7. Complete source
hashes and key method code identities are checked before/after. A successful
guarded facade call is a real native call, not a Fake lock. The package itself
is never preimported, rewritten, copied into another namespace or downgraded.

Limits are explicit: registered fresh test paths, finite acquisition timeouts,
same-thread use, no descriptor callbacks/lifetime/process owner recovery.
A retained anchor prevents default unlink while registered; upstream's real
unlink attempt and allowed Windows persistence are observed, not replaced.
Successful deletion without the anchor and all package variants are not
claimed. This remains trusted-harness isolation, not an OS sandbox against
hostile Python reflection.

CI runs 25 new cases and 2 selected prior path checks; previous 39/32/29
evidence is reused rather than repeated wholesale. Full app is never started.
