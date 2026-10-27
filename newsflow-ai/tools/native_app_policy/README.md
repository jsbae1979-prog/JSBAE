# Bounded Windows app initialization (verification only)

Windows CI / Python 3.14.7 only. Operating Guard, package and product are unchanged.
Reuses the Guard copy, Rtl/CRT bridge and native bindings; global DLL tables do not expand.
App policy grants only synthetic paths, two registered SQLite DBs, owned IPv4 loopback probes and source-bound AnyIO read-only I/O threads (max 2). All processes, scheduled workers, DNS, internet and credentials remain denied.
Actual create_app uses explicit synthetic Settings and Fake RSS, automatic_start=True. No lifespan/server/production run entry is entered. Read-only ASGI requests test Python responses and React asset delivery, not browser execution.
No installed dependency is imported early to avoid Guard. An unapproved native request stops and records BLOCKED.
Existing 28/39/32/29 and 7/59/42 evidence is reused, not replayed.
This is a trusted CI harness, not hostile-Python OS isolation. App operation, Windows 11 GUI and OS DPI are not certified.
