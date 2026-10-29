"""PDF model UI contracts, three deliberately synthetic capabilities; no provider calls."""
from copy import deepcopy
from dataclasses import replace
import logging
import pytest
from newsflow.video_models.catalog import (CATALOG,ModelCatalog,CatalogError,GenerationSettings,
    validate,validate_catalog,reconcile,build_request,compose_prompt,styles,character_config,estimate,duration_values)
from newsflow.character.kling import K3,O3,DEFAULTS,validate as validate_character
from newsflow.character.schema import CharacterError

def synthetic():
    doc=CATALOG.refresh();m=deepcopy(doc['models'][0])
    m.update(id='synthetic/full',api_path='synthetic/full',label='Synthetic Full',aspect_ratios=['9:16','16:9'],
             resolutions=['720p','1080p'],default_resolution='1080p',aspect_ratio_mode='native',
             duration={'min':4,'max':15,'step':1,'default':10},
             param_map={'aspect_ratio':'aspect_ratio','resolution':'resolution','duration':'duration','audio':'generate_audio','reference':'image_url'},
             audio_values={'on':True,'off':False})
    mini=deepcopy(m);mini.update(id='synthetic/mini',api_path='synthetic/mini',label='Synthetic Mini',
            recommended=False,resolutions=['720p'],default_resolution='720p',audio={'native':False,'voice_select':False})
    mini['param_map']['audio']=None
    fixed=deepcopy(m);fixed.update(id='synthetic/fixed',api_path='synthetic/fixed',label='Synthetic Fixed',recommended=False,
        duration={'options':[4,6,8],'default':8},aspect_ratios=['16:9'],default_aspect_ratio='16:9')
    fixed['param_map']['audio']='sound';fixed['audio_values']={'on':'on','off':'off'}
    return {**doc,'models':[m,mini,fixed]}

def local(doc):return ModelCatalog(loader=lambda _:deepcopy(doc))
def settings(**kw):return GenerationSettings(**{'model_id':'synthetic/full','aspect_ratio':'9:16','resolution':'1080p',
    'duration':10,'style_id':'3d_animation','audio':True,**kw})

def test_only_two_user_approved_models_are_shipped_and_config_drives_choices():
    rows=CATALOG.refresh()['models'];assert [m['id'] for m in rows if m['enabled']]==[K3,O3]
    assert next(m for m in rows if m['recommended'])['id']==K3
    assert character_config()['aspect_ratio']=='9:16'
    assert character_config()['style_id'] in styles()

@pytest.mark.parametrize('field',['id','api_path','param_map','audio','duration','pricing_ref','enabled','resolutions'])
def test_missing_fields_are_rejected(field):
    doc=synthetic();del doc['models'][0][field]
    with pytest.raises(CatalogError):validate_catalog(doc)

@pytest.mark.parametrize('change',['extra','duplicate','invalid_resolution','audio_pointer','pro','invalid_duration','untrusted_docs','unknown_audio'])
def test_unknown_or_unsafe_catalog_values_are_rejected(change):
    doc=synthetic();m=doc['models'][0]
    if change=='extra':m['extra']='not allowed'
    elif change=='duplicate':doc['models'].append(deepcopy(m))
    elif change=='invalid_resolution':m['resolutions']=['8k']
    elif change=='audio_pointer':m['param_map']['audio']='raw_function'
    elif change=='pro':m['fixed_params']['mode']='pro'
    elif change=='invalid_duration':m['duration']['step']=0
    elif change=='untrusted_docs':m['docs_ref']='https://outside.invalid/schema'
    else:m['audio']['voice_select']=True
    with pytest.raises(CatalogError):validate_catalog(doc)

def test_startup_once_24h_refresh_failure_preserves_last_good_catalog(caplog):
    clock=[0];calls=[];doc=synthetic()
    def load(_):
        calls.append(1)
        if len(calls)>1:raise OSError('synthetic unavailable')
        return doc
    c=ModelCatalog(loader=load,clock=lambda:clock[0]);first=c.refresh()
    assert len(calls)==1
    clock[0]=86401
    with caplog.at_level(logging.WARNING):again=c.refresh()
    assert again==first and len(calls)==2 and c.warning
    assert '마지막 정상' in caplog.text
    assert c.refresh()==first and len(calls)==2

def test_reduced_options_are_warned_without_overwriting_user_jobs(caplog):
    docs=[synthetic()];c=ModelCatalog(loader=lambda _:docs[0]);old=c.refresh()
    docs[0]=deepcopy(old);docs[0]['models'][0]['resolutions']=['720p'];docs[0]['models'][0]['default_resolution']='720p'
    with caplog.at_level(logging.WARNING):c.refresh(force=True)
    assert '지원 옵션 축소' in caplog.text and old['models'][0]['resolutions']==['720p','1080p']

