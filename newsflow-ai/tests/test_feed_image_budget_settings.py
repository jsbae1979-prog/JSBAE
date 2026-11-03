from copy import deepcopy
import pytest
from newsflow.intelligence.api_settings import read_api_settings
from test_feed_budget import budget_setup,step
from test_top_three_selection import feeds


def post(b,limit='1',approved='true',csrf=None,headers=None):
    return b.client.post('/api/feed-image-budget',data={'request_limit_usd':limit,'approved':approved,'csrf_token':b.csrf if csrf is None else csrf},headers=b.headers if headers is None else headers)


def test_image_budget_operating_save_is_local_and_keeps_text_policy(budget_setup):
    b=budget_setup;before=read_api_settings(b.service.sessions,'openai')
    r=post(b);assert r.status_code==200,r.text
    assert r.json()['requestLimitUsd']=='1' and not b.calls
    assert b.readiness.standing_limit()=='1'
    assert read_api_settings(b.service.sessions,'openai')==before
    for _ in range(3):assert step(b).status_code==200
    assert len(b.calls)==3
    assert post(b,approved='false').status_code==200
    assert b.readiness.standing_limit() is None


@pytest.mark.parametrize('value',['0','-1','NaN','Infinity','10001','bad'])
def test_invalid_image_limit_preserves_setting(budget_setup,value):
    b=budget_setup;assert post(b).status_code==200
    assert post(b,value).status_code==422
    assert b.readiness.standing_limit()=='1' and not b.calls


@pytest.mark.parametrize('bad',['csrf','origin','session'])
def test_budget_save_requires_existing_local_security(budget_setup,bad):
    b=budget_setup
    if bad=='session':b.client.cookies.clear()
    r=post(b,csrf='bad' if bad=='csrf' else None,headers={'Origin':'https://outside.invalid'} if bad=='origin' else None)
    assert r.status_code==403 and not b.calls
    assert b.readiness.standing_limit() is None


def test_new_settings_registry_and_image_button():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for name in ['src/newsflow/studio/actions.json','frontend/src/legacy-actions.json']:
        a=next(x for x in json.loads((root/name).read_text(encoding='utf8')) if x['id']=='feed_image_budget_save')
        assert a['path']=='/api/feed-image-budget' and a['risk']=='local'
    text=(root/'frontend/src/studio/management/Settings.tsx').read_text(encoding='utf8')
    assert 'modelTab === "image"' in text and '"feed_image_budget_save"' in text
