"""Synthetic response bytes only; no stored credentials or live search."""
from copy import deepcopy
import json
import pytest
from sqlalchemy import select
from newsflow.db.models import IntelligenceRun
from newsflow.news.serpapi import parse_result,SerpApiError,SerpApiAdapter
from test_serpapi_news import RESULT,KEY,setup_serpapi,no_external_calls,register
from test_category_collection import post_serp
from test_google_news_trends import TREND,TRENDS_URL
from uuid import uuid4

@pytest.mark.parametrize('source',[None,{}, {'title':'합성 출처'}])
def test_null_optional_metadata_and_article_anchor(source):
    data=deepcopy(RESULT)
    data['news_results'][0].update(source=source,snippet=None,summary=None,highlight=None,stories=None,link='https://example.com/solar#section')
    rows,meta=parse_result(data)
    assert len(rows)==2 and rows[0].url=='https://example.com/solar'
    assert rows[0].publisher==('합성 출처' if source else '출처 미확인')
    assert rows[0].summary=='' and meta['skipped_items']==0

@pytest.mark.parametrize('bad',[{'link':'http://127.0.0.1/private','title':'private'},
    {'link':'https://example.com/a?api_key=SECRET','title':'secret'},
    {'link':'file:///private','title':'file'}, {'link':'https://user:SECRET@example.com/a','title':'secret'},
    {'link':'https://example.com/a','title':None}, {'link':'https://example.com/a','title':'ok','source':['SECRET']},None])
def test_bad_item_is_excluded_not_allowed_and_valid_siblings_retained(bad):
    data=deepcopy(RESULT);data['news_results'].insert(0,bad)
    rows,meta=parse_result(data)
    assert len(rows)==2 and meta['skipped_items']==1
    assert all('SECRET' not in x.url and '127.0.0.1' not in x.url for x in rows)
    assert 'SECRET' not in json.dumps(meta)
    data['news_results']=[bad]
    with pytest.raises(SerpApiError) as e:parse_result(data)
    assert e.value.diagnostics()=={'reason':'no_valid_articles'}

@pytest.mark.parametrize('data,reason',[(None,'document'),({'search_metadata':{'status':'Processing'}},'response_status'),
    ({'search_metadata':{'status':'Success'},'news_results':{}},'news_results'),
    ({'error':'SECRET vendor prose'},'provider_error'),
    ({'search_metadata':{'status':'Success'},'news_results':[{}]*201},'structure_limit')])
def test_structural_errors_fixed_diagnostic_not_raw_response(data,reason):
    with pytest.raises(SerpApiError) as e:parse_result(data)
    assert e.value.diagnostics()=={'reason':reason}
    assert 'SECRET' not in str(e.value)
    assert SerpApiError('bad_response',reason='SECRET').reason=='unknown'

def test_wire_diagnostic_no_retries_or_response_retention(setup_serpapi,monkeypatch):
    keys,_=setup_serpapi;keys.save(KEY);adapter=SerpApiAdapter(keys);calls=[]
    def send(*args):calls.append(1);return b'<html>SECRET</html>'
    monkeypatch.setattr(adapter,'_open',send)
    with pytest.raises(SerpApiError) as e:adapter.search()
    assert e.value.reason=='json_decode' and calls==[1] and 'SECRET' not in str(e.value)

def test_category_valid_siblings_preserved_and_following_requests_not_replayed(client,app,fake,setup_serpapi):
    register(client);fake.feeds[TRENDS_URL]=TREND
    class Adapter:
        test_only=True
        calls=0
        def search(self,**kwargs):
            self.calls+=1
            data=deepcopy(RESULT)
            if self.calls==2:data['news_results'].insert(0,{'link':'http://127.0.0.1/private','title':'SECRET'})
            return parse_result(data)
    adapter=Adapter();app.state.serpapi_adapter=adapter;token=uuid4().hex
    categories=['IT·과학','문화','연예']
    assert post_serp(client,token,categories).status_code==200
    assert adapter.calls==3
    assert post_serp(client,token,categories).status_code==200 and adapter.calls==3
    with app.state.sessions() as db:
        run=db.scalar(select(IntelligenceRun).where(IntelligenceRun.provider=='serpapi'))
        assert run.status=='success' and run.result['requests'][1]['metadata']['skipped_items']==1
        assert run.result['category_counts'][1]['skipped_items']==1
        assert 'SECRET' not in json.dumps(run.result)

def test_fatal_category_keeps_safe_diagnostic_and_remaining_unrequested(client,app,setup_serpapi):
    register(client)
    class Adapter:
        test_only=True
        calls=0
        def search(self,**kwargs):
            self.calls+=1
            if self.calls==2:raise SerpApiError('bad_response',reason='news_results')
            return parse_result(RESULT)
    adapter=Adapter();app.state.serpapi_adapter=adapter;token=uuid4().hex
    assert post_serp(client,token,['IT·과학','문화','연예']).status_code==422
    assert adapter.calls==2
    assert post_serp(client,token,['IT·과학','문화','연예']).status_code==200 and adapter.calls==2  # existing result view, no replay
    with app.state.sessions() as db:
        run=db.scalar(select(IntelligenceRun).where(IntelligenceRun.provider=='serpapi'))
        assert run.status=='failed'
        assert run.result['diagnostic']=={'reason':'news_results'}
        assert run.result['requests'][1]['diagnostic']=={'reason':'news_results'}
        assert run.result['category_counts'][2]['status']=='pending'
