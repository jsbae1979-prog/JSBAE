"""Two new route-boundary checks; existing archival/accounting tests are reused."""
import hashlib
from types import SimpleNamespace

import pytest
from bat_distribution import character_trial as m
from newsflow.intelligence.credentials import CredentialError
from test_character_trial import read
from test_character_trial_authentication import authentication, sample
from test_request_archival import sessions, batch, contents

pytestmark = pytest.mark.parametrize('authentication', ['archive'], indirect=True)


def post(a, csrf, *, consent='true', origin=None):
    return a.client.post(m._ARCHIVE, headers={'Origin': origin or a.session.origin},
                         data={'csrf_token': csrf, 'consent': consent})


def test_archive_route_requires_auth_csrf_consent_and_runs_once_without_keys(authentication):
    a = authentication
    before = contents(a.sample.service.sessions)
    assert post(a, 'bad').status_code == 403
    csrf = a.login()
    state = a.client.get(m._STATUS).json()
    assert state['archiveReady'] and state['unknownCount'] == 7 and state['archivedCount'] == 0
    assert post(a, 'bad').status_code == 403
    assert post(a, csrf, origin='https://outside.invalid').status_code == 403
    assert post(a, csrf, consent='false').status_code == 409
    assert not read(a.sample)['calls']
    response = post(a, csrf)
    assert response.status_code == 200
    assert response.json() == {'count': 7, 'status': 'archived_unknown', 'replay_authorized': False}
    assert not any(identifier in response.text for identifier in before)
    after = contents(a.sample.service.sessions)
    assert set(after) == set(before) and len(after) == 7
    assert all(after[key] == {**value, 'status': 'archived_unknown'} for key, value in before.items())
    assert post(a, csrf).status_code == 409
    state = a.client.get(m._STATUS).json()
    assert not state['archiveReady'] and state['unknownCount'] == 0 and state['archivedCount'] == 7
    assert read(a.sample)['calls'] == {'archive': 1}
    assert a.sample.native.calls == a.state.checks == 0 and not a.state.requests


def test_archive_snapshot_mismatch_stays_atomic_and_native_errors_are_secret_safe(authentication):
    a = authentication
    before = contents(a.sample.service.sessions)
    identifier = next(iter(before))
    from newsflow.db.models import APIRequestReservation
    with a.sample.service.sessions.begin() as db:
        db.get(APIRequestReservation, identifier).reserved_usd = '.21'
    changed = contents(a.sample.service.sessions)
    csrf = a.login()
    assert not a.client.get(m._STATUS).json()['archiveReady']
    response = post(a, csrf)
    assert response.status_code == 409 and response.json()['code'] == 'archive_denied'
    assert contents(a.sample.service.sessions) == changed
    assert post(a, csrf).status_code == 409
    assert read(a.sample)['outcomes']['archive'] == 'failed_or_unknown'
    assert a.sample.native.calls == 0 and a.state.checks == 0

    def broken(payload, entropy):
        raise RuntimeError('synthetic-sensitive-native-diagnostic')
    cipher = m._ReadOnlyCipher(SimpleNamespace(active=lambda provider: None),
                              SimpleNamespace(unprotect=broken), 'claude', b'synthetic-label')
    with pytest.raises(CredentialError) as error:
        cipher.unprotect(bytearray(b'fake'), bytearray(hashlib.sha256(b'synthetic-label').digest()))
    assert 'synthetic-sensitive' not in str(error.value)
