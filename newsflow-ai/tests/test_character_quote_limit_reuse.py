"""Reuse a valid, never-submitted official quote after a ceiling-only edit."""
from copy import deepcopy
from datetime import timedelta

import pytest
from test_api_settings import sessions, store
from test_character_kling_studio import studio
from test_character_single_video import seeded
from test_character_visibility import files

from newsflow.character.kling import check
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint, now


def quoted(studio):
    service=studio.service
    identifier,provider,estimates=seeded(studio,duration=30)
    service.prepare(identifier,consent=True,script_reviewed=True)
    return identifier,provider,estimates,service.read(identifier)


def test_ceiling_only_edit_retains_quote_and_invalidates_old_approval(studio):
    service=studio.service;identifier,provider,estimates,before=quoted(studio)
    before['quote_history']=[{'historical':'preserve'}];service.save(before)
    service.update_studio_settings(identifier,check(before['studio_selection']),'5')
    after=service.read(identifier)
    for key in ('state','scenes','quote_total_usd','quoted_at','quote_key_id','quote_history','studio_selection','script','prompts','day_limit'):
        assert after[key]==before[key]
    assert after['episode_limit']=='5' and after['quote_hash']!=before['quote_hash']
    assert after['plan_hash']==service.plan_hash(after)
    assert after['quote_hash']==fingerprint([after['plan_hash'],after['scenes'],before['quoted_at'],before['quote_key_id']])
    assert len(after['quote_limit_changes'])==1 and after['quote_limit_changes'][0]['quote_hash']==before['quote_hash']
    assert len(estimates)==5 and provider.calls==0
    with pytest.raises(CharacterError):service.submit(identifier,consent=True,quote_hash=before['quote_hash'])
    assert provider.calls==0
    service.submit(identifier,consent=True,quote_hash=after['quote_hash'])
    assert provider.calls==5 and len(estimates)==5


def test_unchanged_ceiling_and_settings_are_a_true_noop(studio):
    service=studio.service;identifier,provider,estimates,before=quoted(studio)
    snapshot=files(service,identifier)
    service.update_studio_settings(identifier,check(before['studio_selection']),'10.00')
    assert service.read(identifier)==before and files(service,identifier)==snapshot
    assert len(estimates)==5 and provider.calls==0


def test_lower_ceiling_cannot_authorize_more_than_the_new_limit(studio):
    service=studio.service;identifier,provider,estimates,before=quoted(studio)
    service.update_studio_settings(identifier,check(before['studio_selection']),'0.40')
    after=service.read(identifier)
    assert after['state']=='quoted' and after['quote_total_usd']=='0.50' and after['quoted_at']==before['quoted_at']
    with pytest.raises(CharacterError):service.submit(identifier,consent=True,quote_hash=after['quote_hash'])
    assert provider.calls==0 and len(estimates)==5


def test_ceiling_edit_never_extends_expired_quote(studio,monkeypatch):
    service=studio.service;identifier,provider,estimates,before=quoted(studio)
    monkeypatch.setattr('newsflow.character.service.now',lambda:now()+timedelta(minutes=16))
    service.update_studio_settings(identifier,check(before['studio_selection']),'5')
    after=service.read(identifier)
    assert after['state']=='script_review' and after['scenes']==[] and 'quote_hash' not in after
    assert after['quote_history'][-1]['quoted_at']==before['quoted_at']
    assert after['quote_history'][-1]['scenes']==before['scenes']
    assert provider.calls==0 and len(estimates)==5


@pytest.mark.parametrize('tamper',['hash','total','submitted'])
def test_ceiling_edit_rejects_untrusted_or_submitted_quote_without_mutation(studio,tamper):
    service=studio.service;identifier,provider,estimates,before=quoted(studio)
    if tamper=='hash':before['quote_hash']='0'*64
    elif tamper=='total':before['quote_total_usd']='0.01'
    else:before['scenes'][0]['state']='submitted'
    service.save(before);snapshot=files(service,identifier)
    with pytest.raises(CharacterError):service.update_studio_settings(identifier,check(before['studio_selection']),'5')
    assert files(service,identifier)==snapshot and provider.calls==0 and len(estimates)==5

def test_settings_route_returns_only_safe_quote_retention_state(studio):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from newsflow.gui.character_routes import router
    service=studio.service;identifier,provider,estimates,before=quoted(studio)
    app=FastAPI();app.state.character=service;app.include_router(router)
    settings=check(before['studio_selection'])
    with TestClient(app) as client:
        response=client.post(f'/api/studio/characters/{identifier}/settings',data={
            'settings':json.dumps(settings),'episode_limit':'5'})
        assert response.status_code==200
        assert response.json()=={'id':identifier,'saved':True,'state':'quoted','quoteRetained':True}
        response=client.post(f'/api/studio/characters/{identifier}/settings',data={
            'settings':json.dumps({**settings,'duration':45,'clip_seconds':9}),'episode_limit':'5'})
        assert response.status_code==200
        assert response.json()=={'id':identifier,'saved':True,'state':'script_review','quoteRetained':False}
    assert len(estimates)==5 and provider.calls==0
