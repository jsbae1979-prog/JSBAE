import json
import pytest
from bat_distribution.portable_package import release
from bat_distribution.zip_update import payload_name
from bat_distribution.lifecycle import Blocked


def test_only_explicit_public_connection_file_is_added():
    assert payload_name('connection.json')=='connection.json'
    for name in ['profile.json','credentials.json','private/connection.json','newsflow.db']:
        with pytest.raises(Blocked):payload_name(name)


def test_release_has_no_restored_profile_identity_and_keeps_updates_disabled(tmp_path):
    root=tmp_path/'Program';(root/'app/product').mkdir(parents=True)
    (root/'app/product/demo.py').write_text('# synthetic')
    (root/'connection.json').write_text('{"schemaVersion":1,"port":18780,"openBrowser":true}')
    release(root,'1.0.0','a'*40)
    layout=json.loads((root/'app/layout.json').read_bytes())
    assert layout['portableFirstRun'] is True and layout['updatesEnabled'] is False
    assert 'validationConfigSha256' not in layout and 'operatingProfile' not in layout
    assert not any(r['path']=='connection.json' for r in layout['files'])
