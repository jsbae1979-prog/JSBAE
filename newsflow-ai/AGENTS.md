# NewsFlow AI development rules

- Phase 1 only. Do not begin Phase 2 without explicit user approval.
- Python 3.12; support Windows 11 and Ubuntu 24.04.
- Keep GUI, services, persistence, and external adapters separate.
- Never commit API keys, OAuth tokens, personal data, local databases, or session secrets.
- No article body scraping, login/paywall bypass, or actual SNS publishing.
- Default to fixture/fake-adapter tests. Live RSS tests must be opt-in.
- Preserve unknown publication dates and unassessed score components.
- Run `python -m pytest -q -rs`; distinguish tests from real network/browser/OS validation.
- Every cloud task is already isolated. Use this checkout; do not create a worktree unless requested.
