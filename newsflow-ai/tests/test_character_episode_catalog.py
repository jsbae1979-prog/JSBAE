from copy import deepcopy
import pytest
from newsflow.character.kling import catalog,validate,DEFAULTS,O3
from newsflow.video_models.catalog import CATALOG,validate_catalog,ModelCatalog,GenerationSettings,build_request

def test_new_episode_length_choices_are_independent_of_model_clip_duration():
    c=catalog()
    assert c['totalDurationChoices']==list(range(15,61,5))
    assert c['defaults']['duration']==30 and c['defaults']['sound']=='on'
    for target in (15,35,60):
        assert validate({**DEFAULTS,'duration':target,'script_model':'gpt-4.1-mini'})['duration']==target

def test_catalog_supplies_continuation_field_and_parameter_map():
    c=deepcopy(CATALOG.refresh());item=deepcopy(c['models'][0])
    item.update(id='synthetic/model',api_path='synthetic/model',label='Synthetic model',recommended=False)
    item['param_map'].update(reference='start_image',audio='generate_audio')
    item['audio_values']={'on':True,'off':False};item['continuation_param']='start_image'
    c['models'].append(item);validate_catalog(c)
    models=ModelCatalog(loader=lambda path:c)
    settings=GenerationSettings(item['id'],'9:16',item['default_resolution'],item['duration']['default'],None,True)
    payload=build_request(settings,'Silent physical comedy',models,reference_url='https://example.com/ref.png')
    assert payload['body']['start_image'].endswith('/ref.png')
    assert payload['body']['generate_audio'] is True

def test_invalid_continuation_pointer_is_rejected():
    c=deepcopy(CATALOG.refresh());c['models'][0]['continuation_param']='arbitrary_url'
    with pytest.raises(ValueError):validate_catalog(c)
