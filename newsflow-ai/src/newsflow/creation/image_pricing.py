"""Offline estimate for direct, text-only GPT Image 2.5 generation.

This is an application budgeting estimate, NOT a provider-enforced charge cap.
The published calculator estimates image output; prompt bytes conservatively
estimate input tokens. Actual response usage and provider invoices differ.
No remote calls, credentials, client-supplied prices or cached-input discounts.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from math import ceil

from .catalog import IMAGE_MODELS, validate
from newsflow.publishing.service import PublishingError

VERSION = 'openai-image-2.5-standard-2026-11-01-v1'
SOURCE = 'https://developers.openai.com/api/docs/guides/image-generation'
PRICING_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-image-2.5-flare'
CALCULATOR_SOURCE = 'https://developers.openai.com/_astro/GptImageTokenCalculator.react.FCse3GSx.js'
VALID_UNTIL = datetime(2026,12,1,tzinfo=timezone.utc).timestamp()
TEXT_RATE = Decimal('5')
OUTPUT_RATE = Decimal('30')
MAX_PROMPT_BYTES = 32000

def current(now):
    return datetime(2026,11,1,tzinfo=timezone.utc).timestamp() <= now < VALID_UNTIL

def output_tokens(size,quality):
    # Independently expressed arithmetic from the public calculator: ties to
    # even, scaled aspect-ratio grid, then pixel-area multiplier and ceiling.
    try:
        width,height=map(int,size.split('x'))
        grid={'low':16,'medium':24,'high':48}[quality]
        if (width%16 or height%16 or min(width,height)<=0 or max(width,height)>3840
                or not 655360<=width*height<=8294400 or max(width,height)>3*min(width,height)):
            raise ValueError
        short=round(Fraction(grid*min(width,height),max(width,height)))
        return ceil(Fraction(grid*short*(2000000+width*height),4000000))
    except (ValueError,KeyError,TypeError,AttributeError):
        raise PublishingError('지원되는 이미지 크기·품질을 선택하세요.') from None

def estimate(selection,prompt,*,now):
    selected=validate('image',{k:selection[k] for k in ('provider','model','size','quality')})
    if selected['model'] not in IMAGE_MODELS or not current(now):
        raise PublishingError('공식 이미지 단가의 확인 기간이 만료됐습니다. 새 단가 확인이 필요합니다.')
    if not isinstance(prompt,str) or not 0<len(prompt.encode('utf8'))<=MAX_PROMPT_BYTES:
        raise PublishingError('이미지 요청의 문구 길이를 확인하세요.')
    incoming=len(prompt.encode('utf8'))
    outgoing=output_tokens(selected['size'],selected['quality'])
    amount=(TEXT_RATE*incoming+OUTPUT_RATE*outgoing)/Decimal(1000000)
    # Keep a disclosed 2x planning reserve, rounded upwards to one US cent.
    # Even this reserve cannot guarantee the supplier's final charge.
    reserve=(amount*2).quantize(Decimal('0.01'),rounding=ROUND_CEILING)
    return {'basis':'app_budget_estimate','pricingVersion':VERSION,
            'estimatedUsd':str(amount),'reserveUsd':str(reserve),
            'estimatedInputTokens':incoming,'estimatedOutputTokens':outgoing,
            'inputBasis':'utf8_bytes_estimate','reserveMultiplier':'2',
            'providerChargeCap':False,'billingVerified':False,
            'source':SOURCE,'pricingSource':PRICING_SOURCE}

def usage_cost(usage):
    """Only direct text-only requests; usage cost is not an invoice."""
    if not isinstance(usage,dict):return None
    if any(type(usage.get(k)) is not int or not 0<=usage[k]<=10000000
           for k in ('input_tokens','output_tokens','total_tokens')):return None
    if usage['input_tokens']+usage['output_tokens']!=usage['total_tokens']:return None
    return str((TEXT_RATE*usage['input_tokens']+OUTPUT_RATE*usage['output_tokens'])/Decimal(1000000))
