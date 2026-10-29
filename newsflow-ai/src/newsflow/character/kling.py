"""Model-specific Higgsfield contracts, public schemas checked 2026-10-29.

Standard is the default; only an explicit O3 quality selection requests Pro/4K.
Style is our prompt preset; output size is local FFmpeg output, not native quality.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
from PIL import Image, ImageOps
from newsflow.intelligence.api_providers import API_MODELS
from .schema import CharacterError
from .higgsfield_client import HiggsfieldVideoClient, amount, reference_bytes
from newsflow.video.ai.download import safe_url

K3 = 'kling-video/v3.0/std/image-to-video'
O3 = 'kling-video/o3/image-reference'
from newsflow.video_models.catalog import (CATALOG,GenerationSettings,build_request,character_config,
    styles,duration_values,validate as validate_generation,estimate as estimate_generation)
MODELS={m['id']:m['label'] for m in CATALOG.refresh()['models'] if m['enabled']}
STYLES={k:s['label'] for k,s in styles().items()}
RATIOS={'9:16':'9:16 (쇼츠)','16:9':'16:9 (가로)','1:1':'1:1 (정사각형)'}
OUTPUTS={'720p':'720p 출력','1080p':'1080p 출력 · 로컬 확대 가능','4k':'4K (2160p) 출력 · 로컬 확대 가능'}
CHARACTER=character_config()
RECOMMENDED=next((m for m in CATALOG.refresh()['models'] if m['enabled'] and m['recommended']),
                 next(m for m in CATALOG.refresh()['models'] if m['enabled']))
DEFAULTS={'video_model':RECOMMENDED['id'],'style':CHARACTER['style_id'],'aspect_ratio':CHARACTER['aspect_ratio'],
          'native_resolution':RECOMMENDED['default_resolution'],'output_quality':CHARACTER['output_quality'],
          'sound':'on' if CHARACTER['audio_default'] else 'off','clip_seconds':CHARACTER['clip_seconds'],
          'duration':CHARACTER['clip_seconds']*5,'script_model':'claude-sonnet-4-6'}

def as_generation(value,seconds=None):
    # Historical O3 snapshots used model_default for the same explicit std mode.
    # Resolve the alias at execution only; never rewrite frozen settings or quotes.
    quality='std' if value['video_model']==O3 and value['native_resolution']=='model_default' else value['native_resolution']
    return GenerationSettings(value['video_model'],value['aspect_ratio'],quality,
                              value['clip_seconds'] if seconds is None else seconds,value['style'],value['sound']=='on')

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULTS):raise CharacterError()
    v=dict(value)
    try:
        issues=validate_generation(as_generation(v))
        if (issues or v['style']!=CHARACTER['style_id'] or v['aspect_ratio']!=CHARACTER['aspect_ratio']
                or v['output_quality'] not in OUTPUTS or v['sound'] not in {'on','off'}
                or type(v['duration']) is not int or not 15<=v['duration']<=60 or v['duration']%5
                or v['duration']!=5*v['clip_seconds']
                or v['script_model'] not in API_MODELS['claude_api']):raise ValueError
    except (ValueError,KeyError,TypeError,ZeroDivisionError):raise CharacterError() from None
    return v

def field_errors(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULTS):return {'settings':'설정 항목을 확인하세요.'}
    result={}
    try:
        for error in validate_generation(as_generation(value)):
            key,_,text=error.partition(':')
            field={'model_id':'video_model','resolution':'native_resolution','duration':'clip_seconds','audio':'sound','style_id':'style'}.get(key,key)
            result[field]=text.strip()
        if value['style']!=CHARACTER['style_id']:result['style']='캐릭터 설정의 스타일로 고정됩니다.'
        if value['aspect_ratio']!=CHARACTER['aspect_ratio']:result['aspect_ratio']='캐릭터 쇼츠는 9:16으로 고정됩니다.'
        try:validate(value)
        except CharacterError:
            if not result:result['settings']='영상 길이·모델·설정 조합을 확인하세요.'
    except (KeyError,TypeError,ValueError):result['settings']='설정 형식을 확인하세요.'
    return result

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def snapshot(value):
    result={'version': 2, **validate(value), 'checked_on':'2026-10-29'}
    result['fingerprint']=fingerprint(result)
    return result

def check(value):
    if (not isinstance(value,dict) or value.get('version')!=2
            or value.get('fingerprint') != fingerprint({k:v for k,v in value.items() if k!='fingerprint'})
            or set(value) != set(DEFAULTS)|{'version','checked_on','fingerprint'}):
        raise CharacterError()
    selected={k:value[k] for k in DEFAULTS}
    # Historical snapshots remain readable if today's catalog changes. Execution revalidates live capabilities.
    if (any(not isinstance(selected[k],str) or len(selected[k])>180 for k in DEFAULTS if k not in {'clip_seconds','duration'})
            or type(selected['clip_seconds']) is not int or type(selected['duration']) is not int):raise CharacterError()
    return selected

def dimensions(value):
    v=validate(value)
    short={'720p':720,'1080p':1080,'4k':2160}[v['output_quality']]
    return {'9:16':(short,short*16//9), '16:9':(short*16//9,short), '1:1':(short,short)}[v['aspect_ratio']]

def catalog():
    data=CATALOG.refresh()
    models=[{**m,'duration_values':duration_values(m)} for m in data['models'] if m['enabled']]
    return {'version':2,'models':{m['id']:m['label'] for m in models},'modelsDetailed':models,'defaults':DEFAULTS,
            'styles':STYLES,'stylePresets':list(styles().values()),'ratios':RATIOS,'character':CHARACTER,
            'outputQualities':OUTPUTS,'sounds':{'off':'끄기 (무음)','on':'켜기'},
            'capabilities':{m['id']:{'ratio':m['aspect_ratio_mode'],'quality':m['quality_note']} for m in models},
            'revision':fingerprint(data),'resolutionChoices':['std','pro','480p','720p','1080p','4k'],
            'durationChoices':sorted(set(n for m in models for n in duration_values(m))),
            'cacheWarning':CATALOG.warning,'accountVerified':False,'nativeVoiceSelection':False}

def normalize_reference(raw):
    """Own PNG derivative. Original user files are never edited."""
    try:
        if not 1 <= len(raw) <= 10*1024*1024: raise ValueError
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {'PNG','JPEG'} or not (128<=im.width<=4096 and 128<=im.height<=4096):
                raise ValueError
            im.load()
            dest=io.BytesIO()
            ImageOps.exif_transpose(im).convert('RGB').save(dest,format='PNG')
        if len(dest.getvalue())>10*1024*1024: raise ValueError
        return dest.getvalue()
    except (OSError,ValueError,Image.DecompressionBombError):
        raise CharacterError('reference') from None

def generation_reference(folder:Path, settings):
    """Kling 3 I2V has no aspect_ratio field. Pad a separate input, preserve character."""
    original=folder/'reference.png'
    reference_bytes(original)
    model=CATALOG.model(settings['video_model'])
    if not model:raise CharacterError('blocked')
    if model['aspect_ratio_mode']=='native':
        return original
    target=folder/'generation-reference.png'
    if target.is_symlink() or target.is_junction(): raise CharacterError('reference')
    width,height=dimensions({**settings,'output_quality':'720p'})
    with Image.open(original) as im:
        ImageOps.pad(im.convert('RGB'),(width,height),color='#09172a').save(target,format='PNG')
    return target

class KlingClient(HiggsfieldVideoClient):
    def __init__(self, credential, settings, **kwargs):
        super().__init__(credential, **kwargs)
        self.settings=validate(settings)
        self.model=self.settings['video_model']

    def payload(self, prompt, seconds, reference):
        if not isinstance(prompt,str) or len(prompt)>4500:raise CharacterError()
        g=as_generation(self.settings,seconds)
        # The service froze the character/style prompt in jobs.json before quoting.
        request=build_request(GenerationSettings(g.model_id,g.aspect_ratio,g.resolution,g.duration,None,g.audio),
                              prompt,reference_url=safe_url(reference))
        return request['body']

    def estimate(self, payload):
        return str(amount(self._safe_call('POST','/estimate/'+self.model,payload).get('usd')))
