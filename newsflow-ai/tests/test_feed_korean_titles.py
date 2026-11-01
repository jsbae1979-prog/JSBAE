"""Korean local typesetting and immutable derivatives: no network or paid provider."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from PIL import Image, ImageDraw
import pytest
from newsflow.creation.catalog import DEFAULTS
from newsflow.creation.top_three_feeds import content_for, prompt_for
from newsflow.publishing.feed_titles import choose_title, title_lines, render_title, TITLE_LAYOUT
from newsflow.publishing.service import PublishingError
from test_top_three_selection import feeds
from test_feed_costs import ready, approve


def test_english_headline_reuses_complete_korean_summary_without_translation():
    sentence = "호주 의원 헬렌 헤인스와 용의자 가족이 오랜 친분을 이어왔다고 가족이 밝혔습니다."
    assert choose_title("English headline which must not be truncated", sentence + " 다음 문장입니다.") == sentence
    title = "한국어 전체 제목 " * 7
    assert choose_title(title.strip(), "요약입니다.") == title.strip()
    assert content_for({'title':'English headline','body':sentence,'rank':3}) == {
        'title':sentence,'body':sentence,'hashtags':'#뉴스요약 #정치 #호주'}

@pytest.mark.parametrize('title',["English title", "잘린 제목…", "가"*101, "한글 title", "비밀\x00문자"])
def test_invalid_headline_rejected_without_truncation(title):
    with pytest.raises(PublishingError):title_lines(title)

@pytest.mark.parametrize('height',[198,224,250,260])
def test_full_100_character_title_fits_without_ellipsis(height):
    title = "가나다라마바사아자차" * 10
    font,lines,line_height=title_lines(title,height)
    assert ''.join(lines)==title and '…' not in ''.join(lines)
    d=ImageDraw.Draw(Image.new('RGB',(1080,1350)))
    assert all(d.textlength(line,font=font)<=976 for line in lines)
    assert len(lines)*line_height<=height-44


def test_prompt_has_local_header_and_no_rank_badges():
    p=prompt_for({'rank':3,'references':[]},{'title':'한국어 제목','body':'요약'},7,1,local_title=True)
    assert 'Do not draw a headline' in p and 'Do not draw rank numbers' in p
    assert '260 pixels' in p


def completed(feeds):
    identifier=feeds.create(42,DEFAULTS['image'])
    row=feeds.get(identifier);r=deepcopy(row.result)
    raw=BytesIO();Image.new('RGB',(1080,1350),'#6699bb').save(raw,'JPEG')
    feeds.root.mkdir(parents=True,exist_ok=True)
    name=f'feed-{identifier}-1-1.jpg';(feeds.root/name).write_bytes(raw.getvalue())
    r['items'][0].update(status='success',filename=name,sha256=sha256(raw.getvalue()).hexdigest(),generation_id=999,title_header_bottom=260)
    feeds._save(identifier,r)
    return identifier,raw.getvalue()


def test_free_retitle_preserves_original_history_costs_and_revision(feeds):
    i,original=completed(feeds);before=feeds.get(i);opts=deepcopy(before.options)
    feeds.generation._generate=lambda *a,**k:pytest.fail('No provider')
    feeds.change(i,before.result['revision'],'retitle',rank=1,title='한국어 제목 전체 표시')
    after=feeds.get(i);item=after.result['items'][0]
    assert item['content']['title']=='한국어 제목 전체 표시'
    assert item['title_history'][0]['sha256']==sha256(original).hexdigest()
    assert (feeds.root/f'feed-{i}-1-1.jpg').read_bytes()==original
    assert after.options==opts and item['attempt']==1 and item['generation_id']==999
    assert feeds.path(i,1).name.endswith('-title-2.jpg')
    assert after.result['revision']==before.result['revision']+1
    assert feeds.view(i)['items'][0]['canEditTitle']
    with pytest.raises(PublishingError,match='다른 화면'):
        feeds.change(i,before.result['revision'],'retitle',rank=1,title='오래된 화면')


def test_legacy_uninspected_header_never_masked_automatically(feeds):
    i,original=completed(feeds);r=deepcopy(feeds.get(i).result);r['items'][0].pop('title_header_bottom');feeds._save(i,r)
    with pytest.raises(PublishingError,match='제목 영역'):
        feeds.change(i,r['revision'],'retitle',rank=1,title='한국어 제목')
    assert feeds.path(i,1).read_bytes()==original


def test_foreign_title_blocks_before_reservation_or_provider(ready):
    s,i,calls=ready;s.change(i,1,'edit',rank=1,title='Foreign headline',body='한글 요약')
    approve(s,i);before=deepcopy(s.get(i).options)
    with pytest.raises(PublishingError,match='한국어 제목'):s.step(i,consent=True,reviewed=True)
    assert not calls and s.get(i).options==before


def test_local_render_does_not_mutate_input():
    original=BytesIO();Image.new('RGB',(1080,1350),'navy').save(original,'JPEG');raw=original.getvalue()
    out=render_title(raw,'전체 한국어 제목')
    assert raw==original.getvalue()
    with Image.open(BytesIO(out)) as image:assert image.size==(1080,1350)


from test_image_selection import selected

def test_corrected_feed_publishing_copy_uses_exact_derivative(app,selected,monkeypatch):
    from newsflow.creation.top_three_feeds import TopThreeFeeds
    from newsflow.publishing.image_generation import ImageGenerationService
    from newsflow.db.models import IntelligenceRun
    from test_feed_recovery_improvements import terminal_image
    generation=ImageGenerationService(app.state.sessions,app.state.config.data_dir,None)
    feeds=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,generation)
    i=feeds.create(selected[0],DEFAULTS['image'])
    gid=terminal_image(feeds,i)
    with feeds.sessions.begin() as db:
        g=db.get(IntelligenceRun,gid);src=feeds.get(i).evidence['sources'][0]
        g.options={**g.options,'style':'full_card','draft_id':src['draft_id']}
        g.evidence={'source':{'plan':deepcopy(feeds.get(i).result['items'][0]['content'])}}
    row=feeds.get(i);result=deepcopy(row.result)
    feeds._accept(row,result['items'][0],gid);result['items'][0]['title_header_bottom']=260;feeds._save(i,result)
    feeds.change(i,1,'retitle',rank=1,title='교정한 한국어 제목')
    app.state.image_posts.generation=generation
    post=feeds.review(i,1,app.state.image_posts,reviewed=True,rights=True,sources_confirmed=True,ai_disclosure='disclose',image_safety_checked=True)
    assert app.state.image_posts.path(post).read_bytes()==feeds.path(i,1).read_bytes()
    # Same local save is idempotent; a later title revision keeps this post intact.
    assert feeds.review(i,1,app.state.image_posts,reviewed=True,rights=True,sources_confirmed=True,ai_disclosure='disclose',image_safety_checked=True)==post
    before=app.state.image_posts.path(post).read_bytes()
    feeds.change(i,feeds.get(i).result['revision'],'retitle',rank=1,title='추가 교정 한국어 제목')
    second=feeds.review(i,1,app.state.image_posts,reviewed=True,rights=True,sources_confirmed=True,ai_disclosure='disclose',image_safety_checked=True)
    assert second!=post and app.state.image_posts.path(post).read_bytes()==before


def test_retitle_http_requires_csrf_and_preserves_generation(feeds,app):
    from starlette.testclient import TestClient
    from bat_distribution.operation import OperatingRequests
    i,raw=completed(feeds)
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');data={'action':'retitle','rank':'1','revision':'1','title':'전체 한국어 제목'}
        assert c.post(f'/api/feed-batches/{i}/change',data={**data,'csrf_token':'invalid'}).status_code==403
        response=c.post(f'/api/feed-batches/{i}/change',data={**data,'csrf_token':c.cookies.get('newsflow_csrf')})
        assert response.status_code==200,response.text
        assert response.json()['items'][0]['content']['title']=='전체 한국어 제목'
        assert c.get(f'/api/feed-batches/{i}/items/1/file').headers['cache-control']=='no-store'


def test_wrap_keeps_korean_words_and_number_units_together():
    title="브렌던 누겐 가족, 헬렌 헤인스와 20년 넘게 친분"
    _, lines, _=title_lines(title,198)
    assert " ".join(lines)==title
    assert any("20년" in line for line in lines)


def test_layout_is_part_of_new_quote_binding_but_legacy_is_unchanged(feeds):
    from newsflow.creation.feed_costs import binding
    i=feeds.create(42,DEFAULTS['image']);row=feeds.get(i);new=binding(row)
    row.options={k:v for k,v in row.options.items() if k!='title_layout'}
    assert binding(row)!=new
