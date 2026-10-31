"""Synthetic local registry files; no user data, external providers or app startup."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from newsflow.character.registry import CharacterRegistry, CharacterProfile
from newsflow.character.schema import CharacterError
from newsflow.creation.image_studio import ImageStudio


def image(color='blue'):
    out=BytesIO(); Image.new('RGB',(128,128),color).save(out,'PNG'); return out.getvalue()


def profile(name='구름', species='rabbit'):
    return {'name_ko':name,'species':species,'appearance':f'An original {species} with blue clothing.',
            'personality':'아주 신중하지만 손이 빠름','comedy_formula':{'world':'정원','setup':'갑자기 내리는 비','reaction':'커다란 잎을 펼침'},
            'style_lock':'Soft hand painted 3D animation'}


@pytest.fixture
def registry(tmp_path):
    images=ImageStudio(None,tmp_path,None)
    return CharacterRegistry(tmp_path,images), images.asset_bytes(image())


def test_two_profiles_are_isolated_edit_snapshots_and_deletion_preserve_assets(registry,tmp_path):
    service,asset=registry
    first=service.save(profile(),asset)
    second=service.save(profile('별','robot'),asset)
    frozen=service.snapshot(first['id'])
    changed=profile();changed['appearance']='A blue rabbit with a green scarf.'
    updated=service.save(changed,asset,first['id'],first['revision'])
    assert updated['revision']==2 and frozen['revision']==1
    assert service.get(second['id'])['species']=='robot'
    assert frozen['appearance']!=updated['appearance']
    old_job=tmp_path/'character'/'synthetic-job.json';old_job.parent.mkdir()
    old_job.write_text(json.dumps(frozen),encoding='utf8');before=old_job.read_bytes()
    original_image=service.images.asset(asset).read_bytes()
    service.delete(first['id'],2)
    assert [row['id'] for row in service.list()]==[second['id']]
    assert old_job.read_bytes()==before and service.images.asset(asset).read_bytes()==original_image


def test_revision_conflicts_do_not_overwrite_or_delete(registry):
    service,asset=registry
    first=service.save(profile(),asset)
    with pytest.raises(CharacterError,match='이전 요청'):
        service.save(profile('달'),asset,first['id'],expected_revision=0)
    with pytest.raises(CharacterError): service.delete(first['id'],True)
    assert service.get(first['id'])==first


@pytest.mark.parametrize('field',['name_ko','appearance','personality','comedy_formula'])
def test_profile_required_fields(registry,field):
    service,asset=registry; value=profile();value.pop(field)
    with pytest.raises(CharacterError): service.save(value,asset)
    assert service.list()==[]


@pytest.mark.parametrize('change',[{'appearance':'외형'}, {'species':'x\nsecret'}, {'made_for_kids':True},
    {'unexpected':'ignored'}, {'personality':'Bearer secret'}, {'comedy_formula':{'world':'a','setup':'b'}}])
def test_profile_validation_and_secret_text_rejected(registry,change):
    service,asset=registry
    with pytest.raises(CharacterError): service.save({**profile(),**change},asset)


@pytest.mark.parametrize('identifier',['../outside','char_../x','C:\\private','char_'+'A'*32])
def test_registry_rejects_external_identifiers(registry,identifier):
    with pytest.raises(CharacterError): registry[0].get(identifier)


def test_failed_atomic_replace_preserves_previous_profile(registry,monkeypatch):
    service,asset=registry;first=service.save(profile(),asset)
    import newsflow.character.registry as module
    monkeypatch.setattr(module.os,'replace',lambda *a: (_ for _ in ()).throw(OSError('synthetic')))
    with pytest.raises(OSError):service.save(profile('달'),asset,first['id'],1)
    assert service.get(first['id'])==first
    assert not list(service.root.glob('.pending-*'))


def test_cross_user_profile_and_corrupt_asset_rejected(registry,tmp_path):
    service,asset=registry;first=service.save(profile(),asset)
    second=CharacterRegistry(tmp_path/'other',ImageStudio(None,tmp_path/'other',None))
    assert second.list()==[]
    with pytest.raises(CharacterError):second.get(first['id'])
    service.images.asset(asset).write_bytes(b'corrupt')
    with pytest.raises((CharacterError,ValueError)):service.get(first['id'])


def test_profile_folder_reparse_is_rejected(registry,monkeypatch):
    service,asset=registry
    original=Path.is_junction
    monkeypatch.setattr(Path,'is_junction',lambda p: p==service.root or original(p))
    with pytest.raises(CharacterError):service.save(profile(),asset)
