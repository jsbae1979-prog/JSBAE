# Reboot / continuation checkpoint

- Branch: `codex/newsflow-core-studios-rebuild-20261027`
- Baseline: `20ed36fb66d515ab36d19eccfb28c1a6de6c6924` (previous approved UI branch preserved).
- Initial implementation: `68db1cb995e6c0ac3aa2892bf3c9131ac6a26c8d`.
- Final product code: `f398c61ea0d42d30f11563d225a53922e28ac8ab`.
- Design reference: `17b81fab2325c4f1757a9e4d8cf88bd287719e4c` on the design document branch.
- Do not reset, clean, stash, merge, create PRs, alter PR #35, or start/stop the operating app.
- No real keys or operating files belong in this branch. `validation/` remains private/untracked.
- React browser evidence uses synthetic route fulfillment at 18765 with the existing pinned Node boundary and an owned Windows Job. No local full Python application was launched.
- New code is in `frontend/src/studio/core`; protected legacy Workbench body remains identical. Legacy form submission/approval and TOP3 state machine are reused.
- Continue only after user review. This checkpoint does not authorize operation, actual AI generation, SNS or deployment.
