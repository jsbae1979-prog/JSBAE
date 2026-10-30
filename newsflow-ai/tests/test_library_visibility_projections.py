"""Synthetic local projections only: no network, publication or provider requests."""
import hashlib
from uuid import uuid4

from sqlalchemy import select

from newsflow.db.models import (AIUsage, APIRequestReservation, ImagePostDelivery, PlatformAccount,
    PublishDraft, PublishEvidence, PublishJob, SocialMetric, WorkspaceRemoval)
from test_library_visibility import character, mixed, post
from test_single_workspace import video_fixture


def publication_fixture(app):
    """Persist production-shaped receipts in a synthetic DB; never perform a publish."""
    video = video_fixture(app, '합성 게시 완료 콘텐츠')
    unpublished = video_fixture(app, '합성 미게시 콘텐츠')
    with app.state.sessions.begin() as session:
        account = PlatformAccount(platform='youtube',label='Synthetic channel',account_type='channel')
        session.add(account); session.flush()
        draft = PublishDraft(render_job_id=video['id'],platform='youtube',title='합성 게시 완료 콘텐츠',
            description='',hashtags=[],sources={},media_sha256='a'*64,account_id=account.id)
        session.add(draft); session.flush()
        job = PublishJob(draft_id=draft.id,platform='youtube',status='uploaded',message='Synthetic fixture',
            idempotency_key=uuid4().hex)
        session.add(job); session.flush()
        evidence = PublishEvidence(draft_id=draft.id,kind='youtube_upload_result',payload={
            'job_id':job.id,'status':'uploaded','account_id':account.id,'video_id':'abcdefghijk'})
        session.add(evidence)
        for synthetic, remote in [(False,'abcdefghijk'),(True,'abcdefghijk'),(False,'mismatch-id')]:
            session.add(SocialMetric(job_id=job.id,account_id=account.id,platform='youtube',remote_id=remote,
                metric='views' if remote=='abcdefghijk' else 'likes',value='17',unit='count',
                period_start='2026-10-30',period_end='2026-10-30',period_basis='day',synthetic=synthetic))
        session.add(AIUsage(provider='offline',model='fake',kind='script',status='failed',
            prompt_tokens=17,completion_tokens=3,total_tokens=20,elapsed_ms=1))
        session.add(APIRequestReservation(id=uuid4().hex,request_id=uuid4().hex,provider='offline',
            kind='script',model='fake',status='unknown',reserved_usd='0.50',estimated_usd=None,
            bounds={},prices={},usage={},test_only=True))
        return {'published':'news:'+str(video['id']),'unpublished':'news:'+str(unpublished['id']),
                'job_id':job.id,'draft_id':draft.id,'account_id':account.id}


