# Windows 11 local synthetic validation runner

Status: **BLOCKED for GUI acceptance**. No approved server run is presently certified.

This is a separate entry point, not the CI-only runner with a disabled check.
It uses the unchanged verification Guard, native adapter, Rtl/filelock boundary
and gate via source-pinned copies. Production Guard and product code are untouched.
No `GITHUB_ACTIONS` value is created. The child receives a minimal new environment.

The policy is a trusted Python verification harness, **not OS isolation against
hostile Python reflection**. It provides one owned IPv4 HTTP listener on
127.0.0.1:18765; outgoing connections/DNS, shell/child workers and real providers
are denied. All writes/SQLite reside in a fresh synthetic profile. Source,
packaged samples, built React files and fixed runtime folders are read only.
No real credentials, proxy settings, OAuth or DPAPI files are inherited.
The product `create_app`, CSRF/Origin middleware and FileResponse/Range are used.
ASGI lifespan and scheduler/background startup are deliberately not entered.
The HTTP surface limits writes to local draft/sample actions and rejects paid
generation, OAuth, account changes, scheduling activation and publishing.

## Latest attempt

One real local attempt returned from create_app but recorded two out-of-root
read rejections and one link-creation rejection during initialization. Libraries
caught those exceptions. The initial harness incorrectly printed READY before
checking the accumulated policy rejection flag. The loop exited without accepting
any request, all resources closed, and the recorded final result was BLOCKED.
The early READY line is **not evidence of a permitted GUI session**.

The corrected code checks all accumulated Guard/gate/policy rejections immediately
after create_app and before seeding/serving. Two focused tests cover caught-error
and returned-initializer cases. It also records call-site frames for future
diagnostics, without logging input values or secret contents. **The corrected
app entry has not been rerun**; no read/link grant has been added after rejection.

Native FileLock ownership remains tied to the original thread. Future sync-route
locks from AnyIO workers may therefore still be rejected. Nested character locks
and other unregistered lock paths remain unsupported; no lockless substitution
or cross-thread ownership grant is made. Fake image/video generation is not
implemented by this runner, and no paid production route is enabled as a fallback.

## Focused contracts

From this directory, using the approved Windows Python 3.14.7:

```powershell
python -B -m unittest test_local_policy -v
```

This executes pure synthetic policy tests, without app/native/network execution.
Do not use another Python version or set CI variables to satisfy a check.

## Future execution, only after the remaining boundary is resolved

```powershell
<approved-python-3.14.7> -B launch.py --workspace <new-ordinary-synthetic-directory>
```

The directory must not exist. The owning parent retains exactly one child handle;
normal stop is an empty `STOP` file in that owned synthetic profile. The child
closes the server, app services, SQLite connections, event loop and native objects.
An exceptional forced cleanup is separately recorded and never counted as a
normal shutdown. Do not terminate processes by port/name, reuse the operating
profile, relax Guard, pre-import filelock or substitute another executable.

Current evidence: `docs/reports/windows11-local-runner-20261028/`.
The 12-screen GUI, HTTP sample playback and actual monitor DPI remain unverified.
