"""Separate image-only HTTPS delivery. All HTTP is in-process/Fake; no deployment."""
import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_image_posts import delivery_setup, make_post

from newsflow.db.models import AppSetting
from newsflow.intelligence.credentials import FakeCipher
from newsflow.publishing.image_delivery import HTTPSImageDelivery, ImageDeliveryKeys, delivery_origin
from newsflow.publishing.image_delivery_server import cleanup_expired, create_delivery_app, validate_jpeg
from newsflow.publishing.service import PublishingError

SECRET='synthetic_only_upload_key_abcdefghijklmnopqrstuvwxyz'
ORIGIN='https://images.example.com'


def jpg():
    buf=BytesIO()
    Image.new('RGB',(1080,1350),'#224466').save(buf,format='JPEG')
    return buf.getvalue()


@pytest.mark.parametrize('url',['http://example.com','https://127.0.0.1/','https://example.com/?token=secret',
                                 'https://user:secret@example.com/','https://example.com/files'])
def test_https_origin_no_credentials_or_private_host(url):
    with pytest.raises((PublishingError,ValueError)):
        delivery_origin(url)


def test_image_only_https_secret_expiry_and_cleanup(tmp_path):
    now=[1000]
    root=tmp_path/'images'
    app=create_delivery_app(root,ORIGIN+'/',SECRET,ttl_seconds=900,clock=lambda:now[0])
    with TestClient(app,base_url=ORIGIN) as client:
        headers={'Authorization':'Bearer '+SECRET,'Content-Type':'image/jpeg'}
        assert client.post('/v1/images',content=jpg()).status_code==401
        assert client.post('/v1/images',content=b'MP4',headers=headers).status_code==422
        assert client.post('/v1/images',content=jpg(),headers={**headers,'Content-Type':'video/mp4'}).status_code==415
        response=client.post('/v1/images',content=jpg(),headers=headers)
        assert response.status_code==200 and SECRET not in response.text
        result=response.json()
        assert result['sha256']==hashlib.sha256(jpg()).hexdigest()
        fetched=client.get(result['url'])
        assert fetched.content==jpg() and fetched.headers['cache-control']=='no-store'
        assert client.get('/images/keys.dpapi').status_code==404
        assert client.get('/images/newsflow.db').status_code==404
        assert client.get('/robots.txt').status_code==200
        now[0]=1900
        assert client.get(result['url']).status_code==410
        cleanup_expired(root,now[0])
        assert not list(root.iterdir())
    with TestClient(app,base_url='http://images.example.com') as client:
        assert client.post('/v1/images',content=jpg(),headers=headers).status_code==400


def test_validation_does_not_accept_png_metadata_or_oversize():
    with pytest.raises(PublishingError):
        validate_jpeg(b'a'*(8*1024*1024+1))
    buf=BytesIO()
    Image.new('RGB',(1080,1350)).save(buf,format='PNG')
    with pytest.raises(PublishingError):
        validate_jpeg(buf.getvalue())
    image=Image.new('RGB',(1080,1350))
    exif=Image.Exif(); exif[270]='private'
    buf=BytesIO(); image.save(buf,format='JPEG',exif=exif)
    with pytest.raises(PublishingError):
        validate_jpeg(buf.getvalue())


def test_delivery_keys_separate_dpapi_file(tmp_path):
    store=ImageDeliveryKeys(tmp_path,FakeCipher())
    store.save(SECRET)
    assert store.key()==SECRET and store.path.name=='feed-delivery-key.dpapi'
    assert SECRET.encode() not in store.path.read_bytes()
    assert not (tmp_path/'ai-key.dpapi').exists()


def test_missing_server_blocks_before_any_upload_or_journal(app):
    post=make_post(app)
    service,account=delivery_setup(app,post)
    with pytest.raises(PublishingError,match='BLOCKED'):
        service.prepare(post,account,'',consent=True)
    assert not service.deliveries(post) and not service.adapter.calls


def test_delivery_once_journal_before_upload_uncertain_never_replays(app):
    post=make_post(app)
    service,account=delivery_setup(app,post)
    calls=[]
    def upload(path,digest):
        assert service.deliveries(post)[0].status=='preparing'
        calls.append(digest)
        raise TimeoutError('private secret')
    service.delivery=SimpleNamespace(ready=lambda:True,upload=upload)
    identifier=service.prepare(post,account,'',consent=True)
    row=service._delivery(identifier)
    assert row.status=='unknown' and row.detail['error_code']=='image_delivery_unknown'
    assert 'private' not in str(row.detail)
    service.recover()
    with pytest.raises(PublishingError): service.prepare(post,account,'',consent=True)
    assert len(calls)==1 and not service.adapter.calls


def test_delivery_client_feed_publish_contract_and_independent_video_history(app, tmp_path):
    post=make_post(app)
    service,account=delivery_setup(app,post)
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key='feed_delivery_origin',value=ORIGIN+'/'))
    calls=[]
    def transport(origin,raw,key):
        calls.append((origin,hashlib.sha256(raw).hexdigest()))
        assert key==SECRET
        return {'url':origin+'/images/'+'a'*32+'.jpg','sha256':hashlib.sha256(raw).hexdigest()}
    service.delivery=HTTPSImageDelivery(app.state.sessions,tmp_path,
        keys=SimpleNamespace(status=lambda:{'configured':True},key=lambda:SECRET),transport=transport)
    identifier=service.prepare(post,account,'',consent=True)
    assert service._delivery(identifier).status=='processing'
    service.check(identifier,consent=True)
    with pytest.raises(PublishingError): service.publish(identifier)
    service.publish(identifier,public_consent=True)
    assert service._delivery(identifier).status=='published'
    assert service._delivery(identifier).detail['upload_sha256']==service.get(post).sha256
    with pytest.raises(PublishingError): service.publish(identifier,public_consent=True)
    assert len(calls)==1 and service.adapter.calls==['create','status','publish','result']
    from sqlalchemy import func, select

    from newsflow.db.models import PublishJob
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishJob))==0
