import hashlib
import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from bat_distribution.lifecycle import Blocked
from bat_distribution.restored_install import load_restored, check_restored_profile, RestoredRequests


def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    root=tmp_path/'Program'; root.mkdir()
    base=tmp_path/'AppData/Local/NewsFlowAI-BAT'; base.mkdir(parents=True)
    content=json.dumps({'schemaVersion':2,'profileKind':'restored-private-validation',
        'readOnly':True,'decryptCredentials':False,'programRoot':str(root),
        'installationId':'a'*32,'port':18768,'openBrowser':False}).encode()
    (base/'launch.json').write_bytes(content)
    layout={'validationConfigSha256':hashlib.sha256(content).hexdigest()}
    return root,base,layout


def test_fixed_same_user_restored_location(tmp_path,monkeypatch):
    root,base,layout=configured(tmp_path,monkeypatch)
    result=load_restored(root,layout)
    assert result.profile == base/'v1'
    assert result.profile_kind == 'restored-private-validation'


@pytest.mark.parametrize('field,value',[('readOnly',False),('decryptCredentials',True),('port',8765),('programRoot','C:/different-program')])
def test_refuse_unsafe_restored_configuration(tmp_path,monkeypatch,field,value):
    root,base,layout=configured(tmp_path,monkeypatch)
    file=base/'launch.json'; raw=json.loads(file.read_bytes());raw[field]=value
    file.write_text(json.dumps(raw));layout['validationConfigSha256']=hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(Blocked): load_restored(root,layout)


def test_refuse_tampered_external_configuration(tmp_path,monkeypatch):
    root,base,layout=configured(tmp_path,monkeypatch)
    (base/'launch.json').write_bytes(b'{}')
    with pytest.raises(Blocked,match='integrity'): load_restored(root,layout)


def test_restored_marker_does_not_adopt_foreign_sid(tmp_path,monkeypatch):
    root,base,layout=configured(tmp_path,monkeypatch)
    result=load_restored(root,layout);result.profile.mkdir()
    (result.profile/'restored-install.private.json').write_text(json.dumps({
        'installationId':'a'*32,'ownerSid':'S-1-5-21-1-1002',
        'opaqueCredentialsOnly':True,'sourceDbSha256':'b'*64}))
    with pytest.raises(Blocked,match='owner-or-identity'):
        check_restored_profile(result,'S-1-5-21-1-1001')


async def inner(scope,receive,send):
    await send({'type':'http.response.start','status':200,'headers':[]})
    await send({'type':'http.response.body','body':b'LOCAL'})


@pytest.mark.parametrize('path', ['/api/studio/modules/news','/video/jobs/1/file','/image-posts/1/file'])
def test_cached_local_reads_allowed(path):
    assert TestClient(RestoredRequests(inner)).get(path).status_code==200


@pytest.mark.parametrize('method,path',[('POST','/api/feed-batches/defaults'),('POST','/api/feed-batches/1/step'),('GET','/oauth/callback'),('GET','/news/1/thumbnail')])
def test_writes_and_external_collection_or_auth_routes_refused(method,path):
    boundary=RestoredRequests(inner)
    assert TestClient(boundary).request(method,path).status_code==403
    assert boundary.refused==1
