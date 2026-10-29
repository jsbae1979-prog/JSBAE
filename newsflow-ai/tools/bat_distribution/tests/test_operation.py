import hashlib
import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from bat_distribution.operation import load_operating, OperatingRequests
from bat_distribution.lifecycle import Blocked

async def inner(scope,receive,send):
    await send({'type':'http.response.start','status':204,'headers':[]})
    await send({'type':'http.response.body','body':b''})


def configured(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls: tmp_path))
    root=tmp_path/'Program';root.mkdir()
    base=tmp_path/'AppData/Local/NewsFlowAI-BAT';base.mkdir(parents=True)
    raw={'schemaVersion':2,'profileKind':'restored-local-operation','readOnly':False,
         'decryptCredentials':False,'automaticJobsEnabled':False,'externalExecutionEnabled':False,
         'openBrowser':True,'programRoot':str(root),'installationId':'a'*32,'port':18768}
    source=base/'launch.json'
    def write():
        content=json.dumps(raw).encode();source.write_bytes(content)
        return {'localOperationConnected':True,'validationOnly':False,'operatingProfile':'restored-local-operation',
                'updatesEnabled':False,'validationConfigSha256':hashlib.sha256(content).hexdigest()}
    return root,raw,write


def test_explicit_same_user_local_operation(tmp_path,monkeypatch):
    root,raw,write=configured(tmp_path,monkeypatch)
    config=load_operating(root,write())
    assert config.profile_kind=='restored-local-operation' and config.port==18768
    assert config.profile==tmp_path/'AppData/Local/NewsFlowAI-BAT/v1'

@pytest.mark.parametrize('field,value',[('readOnly',True),('decryptCredentials',True),
 ('automaticJobsEnabled',True),('externalExecutionEnabled',True),('port',8765)])
def test_operation_does_not_unlock_external_or_other_modes(tmp_path,monkeypatch,field,value):
    root,raw,write=configured(tmp_path,monkeypatch);raw[field]=value
    with pytest.raises(Blocked):load_operating(root,write())

@pytest.mark.parametrize('method,path',[('POST','/collection'),('POST','/api/feed-batches/1/step'),
 ('POST','/publish/1'),('GET','/oauth/callback')])
def test_external_and_execution_routes_remain_denied(method,path):
    assert TestClient(OperatingRequests(inner)).request(method,path).status_code==403

@pytest.mark.parametrize('path',['/settings/collection','/image-studio/drafts','/character','/ai/drafts/1'])
def test_local_saves_delegate_to_original_auth_and_services(path):
    assert TestClient(OperatingRequests(inner)).post(path).status_code==204


def test_config_requires_explicit_layout_opt_in(tmp_path,monkeypatch):
    root,raw,write=configured(tmp_path,monkeypatch);layout=write();layout['validationOnly']=True
    with pytest.raises(Blocked):load_operating(root,layout)
