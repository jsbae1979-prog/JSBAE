# NewsFlow AI development rules

- Phase 4B-1 OFFLINE/BLOCKED OAuth foundation is authorized. Do not log in to real SNS accounts, exchange real codes/tokens, store real service credentials, upload/publish, begin Phase 4B-2, or merge main without explicit user approval. Windows vault validation uses recognizable synthetic tokens only.
- Python 3.12; production target is Windows 11 only. Codex Cloud is for development/tests; no Linux deployment, Docker, or WSL features.
- Keep GUI, services, persistence, and external adapters separate.
- Never commit API keys, OAuth tokens, personal data, local databases, or session secrets.
- No article body scraping, login/paywall bypass, or actual SNS publishing.
- Default to fixture/fake-adapter tests. Live RSS tests must be opt-in.
- Preserve unknown publication dates and unassessed score components.
- Run `python -m pytest -q -rs`; distinguish tests from real network/browser/OS validation.
- Every cloud task is already isolated. Use this checkout; do not create a worktree unless requested.
