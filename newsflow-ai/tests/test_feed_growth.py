from copy import deepcopy
from datetime import datetime, timezone
import json
import pytest
from starlette.testclient import TestClient
from newsflow.creation.feed_growth import caption_parts, compose_caption, copy_options, FeedPerformance
from newsflow.publishing.service import PublishingError
from newsflow.publishing.photo_feed import validate
from newsflow.db.models import AppSetting
from bat_distribution.operation import OperatingRequests
from test_photo_feed_editor import feeds, prepared

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def sample(**updates):
    return {"version":1,"url":"https://www.instagram.com/p/Example123/","publishedAt":"2026-10-31T09:00:00+09:00",
            "observedAt":"2026-11-01T00:00:00Z","reach":1000,"saves":25,"shares":10,"follows":None,"publishedConfirmed":True,**updates}


def setup(feeds):
    designs,b,state,d=prepared(feeds)
    designs.save(b,1,state['revision'],state['background'],d,export=True)
    return FeedPerformance(designs,now=lambda:NOW),b,designs


def test_exact_title_options_preserve_numbers_status_and_no_forced_question():
    source={'title':'2026년 20km 노선 검토','body':'노선은 검토 중입니다. 아직 확정되지 않았습니다.'}
    options=copy_options(source,{'content':{'title':source['title']}},{'title':'2026년 20km 노선\n검토'})
    assert len(options['titleCandidates'])==2
    assert options['titleCandidates'][0]['text']=='2026년 20km 노선\n검토'
    assert options['titleCandidates'][1]['text']=='노선은 검토 중입니다.'
    assert not options['paid']
    assert all('확정' not in c['text'] and '?' not in c['text'] for c in options['titleCandidates'])
    english=copy_options({'title':'Plan under review','body':'검토 중입니다.'},{'content':{'title':'검토 중인 계획'}},{'title':'현재 제목'})
    assert english['titleCandidates'][2]['korean'] is False


def test_caption_optional_sections_and_preserved_version(feeds):
    s,b,state,d=prepared(feeds)
    parts={'lead':'2026년 관측 계획 공개','facts':'추가 검토 중이며 확정되지 않았습니다.','meaning':'','question':''}
    caption=compose_caption(parts)
    assert caption=='2026년 관측 계획 공개\n\n추가 검토 중이며 확정되지 않았습니다.'
    first=s.save(b,1,state['revision'],state['background'],d,export=True)
    edited={**d,'caption_sections':parts,'caption':caption}
    second=s.save(b,1,first['revision'],first['background'],edited,export=True)
    assert second['versions'][0]['design']['caption']==d['caption']
    assert s.state(b,1)['draft']['caption_sections']==parts
    assert s.state(b,2)['versions']==[]
    assert s.view(b,1)['copyOptions']['paid'] is False


@pytest.mark.parametrize('parts',[{'lead':'a'*181},{'facts':'a'*1201},{'meaning':'a'*301},{'question':'a'*181},{'lead':5},{'notes':'private'},{'lead':'bad\x00'}])
def test_caption_rejects_invalid_inputs(parts):
    with pytest.raises(PublishingError):caption_parts(parts)


def test_caption_empty_and_total_limit():
    with pytest.raises(PublishingError):compose_caption({})
    with pytest.raises(PublishingError):compose_caption({'lead':'a'*180,'facts':'b'*1200,'meaning':'c'*300,'question':'d'*180})
    assert validate({'title':'Old draft'})['caption_sections']=={}


def test_manual_metrics_rates_idempotency_and_scope(feeds):
    metrics,b,designs=setup(feeds)
    before=deepcopy(feeds.get(b).result)
    feeds.generation._generate=lambda *a,**k:pytest.fail('No paid request')
    saved=metrics.save(b,1,0,sample())
    row=saved['records'][0]
    assert row['rates']=={'saves':2.5,'shares':1.0,'follows':None}
    assert row['elapsedHours']==24 and row['source']=='manual' and not row['verifiedByPlatform']
    assert metrics.save(b,1,0,sample())==saved  # duplicated button request, no duplicate row
    assert FeedPerformance(designs,now=lambda:NOW).view(b,1)==saved
    assert metrics.view(b,2)['records']==[] and feeds.get(b).result==before
    with pytest.raises(PublishingError,match='원래 기록'):metrics.save(b,1,1,sample(saves=50))
    with pytest.raises(PublishingError,match='다른 화면'):metrics.save(b,1,0,sample(observedAt='2026-11-01T01:00:00Z'))


@pytest.mark.parametrize('reach,saves,expected',[(None,0,None),(0,5,None),(100,0,0.0)])
def test_unknown_is_not_zero_and_zero_reach_never_divides(feeds,reach,saves,expected):
    metrics,b,_=setup(feeds)
    saved=metrics.save(b,1,0,sample(reach=reach,saves=saves))
    assert saved['records'][0]['rates']['saves']==expected


@pytest.mark.parametrize('patch',[
    {'publishedConfirmed':False},{'url':'https://evil.test/p/abc'}, {'url':'https://instagram.com/p/abc/?token=secret'},
    {'version':2},{'version':True},{'publishedAt':'2026-11-02T00:00:00Z'},
    {'observedAt':'2026-11-02T00:00:00Z'},{'observedAt':'2026-11-01T00:00:00'},
    {'reach':-1},{'reach':True},{'saves':1.5},{'reach':None,'saves':None,'shares':None,'follows':None}])
def test_manual_performance_rejects_invalid_without_records(feeds,patch):
    metrics,b,_=setup(feeds)
    with pytest.raises(PublishingError):metrics.save(b,1,0,sample(**patch))
    assert metrics.view(b,1)['records']==[]


def test_post_identity_cannot_change_version(feeds):
    metrics,b,designs=setup(feeds)
    state=designs.state(b,1)
    designs.save(b,1,state['revision'],state['background'],{**state['draft'],'accent':'#ffcc55'},export=True)
    metrics.save(b,1,0,sample())
    with pytest.raises(PublishingError,match='동일 이미지'):
        metrics.save(b,1,1,sample(version=2,observedAt='2026-11-01T01:00:00Z'))


def test_caption_and_metric_routes_auth_csrf_no_network(app,feeds):
    metrics,b,designs=setup(feeds)
    prefix=f'/api/feed-batches/{b}/items/1'
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');csrf=c.cookies.get('newsflow_csrf')
        before=designs.state(b,1)
        caption={'revision':before['revision'],'action':'caption','background':'caption-only','design':json.dumps({'lead':'계획 검토 중'})}
        assert c.post(prefix+'/design',data=caption).status_code==403
        response=c.post(prefix+'/design',data={**caption,'csrf_token':csrf})
        assert response.status_code==200 and response.json()['caption']=='계획 검토 중'
        assert designs.state(b,1)==before
        assert c.get(prefix+'/design-performance').json()['records']==[]
        data={'revision':0,'metrics':json.dumps(sample())}
        assert c.post(prefix+'/design-performance',data=data).status_code==403
        assert c.post(prefix+'/design-performance',data={**data,'csrf_token':csrf},headers={'Origin':'https://evil.test'}).status_code==403
        response=c.post(prefix+'/design-performance',data={**data,'csrf_token':csrf})
        assert response.status_code==200,response.text
        assert response.json()['records'][0]['source']=='manual'
        assert c.post(f'/api/feed-batches/{b}/step',data={'csrf_token':csrf}).status_code==403
    assert designs.state(b,1)==before
