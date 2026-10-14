"""Official-document exports must preserve policy text without credential examples."""

from tools.ci_official_research import redact_document_examples, select_excerpts


def test_json_and_form_credential_examples_are_not_exported():
    sample = ('{"access_token":"public-doc-access", "refresh_token":"public-doc-refresh", '
              '"client_secret":"public-doc-secret", "scope":"youtube.upload"} '
              'code=public-doc-code&state=public-doc-state&code_verifier=public-doc-verifier')
    exported = redact_document_examples(sample)
    for value in ("public-doc-access", "public-doc-refresh", "public-doc-secret",
                  "public-doc-code", "public-doc-state", "public-doc-verifier"):
        assert value not in exported
    assert '"scope":"youtube.upload"' in exported
    assert '"access_token":"[PUBLIC_DOC_EXAMPLE_REDACTED]"' in exported


def test_redaction_preserves_pkce_algorithm_and_official_endpoint():
    text = ('code_challenge = BASE64URL-ENCODE(SHA256(ASCII(code_verifier))) '
            'S256 https://oauth2.googleapis.com/token redirect_uri=http://127.0.0.1:8765/oauth/callback')
    assert redact_document_examples(text) == text


def test_focused_excerpts_keep_procedure_after_large_intro_and_redact_values():
    lines = ["OAuth introduction " * 100] * 100
    lines.extend(['S256 code_challenge = BASE64URL-ENCODE(SHA256(ASCII(code_verifier)))',
                  'code_verifier=public-doc-verifier&state=public-doc-state'])
    excerpts = select_excerpts(lines, "native_pkce")
    joined = " ".join(excerpts)
    assert "S256" in joined and "BASE64URL-ENCODE" in joined
    assert "public-doc-verifier" not in joined and "public-doc-state" not in joined
    assert sum(map(len, excerpts)) <= 6000
