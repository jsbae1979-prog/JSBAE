"""Google RFC 9207 callback compatibility, local HTTP and synthetic codes only."""
import pytest
from test_oauth_callback import listener as listener, params, request
from newsflow.oauth.callback import CallbackError


def test_google_issuer_callback_retains_bound_permissions_and_one_use(listener):
    callback, launch = listener
    values = [*params(launch), ('iss', 'https://accounts.google.com'),
              ('scope', 'openid'), ('authuser', '0'), ('prompt', 'consent')]
    assert request(launch, values=values)[0] == 200
    result = callback.wait(1)
    result.assert_valid('youtube:1')
    assert result.scopes == launch.request.scopes
    assert result.account_key == launch.request.account_key
    assert request(launch, values=values)[0] == 409
    assert callback.evidence()['real_oauth_requests'] == 0


@pytest.mark.parametrize('issuer', [
    'https://attacker.invalid', 'http://accounts.google.com', 'accounts.google.com',
    'https://accounts.google.com/', 'https://accounts.google.com.attacker.invalid',
])
def test_unexpected_issuer_rejected_without_reflection(listener, issuer, capfd):
    callback, launch = listener
    status, body, _ = request(launch, values=[*params(launch), ('iss', issuer)])
    assert status == 400 and issuer.encode() not in body
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.reason == 'issuer'
    assert capfd.readouterr() == ('', '')


@pytest.mark.parametrize('extra,reason', [
    ([('iss', '')], 'empty_field'),
    ([('iss', 'https://accounts.google.com'), ('iss', 'https://accounts.google.com')], 'duplicate_field'),
    ([('iss', 'https://accounts.google.com'), ('unrecognized', 'value')], 'unknown_field'),
])
def test_issuer_does_not_relax_other_field_validation(listener, extra, reason):
    callback, launch = listener
    assert request(launch, values=[*params(launch), *extra])[0] == 400
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.reason == reason


def test_issuer_with_wrong_state_does_not_consume_login(listener):
    callback, launch = listener
    invalid = [('state', 'x' * 43), ('code', 'nf-synthetic-code-invalid'), ('iss', 'https://accounts.google.com')]
    assert request(launch, values=invalid)[0] == 400
    assert request(launch, values=[*params(launch), ('iss', 'https://accounts.google.com')])[0] == 200
    callback.wait(1).assert_valid('youtube:1')


def test_issuer_on_provider_denial_is_not_a_success(listener):
    callback, launch = listener
    values = [('state', launch.request.state.get_secret_value()), ('error', 'access_denied'),
              ('iss', 'https://accounts.google.com')]
    assert request(launch, values=values)[0] == 400
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.reason == 'provider_denied'
