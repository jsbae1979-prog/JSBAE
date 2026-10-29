"""Synthetic marker checks; these do NOT prove cross-account Windows ACL/DPAPI."""
import json
from pathlib import Path
import pytest
from bat_distribution.portable import portable_profile, prepare_profile
from bat_distribution.windows_live import ValidationConfig
from bat_distribution.lifecycle import Blocked

@pytest.mark.parametrize('field,value',[
    ('ownerSid','S-1-5-21-101-102-103-1002'),
    ('programRoot','FOREIGN_PROGRAM')])
def test_foreign_marker_is_refused_without_adopting_data(tmp_path,monkeypatch,field,value):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path/'SyntheticUser'))
    root=tmp_path/'Program';root.mkdir()
    profile=portable_profile();profile.mkdir(parents=True)
    sid='S-1-5-21-101-102-103-1001'
    from newsflow.distribution import windows_profile
    import win32security
    monkeypatch.setattr(windows_profile,'current_sid',lambda:sid)
    monkeypatch.setattr(windows_profile,'private_directory',lambda path:path)
    monkeypatch.setattr(win32security,'ConvertSidToStringSid',lambda value:value)
    marker={'schemaVersion':1,'installationId':'a'*32,'ownerSid':sid,
            'programRoot':str(root),'profileKind':'portable-local-operation'}
    marker[field]=value
    file=profile/'portable-install.private.json';file.write_text(json.dumps(marker))
    before=file.read_bytes()
    config=ValidationConfig(root,profile,18780,'a'*32,False,'portable-local-operation')
    with pytest.raises(Blocked,match='portable-existing-or-foreign-profile-refused'):
        prepare_profile(config,True)
    assert file.read_bytes()==before
    assert not (profile/'newsflow.db').exists()
