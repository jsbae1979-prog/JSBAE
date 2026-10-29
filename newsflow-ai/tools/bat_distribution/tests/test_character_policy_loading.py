"""Optional character approval remains pinned and expires without unlocking the app."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest

from bat_distribution.lifecycle import Blocked
from bat_distribution.windows_live import character_trial_policy, active_character_trial_policy


def configured(tmp_path, *, expires=None):
    program, profile = tmp_path/'program', tmp_path/'profile'
    (program/'app').mkdir(parents=True)
    profile.mkdir()
    value={'expires_at':(expires or datetime.now(UTC)+timedelta(hours=1)).isoformat()}
    content=json.dumps(value).encode()
    (profile/'character-api-policy.private.json').write_bytes(content)
    (program/'app/layout.json').write_text(json.dumps({'characterTrialPolicySha256':hashlib.sha256(content).hexdigest()}))
    return SimpleNamespace(program=program,profile=profile,profile_kind='restored-local-operation'),value


def test_exact_approved_policy_is_loaded(tmp_path):
    config,value=configured(tmp_path)
    assert character_trial_policy(config)==value


def test_missing_approval_keeps_existing_mode(tmp_path):
    config,_=configured(tmp_path)
    (config.program/'app/layout.json').write_text('{}')
    assert character_trial_policy(config) is None


def test_expired_trial_does_not_block_local_app(tmp_path):
    config,_=configured(tmp_path,expires=datetime.now(UTC)-timedelta(seconds=1))
    assert character_trial_policy(config) is None


def test_modified_policy_is_not_accepted(tmp_path):
    config,_=configured(tmp_path)
    (config.profile/'character-api-policy.private.json').write_text('{"expires_at":"2099-01-01T00:00:00Z"}')
    with pytest.raises(Blocked):character_trial_policy(config)


def test_other_profile_never_adopts_trial(tmp_path):
    config,_=configured(tmp_path)
    config.profile_kind='restored-private-validation'
    assert character_trial_policy(config) is None


def test_closed_reuse_policy_retires_only_operation_wrapper_without_changing_approval():
    policy={'reuse_source_job_id':'a'*32,'allow_submit':False,'expires_at':'historical'}
    original=dict(policy)
    for kind in ('restored-local-operation','portable-local-operation'):
        config=SimpleNamespace(profile_kind=kind)
        assert active_character_trial_policy(config,policy) is None
        assert policy==original
        for active in ({**policy,'allow_submit':True},{'allow_submit':False},None):
            assert active_character_trial_policy(config,active) is active
    config=SimpleNamespace(profile_kind='restored-private-validation')
    assert active_character_trial_policy(config,policy) is policy