def test_publishing_candidates_only_complete_media_but_history_is_preserved(app,client):
    fixed = publication_fixture(app)
    incomplete = character(app,'clips_review')
    complete = character(app,'completed')
    identifier = complete.split(':')[1]
    service = app.state.character
    target = service.folder(identifier)/'final.mp4'
    target.write_bytes(b'SYNTHETIC_UI_BYTES_NOT_REAL_MP4')
    job = service.read(identifier); job['output']={'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    service.save(job)
    missing = video_fixture(app,'합성 누락 영상',exists=False)
    view = client.get('/api/studio/modules/publishing').json()
    expected={fixed['published'],fixed['unpublished'],complete}
    assert {row['id'] for row in view['projects']}==expected
    assert incomplete not in expected and f"news:{missing['id']}" not in expected
    retained={key:view['collections'][key] for key in ('drafts','jobs','calendar','deliveries','cohorts')}
    assert post(client,'remove',[fixed['published'],complete]).status_code==200
    after=client.get('/api/studio/modules/publishing').json()
    assert {row['id'] for row in after['projects']}=={fixed['unpublished']}
    assert {key:after['collections'][key] for key in retained}==retained
    workspace=client.get('/api/studio/workspace').json()
    assert fixed['published'] not in {row['id'] for row in workspace['projects']}
    assert incomplete in {row['id'] for row in workspace['projects']}
    # Query parameters cannot switch the public list back into an archival view.
    assert client.get('/api/studio/workspace?include_library_hidden=true').json()['projects']==workspace['projects']
    assert post(client,'restore',[fixed['published'],complete]).status_code==200
    assert {row['id'] for row in client.get('/api/studio/modules/publishing').json()['projects']}==expected
    assert target.read_bytes()==b'SYNTHETIC_UI_BYTES_NOT_REAL_MP4'


def test_performance_only_confirmed_publication_costs_and_hidden_history_retained(app,client):
    fixed=publication_fixture(app)
    before=client.get('/api/studio/modules/analytics').json()
    assert {row['id'] for row in before['publishedProjects']}=={fixed['published']}
    assert before['publishedProjects'][0]['publications']==[{
        'platform':'youtube','accountId':fixed['account_id'],'jobId':fixed['job_id'],'status':'uploaded'}]
    assert len(before['collections']['metrics'])==1
    assert before['collections']['metrics'][0]['synthetic'] is False
    costs={key:before['collections'][key] for key in ('usage','requests')}
    assert costs['usage'] and costs['requests']
    assert post(client,'remove',[fixed['published'],fixed['unpublished']]).status_code==200
    after=client.get('/api/studio/modules/analytics').json()
    assert after['publishedProjects']==before['publishedProjects']
    assert after['collections']['metrics']==before['collections']['metrics']
    assert {key:after['collections'][key] for key in costs}==costs
    with app.state.sessions() as session:
        assert len(list(session.scalars(select(SocialMetric))))==3
        assert session.get(PublishJob,fixed['job_id']).status=='uploaded'
        assert len(list(session.scalars(select(APIRequestReservation))))==1


def test_approval_simulated_unknown_or_incomplete_receipt_never_claims_publication(app,client):
    fixed=publication_fixture(app)
    with app.state.sessions() as session:
        evidence_id=session.scalar(select(PublishEvidence.id))
    for job_status,changes in [('unvalidated',{}),('unknown',{}),('ext_simulated',{}),
                               ('uploaded',{'synthetic':True}),('uploaded',{'video_id':None}),
                               ('uploaded',{'account_id':None}),('uploaded',{'status':'unknown'})]:
        with app.state.sessions.begin() as session:
            session.get(PublishJob,fixed['job_id']).status=job_status
            session.get(PublishEvidence,evidence_id).payload={
                'job_id':fixed['job_id'],'status':'uploaded','account_id':fixed['account_id'],
                'video_id':'abcdefghijk',**changes}
        view=client.get('/api/studio/modules/analytics').json()
        assert view['publishedProjects']==[] and view['collections']['metrics']==[]
        assert len(view['collections']['usage'])==1 and len(view['collections']['requests'])==1


def test_instagram_image_published_receipt_is_independent_of_library_visibility(app,client):
    ids,_=mixed(app)
    post_id=int(ids[2].split(':')[1])
    with app.state.sessions.begin() as session:
        account=PlatformAccount(platform='instagram',label='Synthetic image account',account_type='business')
        session.add(account);session.flush()
        delivery=ImagePostDelivery(post_id=post_id,account_id=account.id,media_sha256='a'*64,
            status='published_no_link',detail={'media_id':'123456789'})
        session.add(delivery);session.flush();identifier=delivery.id
    assert post(client,'remove',[ids[2]]).status_code==200
    view=client.get('/api/studio/modules/analytics').json()
    assert [row['id'] for row in view['publishedProjects']]==[ids[2]]
    assert view['publishedProjects'][0]['publications'][0]['deliveryId']==identifier
    for state,detail in [('unknown',{'media_id':'123456789'}),('ready',{'media_id':'123456789'}),
                         ('published',{}),('published',{'media_id':'123456789','synthetic':True})]:
        with app.state.sessions.begin() as session:
            row=session.get(ImagePostDelivery,identifier);row.status=state;row.detail=detail
        assert client.get('/api/studio/modules/analytics').json()['publishedProjects']==[]
    with app.state.sessions() as session:
        assert session.get(WorkspaceRemoval,'library:'+ids[2]) is not None


def test_published_receipt_account_survives_draft_edit_but_invalid_accounts_are_rejected(app,client):
    fixed=publication_fixture(app)
    baseline=client.get('/api/studio/modules/analytics').json()
    with app.state.sessions.begin() as session:
        other=PlatformAccount(platform='instagram',label='Another synthetic account',account_type='business')
        session.add(other);session.flush();other_id=other.id
        draft=session.get(PublishDraft,fixed['draft_id'])
        draft.account_id=other_id;draft.platform='instagram'
        evidence=session.scalar(select(PublishEvidence));evidence_id=evidence.id
        original=dict(evidence.payload)
    # A later edit of the reusable draft cannot reassign or erase an earlier publication.
    changed=client.get('/api/studio/modules/analytics').json()
    assert changed['publishedProjects']==baseline['publishedProjects']
    assert changed['collections']['metrics']==baseline['collections']['metrics']
    for invalid in [None,True,0,-1,str(fixed['account_id']),other_id,999999,2**63]:
        with app.state.sessions.begin() as session:
            session.get(PublishEvidence,evidence_id).payload={**original,'account_id':invalid}
        rejected=client.get('/api/studio/modules/analytics').json()
        assert rejected['publishedProjects']==[] and rejected['collections']['metrics']==[]
        assert rejected['collections']['usage']==baseline['collections']['usage']
        assert rejected['collections']['requests']==baseline['collections']['requests']
    with app.state.sessions.begin() as session:
        session.get(PublishEvidence,evidence_id).payload=original
    assert client.get('/api/studio/modules/analytics').json()['publishedProjects']==baseline['publishedProjects']
