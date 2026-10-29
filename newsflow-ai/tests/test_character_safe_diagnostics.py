"""Synthetic requester coverage: diagnostics never authorize or replay a submit."""
import json

import pytest

from newsflow.character.higgsfield_client import MODEL, HiggsfieldVideoClient
from newsflow.video.ai.contracts import (
    ProviderAmbiguousSubmit,
    ProviderAuthError,
    ProviderCreditError,
    ProviderInputError,
    ProviderModelError,
    ProviderResponseError,
)
from newsflow.video.ai.higgsfield import _NotSent


SYNTHETIC_KEY = 'synthetic-id:synthetic-secret'
IDEMPOTENCY_KEY = 'a' * 32
REQUEST_ID = 'owned-request-123'
CORRELATION_ID = 'owned-correlation-456'
PAYLOAD = {'prompt': 'private-synthetic-prompt', 'duration': 5}


def client_for(status, response):
    calls = []

    def requester(_host, method, _path, _body, _headers, _timeout):
        calls.append(method)
        body = response if isinstance(response, bytes) else json.dumps(response).encode()
        return status, body

    return HiggsfieldVideoClient(lambda: SYNTHETIC_KEY, requester=requester), calls


@pytest.mark.parametrize(('status', 'exception', 'code'), [
    (400, ProviderInputError, 'video_ai_bad_input'),
    (401, ProviderAuthError, 'video_ai_auth_failed'),
    (402, ProviderCreditError, 'video_ai_credits'),
    (403, ProviderCreditError, 'video_ai_credits'),
    (404, ProviderModelError, 'video_ai_bad_model'),
    (405, ProviderAmbiguousSubmit, 'video_ai_bad_response'),
    (422, ProviderInputError, 'video_ai_bad_input'),
    (408, ProviderAmbiguousSubmit, 'video_ai_unknown_submit'),
    (429, ProviderAmbiguousSubmit, 'video_ai_unknown_submit'),
    (500, ProviderAmbiguousSubmit, 'video_ai_unknown_submit'),
    (503, ProviderAmbiguousSubmit, 'video_ai_unknown_submit'),
])
def test_http_failure_preserves_classification_safe_facts_and_single_submit(status, exception, code):
    client, calls = client_for(status, {
        'request_id': REQUEST_ID, 'correlation_id': CORRELATION_ID,
        'message': 'private-provider-prose', 'prompt': PAYLOAD['prompt'],
        'url': 'https://private.example/signed?secret=private-query',
        'headers': {'Authorization': SYNTHETIC_KEY},
        'error': {'message': SYNTHETIC_KEY},
    })
    with pytest.raises(exception) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    error = caught.value
    assert type(error) is exception
    assert error.safe_diagnostics == {
        'http_status': status, 'error_code': code,
        'request_id': REQUEST_ID, 'correlation_id': CORRELATION_ID,
    }
    assert error.retryable is False and error.sent is True
    assert calls == ['POST']
    serialized = json.dumps(error.safe_diagnostics)
    for forbidden in (SYNTHETIC_KEY, PAYLOAD['prompt'], 'private-provider-prose',
                      'private-query', 'Authorization', 'https://'):
        assert forbidden not in serialized


@pytest.mark.parametrize('response', [
    {'error_code': 'insufficient_credits'},
    {'code': 'insufficient_credits'},
    {'error': {'code': 'insufficient_credits', 'message': 'private-provider-prose'}},
])
def test_only_allowlisted_provider_error_code_is_retained(response):
    client, calls = client_for(400, response)
    with pytest.raises(ProviderInputError) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {'http_status': 400, 'error_code': 'insufficient_credits'}
    assert calls == ['POST']


@pytest.mark.parametrize('code', [
    'private-but-token-shaped', SYNTHETIC_KEY, 'synthetic-secret',
    'https://private.example/error', 'invalid_request\nprivate-prose',
    'x' * 1000, {'code': 'invalid_request'}, ['invalid_request'], None, 401,
])
def test_unknown_or_malformed_error_codes_are_discarded(code):
    client, calls = client_for(400, {'error_code': code, 'error': {'code': code}})
    with pytest.raises(ProviderInputError) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {'http_status': 400, 'error_code': 'video_ai_bad_input'}
    assert calls == ['POST']


