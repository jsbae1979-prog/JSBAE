"""Only the one-record review and the explicitly reduced video ceiling are new."""
from types import SimpleNamespace

import pytest
from bat_distribution import character_trial as m
from newsflow.character.schema import CharacterError
from test_character_trial import sample, ID
from test_character_trial_authentication import authentication
from test_request_archival import sessions, batch, contents


@pytest.mark.parametrize('authentication', ['archive-one'], indirect=True)
def test_one_reviewed_unknown_is_archived_from_authenticated_gui_without_replay(authentication):
    a = authentication
    csrf = a.login()
    before = contents(a.sample.service.sessions)
    state = a.client.get(m._STATUS).json()
    assert state['archiveReady'] and state['unknownCount'] == 1
    response = a.client.post(m._ARCHIVE, headers={'Origin': a.session.origin},
                             data={'consent': 'true', 'csrf_token': csrf})
    assert response.status_code == 200
    assert response.json() == {'count': 1, 'status': 'archived_unknown', 'replay_authorized': False}
    after = contents(a.sample.service.sessions)
    selected = next(iter(a.sample.trial.unknown_review))
    assert after[selected] == {**before[selected], 'status': 'archived_unknown'}
    assert all(after[key] == value for key, value in before.items() if key != selected)
    assert len(after) == len(before) == 7
    state = a.client.get(m._STATUS).json()
    assert not state['archiveReady'] and state['unknownCount'] == 0 and state['archivedCount'] == 1
    assert a.sample.native.calls == a.state.checks == 0


def test_two_fifty_policy_bounds_job_and_single_video_quote_without_unlocking_other_caps(sample):
    policy = {**sample.policy, 'id': 'd' * 32, 'video_limit_usd': '2.50'}
    trial = m.Trial(sample.service, sample.root, policy)
    with pytest.raises(CharacterError):
        trial._valid(ID)  # The old 2.75 job limit is outside this new approval.
    job = sample.service.jobs[ID]
    job.update(episode_limit='2.50', state='quoted', script={'scenes': [{'seconds': 3} for _ in range(5)]},
               scenes=[{'state': 'not_submitted', 'quote_usd': '2.51'}], quote_total_usd='2.51')
    assert trial._valid(ID)['id'] == ID
    with trial.journal() as row:
        row['job_id'] = ID
        row['script']['state'] = 'reported'
        row['outcomes'].update({'auto-story': 'success', 'prepare': 'success'})
    called = []
    token = m._CONTEXT.set(SimpleNamespace(trial=trial, action='submit', job_id=ID))
    try:
        with pytest.raises(CharacterError):
            trial.invoke('submit', ID, lambda: called.append('synthetic-only'))
        assert called == []
        job['scenes'][0]['quote_usd'] = job['quote_total_usd'] = '2.50'
        trial.invoke('submit', ID, lambda: called.append('synthetic-only'))
        with pytest.raises(CharacterError):
            trial.invoke('submit', ID, lambda: called.append('must-not-run'))
    finally:
        m._CONTEXT.reset(token)
    assert called == ['synthetic-only'] and sample.native.calls == 0
    with trial.journal(readonly=True) as row:
        assert row['video']['reserved_usd'] == '2.50' and row['calls']['submit'] == 1
    with pytest.raises(CharacterError):
        m._policy({**policy, 'video_limit_usd': '2.51'})
