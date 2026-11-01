from datetime import datetime,timezone
from copy import deepcopy
import pytest
from newsflow.creation.catalog import DEFAULTS, IMAGE_MODELS
from newsflow.creation.image_pricing import estimate,output_tokens,usage_cost,VALID_UNTIL
from newsflow.publishing.service import PublishingError

NOW=datetime(2026,11,1,tzinfo=timezone.utc).timestamp()

@pytest.mark.parametrize('model',IMAGE_MODELS)
@pytest.mark.parametrize('size',['1024x1024','1024x1280','1024x1536'])
@pytest.mark.parametrize('quality',['low','medium','high'])
def test_offline_supported_combinations(model,size,quality):
    from decimal import Decimal
    s={**DEFAULTS['image'],'model':model,'size':size,'quality':quality}
    result=estimate(s,'한글 synthetic news',now=NOW)
    assert Decimal(result['reserveUsd'])>=Decimal(result['estimatedUsd'])*2
    assert result['estimatedInputTokens']==len('한글 synthetic news'.encode())
    assert not result['providerChargeCap'] and not result['billingVerified']

def test_published_calculator_square_low_example():
    assert output_tokens('1024x1024','low')==196

@pytest.mark.parametrize('prompt',['','a'*32001])
def test_prompt_limits(prompt):
    with pytest.raises(PublishingError):estimate(DEFAULTS['image'],prompt,now=NOW)

def test_expired_rates_block_estimate():
    with pytest.raises(PublishingError):estimate(DEFAULTS['image'],'news',now=VALID_UNTIL)

def test_usage_cost_never_infers_zero_from_unknown_or_invalid():
    assert usage_cost(None) is None
    assert usage_cost({'input_tokens':False,'output_tokens':1,'total_tokens':1}) is None
    assert usage_cost({'input_tokens':10,'output_tokens':20,'total_tokens':29}) is None
    assert usage_cost({'input_tokens':100,'output_tokens':1000,'total_tokens':1100})=='0.0305'
