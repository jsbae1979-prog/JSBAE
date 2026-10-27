Step13G.10-B Windows Fake browser validation checkpoint
Python3.14.7 only. Development/test tools; never imported by product startup.
Original media/file/SQLite/network Guard stays installed. Pinned Node run-driver and pinned headless Chrome only. No shell or global Guard override. Real sockets:127.0.0.1:18765 only;8765 forbidden.
Existing TestClient route.fulfill fixtures use a virtual127 origin without a port; continue/fallback/default route still deny real connections to that origin.
No real provider keys, OAuth data, user DB or media are included.
Machine-local guard-config-private.json,node-config-private.json,runtime-config-private.json are deliberately excluded. Keep them in the local diagnostic directory; never commit them.
Resume after reboot: verify operating app remains stopped and8765 free; revalidate pinned runtime hashes and synthetic profile paths; read the local phase supervisor/pytest.xml and resume only incomplete phases. Do not resume live provider or publish requests.
The91 original IDs are exact; no tests skipped/xfail-ed or removed. Existing acceptedG2-G9 source/test changes are preserved on the checkpoint branch, based on645c4b7. This step changes no product source.
Chrome background traffic is not proven completely blocked by OS policy. Playwright routes, Node boundary, proxy/resolver flags are defense in depth, not a complete OS isolation claim.
Status:15 routes at3 widths PASS; remaining90 and full regression in progress. This is not an operating deployment or Windows EXE release.