def test_three_models_adjust_only_unsupported_values_and_emit_field_notes():
    c=local(synthetic());s=settings()
    kept,notes=reconcile(s,c);assert kept==s and not notes
    mini,notes=reconcile(replace(s,model_id='synthetic/mini'),c)
    assert mini.resolution=='720p' and mini.audio is False and mini.duration==10
    assert set(notes)=={'resolution','audio'}
    fixed,notes=reconcile(replace(mini,model_id='synthetic/fixed',duration=10),c)
    assert fixed.duration==8 and fixed.aspect_ratio=='16:9' and fixed.resolution=='720p'
    assert set(notes)=={'duration','aspect_ratio'}

def test_same_settings_use_model_specific_audio_parameter_names_and_types():
    c=local(synthetic())
    a=build_request(settings(), 'A character walks.',c,reference_url='https://example.com/ref.png')
    assert a['body']['generate_audio'] is True and a['body']['resolution']=='1080p'
    b=build_request(settings(model_id='synthetic/fixed',aspect_ratio='16:9',duration=8),'walk',c)
    assert b['body']['sound']=='on' and 'generate_audio' not in b['body']
    off=build_request(settings(model_id='synthetic/mini',resolution='720p',audio=False),'walk',c)
    assert 'sound' not in off['body'] and 'generate_audio' not in off['body']

def test_prefix_suffix_and_character_style_priority_and_warning_are_data_driven():
    s=styles()['realistic'];text=compose_prompt('realistic','SCENE')
    assert s['prefix'] in text and s['suffix'] in text and s['warn']
    cfg=character_config();frozen=compose_prompt('realistic','SCENE',character=cfg)
    assert cfg['appearance'] in frozen and cfg['style_lock'] in frozen and s['prefix'] not in frozen

@pytest.mark.parametrize('change',[{'resolution':'4k'},{'duration':16},{'aspect_ratio':'21:9'},
   {'model_id':'missing'},{'audio':'true'},{'style_id':'unknown'}])
def test_server_rejects_unsupported_combination_before_request_build(change):
    c=local(synthetic());s=settings(**change)
    assert validate(s,c)
    with pytest.raises(CatalogError):build_request(s,'walk',c)

def test_disabled_model_is_hidden_and_not_automatically_replaced():
    doc=synthetic();doc['models'][0]['enabled']=False;c=local(doc)
    assert c.model('synthetic/full') is None
    with pytest.raises(CatalogError):reconcile(settings(),c)

@pytest.mark.parametrize('key,value',[('style','realistic'),('aspect_ratio','16:9'),('native_resolution','1080p')])
def test_character_lock_is_also_enforced_on_server(key,value):
    with pytest.raises(CharacterError):validate_character({**DEFAULTS,key:value})

def test_public_price_is_estimate_only_and_unverified_audio_price_is_not_invented():
    s=GenerationSettings(K3,'9:16','model_default',11,'3d_animation',False)
    e=estimate(s,55);assert e['minimum']=='4.620' and e['maximum']=='6.930' and not e['official_quote']
    o=estimate(replace(s,model_id=O3,resolution='std',audio=True),55)
    assert o['maximum'] is None and not o['audio_price_verified']


@pytest.mark.parametrize('quality',['std','pro','4k'])
def test_official_o3_quality_modes_are_explicit_api_modes(quality):
    m=CATALOG.model(O3)
    assert m['resolutions']==['std','pro','4k'] and m['default_resolution']=='std'
    s=GenerationSettings(O3,'9:16',quality,11,'3d_animation',False)
    request=build_request(s,'walk',reference_url='https://example.com/ref.png')
    assert request['path']==O3 and request['body']['mode']==quality
    assert not {'resolution','quality'} & request['body'].keys()
    if quality!='std':assert estimate(s,55)['maximum'] is None


def test_standard_k3_quality_is_fixed_and_never_promoted():
    m=CATALOG.model(K3)
    assert m['resolutions']==['model_default'] and m['param_map']['resolution'] is None
    s=GenerationSettings(K3,'9:16','model_default',11,'3d_animation',False)
    assert not {'mode','resolution','quality'} & build_request(s,'walk')['body'].keys()
    for value in ['std','pro','720p','1080p','4k']:
        assert validate(replace(s,resolution=value))


@pytest.mark.parametrize('previous',['model_default','720p','1080p'])
def test_switching_to_o3_uses_standard_without_automatic_upgrade(previous):
    s=GenerationSettings(O3,'9:16',previous,11,'3d_animation',False)
    adjusted,notes=reconcile(s)
    assert adjusted.resolution=='std' and 'resolution' in notes
