# Windows integration checkpoint

- Branch: codex/newsflow-core-studios-rebuild-20261027
- Baseline: ebe163e9c61e478af2a99e3e1352bf9cda6b45cf
- Tested product: dcf7c0dfca79b911c2e84ed9bf3fe0f8090a90ad
- New real-application route tests: Windows run 40497641341, 7 passed.
- Automatically repeated focused workflow: Windows run 40497641175, 59 passed.
- Character scene binding: status -> state only. Focused synthetic Chrome failure and pass retained.
- Existing local validation/ and original reports retained; no reset/clean/stash.
- Local full Python app remains blocked; do not pre-import modules, reorder native initialization or bypass Guard. OS DPI remains not verified.
- Do not stop/restart operating app, alter its data or keys, merge PR #35/main, publish or call paid APIs.
- Await user review before further work.