@pytest.mark.parametrize('field', ['request_id', 'correlation_id'])
@pytest.mark.parametrize('value', [
    SYNTHETIC_KEY, 'request-synthetic-secret', 'request-synthetic-id', IDEMPOTENCY_KEY,
    'https://private.example/owned-id', 'request-id\nprivate-prose', 'short',
    'x' * 101, {'id': REQUEST_ID}, [REQUEST_ID], 12345678, None,
])
def test_response_ids_are_bounded_validated_and_cannot_echo_credentials_or_submit_key(field, value):
    client, calls = client_for(401, {field: value})
    with pytest.raises(ProviderAuthError) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {'http_status': 401, 'error_code': 'video_ai_auth_failed'}
    assert calls == ['POST']


@pytest.mark.parametrize('status', [200, 201, 202])
@pytest.mark.parametrize('malformation', ['missing_url', 'invalid_url', 'invalid_state', 'malformed_state'])
def test_unusable_success_response_keeps_http_status_and_owned_ids_as_unknown(status, malformation):
    response = {
        'request_id': REQUEST_ID, 'correlation_id': CORRELATION_ID, 'status': 'queued',
        'status_url': f'https://api.higgsfield.ai/requests/{REQUEST_ID}/status',
    }
    if malformation == 'missing_url':
        response.pop('status_url')
    elif malformation == 'invalid_url':
        response['status_url'] = 'https://private.example/signed?private-query'
    else:
        response['status'] = {} if malformation == 'malformed_state' else 'private-state'
    client, calls = client_for(status, response)
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {
        'http_status': status, 'error_code': 'video_ai_unknown_submit',
        'request_id': REQUEST_ID, 'correlation_id': CORRELATION_ID,
    }
    assert caught.value.retryable is False
    assert calls == ['POST']


def test_credential_echo_in_success_response_stays_unknown_with_safe_diagnostics():
    client, calls = client_for(202, {
        'request_id': REQUEST_ID, 'status': 'queued',
        'status_url': f'https://api.higgsfield.ai/requests/{REQUEST_ID}/status',
        'message': SYNTHETIC_KEY,
    })
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {
        'http_status': 202, 'error_code': 'video_ai_bad_response', 'request_id': REQUEST_ID,
    }
    assert calls == ['POST']


@pytest.mark.parametrize('body', [b'private unstructured prose', b'[]', b'null', b'\xff'])
def test_unstructured_http_error_retains_no_response_content(body):
    client, calls = client_for(400, body)
    with pytest.raises(ProviderInputError) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {'http_status': 400, 'error_code': 'video_ai_bad_input'}
    assert calls == ['POST']


def test_safe_call_also_attaches_sanitized_failure_to_original_exception():
    client, calls = client_for(422, {'error': {'code': 'validation_error'}, 'request_id': REQUEST_ID})
    with pytest.raises(ProviderInputError) as caught:
        client._safe_call('POST', '/estimate/' + MODEL, PAYLOAD)
    assert caught.value.safe_diagnostics == {
        'http_status': 422, 'error_code': 'validation_error', 'request_id': REQUEST_ID,
    }
    assert calls == ['POST']


@pytest.mark.parametrize('exception', [ConnectionError, ProviderResponseError])
def test_transport_failure_has_no_invented_http_status_or_untrusted_diagnostic_attributes(exception):
    calls = []

    def requester(*_args):
        calls.append('POST')
        error = exception('private-exception-prose')
        error.safe_diagnostics = {'message': SYNTHETIC_KEY, 'http_status': 401}
        raise error

    client = HiggsfieldVideoClient(lambda: SYNTHETIC_KEY, requester=requester)
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert caught.value.safe_diagnostics == {'error_code': 'video_ai_unknown_submit'}
    assert caught.value.retryable is False
    assert calls == ['POST']


def test_not_sent_exception_is_preserved_without_a_second_attempt():
    calls = []

    def requester(*_args):
        calls.append('POST')
        raise _NotSent()

    client = HiggsfieldVideoClient(lambda: SYNTHETIC_KEY, requester=requester)
    with pytest.raises(_NotSent):
        client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY)
    assert calls == ['POST']


def test_valid_submit_handle_remains_unchanged():
    url = f'https://api.higgsfield.ai/requests/{REQUEST_ID}/status'
    client, calls = client_for(202, {
        'request_id': REQUEST_ID, 'correlation_id': CORRELATION_ID,
        'status': 'queued', 'status_url': url,
    })
    assert client.submit_scene(PAYLOAD, IDEMPOTENCY_KEY) == {'request_id': REQUEST_ID, 'status_url': url}
    assert calls == ['POST']
