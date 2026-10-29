import json
from pathlib import Path
import pytest
from bat_distribution.portable import load_portable
from bat_distribution.lifecycle import Blocked


def configured(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path/'User'))
    root=tmp_path/'Program';root.mkdir()
    raw={'schemaVersion':1,'port':18780,'openBrowser':True}
    (root/'connection.json').write_text(json.dumps(raw))
    layout={'portableFirstRun':True,'validationOnly':False,'updatesEnabled':False}
    return root,raw,layout


def test_fresh_profile_is_separate_and_load_does_not_create_it(tmp_path,monkeypatch):
    root,raw,layout=configured(tmp_path,monkeypatch);c=load_portable(root,layout)
    assert c.profile==tmp_path/'User/AppData/Local/NewsFlowAI-BAT/portable-v1'
    assert not c.profile.exists() and c.port==18780 and c.open_browser

@pytest.mark.parametrize('port',[8765,80,65536,True])
def test_invalid_or_old_operating_port_refused(tmp_path,monkeypatch,port):
    root,raw,layout=configured(tmp_path,monkeypatch);raw['port']=port
    (root/'connection.json').write_text(json.dumps(raw))
    with pytest.raises(Blocked):load_portable(root,layout)

@pytest.mark.parametrize('extra',['profile','programRoot','command','installationId'])
def test_package_cannot_select_data_path_or_command(tmp_path,monkeypatch,extra):
    root,raw,layout=configured(tmp_path,monkeypatch);raw[extra]='foreign'
    (root/'connection.json').write_text(json.dumps(raw))
    with pytest.raises(Blocked):load_portable(root,layout)


def test_unprovisioned_or_updates_enabled_refused(tmp_path,monkeypatch):
    root,raw,layout=configured(tmp_path,monkeypatch);layout['updatesEnabled']=True
    with pytest.raises(Blocked):load_portable(root,layout)
