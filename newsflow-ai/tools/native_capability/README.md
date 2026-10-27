# Verification-only native lock capability

This directory is not imported by NewsFlow. The existing host Guard, filelock
package and product startup are unchanged. Run only through the dedicated
Windows CI workflow with Python 3.14.7; never spoof a CI flag on the host.

## Trust and capability boundary
This API protects a trusted verification harness from accidental overreach.
It is not an OS sandbox against hostile Python reflection or compromised code.
The separate test gate is installed before adapter import and native binding;
it never replaces or modifies the operating Guard. No app, DPAPI, provider,
process, network/DNS or non-memory SQLite capability is granted.

A one-use grant names a fresh random synthetic directory. Only newly created
direct-child ASCII .lock files can be registered. No arbitrary content IO,
pre-existing file, nested path, caller NT path, pointer, access mask or raw
handle is accepted. The drive and every directory component are pinned by
metadata/traversal handles without delete sharing, then verified by actual
final path and reparse attributes. The final file is opened relative to the
pinned directory. Its volume/file ID, single hard link and empty size are
checked. This avoids creating a file through an intermediate junction before
post-open validation. Supporting ancestry metadata opens are not general
file-content access.

Locks are real synchronous exclusive LockFileEx locks: one byte, offset zero,
fail-immediately plus bounded polling (0–2 seconds). LockTimeout differs from
NativeFailure. Ownership/state changes only after OS success. Explicit release
and close act only on live registered capabilities and remain possible for
cleanup if path metadata has subsequently changed. Owner-thread enforcement,
closed/foreign/forged token rejection and no implicit reentrancy are intentional.
There is no lock-free fallback, stale-owner breaking, package monkey patch or
claim of full filelock compatibility.

| Call | Policy |
|---|---|
| NtCreateFile | Private fixed ABI; one validated component relative to owned directory |
| RtlNtStatusToDosError | Private bounded scalar conversion |
| GetFileInformationByHandle | Private owned ancestry/file handles only |
| LockFileEx / UnlockFileEx | Owned file, fixed exclusive one-byte range |
| RtlDosPathNameToNtPathName_U_WithStatus | BLOCKED; relative name needs no conversion |
| RtlFreeUnicodeString | BLOCKED; Python owns buffers, no native allocation/free |
| OpenProcess / GetProcessTimes | BLOCKED; necessity not established |
| CreateFileW / GetFinalPathNameByHandleW / CloseHandle | Private supporting fixed bindings for metadata bootstrap, validation and owned cleanup |
| Other DLL/symbol | BLOCKED |

Unknown PIDs/owners are never inspected, unlocked or terminated. Separately
opened handles contend under Windows even in the same process; no child is needed.

## Evidence and limitations
The standalone runner records individual failures, source/DLL hashes, denial
counts and cleanup. Junction targets and outside-root negative files are all
synthetic. Missing prerequisites fail rather than adding skip/xfail.
Trusted fault injection tests path/ID mismatch and unlock/close failure state.

CI success does not authorize local full-app startup or filelock integration,
prove Windows 11 host compatibility or verify OS DPI. Those remain separate.

Sources:
- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
- [LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)
- [GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)
