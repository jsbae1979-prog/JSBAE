"""One strict catalog for UI, reconciliation and request building.

Configuration is JSON syntax, a YAML 1.2 subset. This intentionally needs no new
runtime/wheel dependency or executable YAML tags. Public schemas are maintained
manually because no authenticated discovery call is authorized/assumed.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
import json,logging,re,time
from threading import RLock
from pathlib import Path
LOG=logging.getLogger(__name__)
CONFIG=Path(__file__).parents[1]/'config'
class CatalogError(ValueError):pass

def load_document(path):
    try:
        if path.is_symlink() or path.is_junction() or path.stat().st_size>200000:raise ValueError
        return json.loads(path.read_text(encoding='utf8'))
    except (ValueError,OSError):raise CatalogError('모델 설정 파일 형식·위치를 확인하세요.') from None

def _strings(values,allowed=None):
    return isinstance(values,list) and bool(values) and all(isinstance(x,str) for x in values) and len(values)==len(set(values)) and all(
        x in allowed if allowed else len(x)<180 for x in values)

def validate_catalog(document):
    if (not isinstance(document,dict) or set(document)!={'schema_version','source','checked_on','models'}
            or type(document['schema_version']) is not int or document['schema_version']!=1 or not isinstance(document['models'],list) or not document['models']):
        raise CatalogError('모델 카탈로그 필수 항목을 확인하세요.')
    expected={'id','label','provider','api_path','enabled','recommended','reference_image','resolutions',
        'default_resolution','duration','audio','checked_on','quality_note','pricing_ref','aspect_ratios',
        'default_aspect_ratio','aspect_ratio_mode','param_map','fixed_params','audio_values','docs_ref','pricing'}
    ids=set()
    for m in document['models']:
        if not isinstance(m,dict) or set(m)!=expected:raise CatalogError('모델의 누락·알 수 없는 항목을 확인하세요.')
        if (not isinstance(m['id'],str) or not re.fullmatch(r'[a-z0-9][a-z0-9/._-]{1,160}',m['id']) or '..' in m['id']
                or m['id'] in ids or m['api_path']!=m['id'] or m['provider']!='higgsfield'
                or any(type(m[k]) is not bool for k in ['enabled','recommended','reference_image'])
                or not isinstance(m['label'],str) or not 1<=len(m['label'])<=100):
            raise CatalogError('모델 ID·경로·활성 상태를 확인하세요.')
        ids.add(m['id'])
        if (not _strings(m['aspect_ratios'],{'9:16','16:9','1:1','4:3','3:4','21:9'})
                or m['default_aspect_ratio'] not in m['aspect_ratios']
                or not _strings(m['resolutions'],{'model_default','480p','720p','1080p','4k'})
                or m['default_resolution'] not in m['resolutions']
                or m['aspect_ratio_mode'] not in {'native','reference-padding'}):raise CatalogError('모델 선택지를 확인하세요.')
        duration_values(m)
        if (not isinstance(m['audio'],dict) or set(m['audio'])!={'native','voice_select'}
                or any(type(v) is not bool for v in m['audio'].values()) or m['audio']['voice_select']):
            raise CatalogError('소리 생성 기능을 확인하세요. 목소리 선택은 지원하지 않습니다.')
        pm=m['param_map']
        if not isinstance(pm,dict) or set(pm)!={'aspect_ratio','resolution','duration','audio','reference'}:
            raise CatalogError('param_map 항목을 확인하세요.')
        allowed={None,'aspect_ratio','resolution','duration','sound','generate_audio','image_url','image_urls'}
        if any(x not in allowed for x in pm.values()) or pm['duration']!='duration' or pm['reference'] not in {'image_url','image_urls'}:
            raise CatalogError('지원하지 않는 파라미터 매핑입니다.')
        if (m['audio']['native'] and pm['audio'] not in {'sound','generate_audio'}) or (not m['audio']['native'] and pm['audio'] is not None):
            raise CatalogError('소리 파라미터 매핑을 확인하세요.')
        expected_audio={'on':'on','off':'off'} if pm['audio']=='sound' else {'on':True,'off':False}
        if m['audio_values']!=expected_audio:raise CatalogError('소리 값 형식을 확인하세요.')
        if (not isinstance(m['fixed_params'],dict) or set(m['fixed_params'])-{'mode','shot_type','multi_shots'}
                or m['fixed_params'].get('mode','std')!='std'
                or m['fixed_params'].get('shot_type','customize')!='customize'
                or m['fixed_params'].get('multi_shots',False) is not False):raise CatalogError('고정 Standard 파라미터를 확인하세요.')
        for key in ('docs_ref','pricing_ref'):
            if not isinstance(m[key],str) or not m[key].startswith('https://open.higgsfield.ai/'):
                raise CatalogError('공식 문서 출처를 확인하세요.')
        p=m['pricing']
        if (not isinstance(p,dict) or set(p)!={'currency','basis','per_second','audio_price_verified','note'}
                or p['currency']!='USD' or set(p['per_second'])!={'on','off'}
                or type(p['audio_price_verified']) is not bool):raise CatalogError('단가 근거를 확인하세요.')
        for rate in p['per_second'].values():
            if rate is None:continue
            try:
                if len(rate)!=2 or any(not Decimal(x).is_finite() or Decimal(x)<0 for x in rate) or Decimal(rate[0])>Decimal(rate[1]):raise ValueError
            except (ValueError,TypeError,InvalidOperation):raise CatalogError('단가 범위를 확인하세요.') from None
    if not any(m['enabled'] for m in document['models']):raise CatalogError('활성 모델이 없습니다.')
    return deepcopy(document)

def duration_values(model):
    d=model['duration']
    if not isinstance(d,dict):raise CatalogError('영상 길이 정의가 필요합니다.')
    if set(d)=={'options','default'}:
        v=d['options']
        if not isinstance(v,list) or not v or any(type(n) is not int or not 1<=n<=120 for n in v):raise CatalogError('고정 길이를 확인하세요.')
    elif set(d)=={'min','max','step','default'}:
        if any(type(v) is not int for v in d.values()) or not 1<=d['min']<=d['max']<=120 or not 1<=d['step']<=120:
            raise CatalogError('길이 범위를 확인하세요.')
        v=list(range(d['min'],d['max']+1,d['step']))
    else:raise CatalogError('길이 항목을 확인하세요.')
    if type(d['default']) is not int or d['default'] not in v:raise CatalogError('기본 길이가 지원 범위 밖입니다.')
    return v

class ModelCatalog:
    def __init__(self,path=None,*,loader=load_document,clock=time.monotonic,ttl=86400):
        self.path=Path(path or CONFIG/'video_models.yaml');self.loader=loader;self.clock=clock;self.ttl=ttl;self._lock=RLock()
        self._data=None;self._loaded=0;self.warning=None
        self.refresh(force=True)
    def refresh(self,*,force=False):
        with self._lock:return self._refresh(force=force)
    def _refresh(self,*,force=False):
        if not force and self.clock()-self._loaded<self.ttl:return deepcopy(self._data)
        try:
            new=validate_catalog(self.loader(self.path))
        except (ValueError,OSError,TypeError,KeyError):
            if self._data is None:raise CatalogError('모델 카탈로그를 읽지 못했습니다. 생성 요청을 차단합니다.') from None
            self.warning='카탈로그 갱신 실패 · 마지막 정상 목록을 사용합니다.'
            LOG.warning(self.warning);self._loaded=self.clock();return deepcopy(self._data)
        old={m['id']:m for m in (self._data or {}).get('models',[])}
        for m in new['models']:
            previous=old.get(m['id'])
            if previous and (any(not set(m[k]).issuperset(previous[k]) for k in ['aspect_ratios','resolutions'])
                    or not set(duration_values(m)).issuperset(duration_values(previous))
                    or (previous['audio']['native'] and not m['audio']['native'])
                    or (previous['enabled'] and not m['enabled'])):
                LOG.warning('모델 지원 옵션 축소: %s',m['id'])
        self._data=new;self._loaded=self.clock();self.warning=None
        return deepcopy(new)
    def model(self,identifier):
        return next((m for m in self.refresh()['models'] if m['id']==identifier and m['enabled']),None)

CATALOG=ModelCatalog()

def styles():
    doc=load_document(CONFIG/'style_presets.yaml')
    if not isinstance(doc,dict) or set(doc)!={'schema_version','presets'} or doc['schema_version']!=1:
        raise CatalogError('스타일 설정 형식을 확인하세요.')
    rows={}
    for s in doc['presets']:
        if (set(s)!={'id','label','recommended','prefix','suffix','warn'} or not re.fullmatch(r'[a-z0-9_-]{1,60}',s['id'])
                or s['id'] in rows or type(s['recommended']) is not bool
                or any(not isinstance(s[k],str) or len(s[k])>800 for k in ['label','prefix','suffix','warn'])):
            raise CatalogError('스타일 프리셋 항목을 확인하세요.')
        rows[s['id']]=s
    return rows

def character_config():
    doc=load_document(CONFIG/'character_studio.yaml')
    if (set(doc)!={'schema_version','style_id','aspect_ratio','appearance','style_lock','audio_default','clip_seconds','max_total_seconds','output_quality'}
            or doc['schema_version']!=1 or doc['style_id'] not in styles() or doc['aspect_ratio']!='9:16'
            or type(doc['clip_seconds']) is not int or not 3<=doc['clip_seconds']<=12
            or doc['max_total_seconds']!=60 or type(doc['audio_default']) is not bool
            or doc['output_quality'] not in {'720p','1080p'}):raise CatalogError('캐릭터 고정 설정을 확인하세요.')
    return doc

@dataclass(frozen=True)
class GenerationSettings:
    model_id:str
    aspect_ratio:str
    resolution:str
    duration:int
    style_id:str|None
    audio:bool

def validate(settings,catalog=CATALOG):
    m=catalog.model(settings.model_id)
    if not m:return ['model_id: 활성 모델을 선택하세요.']
    errors=[]
    if settings.aspect_ratio not in m['aspect_ratios']:errors.append('aspect_ratio: 모델이 지원하지 않는 비율입니다.')
    if settings.resolution not in m['resolutions']:errors.append('resolution: 모델이 지원하지 않는 화질입니다.')
    if type(settings.duration) is not int or settings.duration not in duration_values(m):errors.append('duration: 모델의 지원 길이를 선택하세요.')
    if type(settings.audio) is not bool or settings.audio and not m['audio']['native']:errors.append('audio: 이 모델은 소리 생성을 지원하지 않습니다.')
    if settings.style_id is not None and settings.style_id not in styles():errors.append('style_id: 스타일 프리셋을 확인하세요.')
    return errors

def compose_prompt(style_id,scene_prompt,*,character=None):
    if character:
        return f"{character['appearance']} {character['style_lock']} {scene_prompt}"
    s=styles().get(style_id)
    return f"{s['prefix']} {scene_prompt} {s['suffix']}" if s else scene_prompt

def build_request(settings,scene_prompt,catalog=CATALOG,*,reference_url=None,character=None):
    errors=validate(settings,catalog)
    if errors:raise CatalogError(' / '.join(errors))
    m=catalog.model(settings.model_id);pm=m['param_map']
    body={'prompt':compose_prompt(settings.style_id,scene_prompt,character=character),**m['fixed_params']}
    for k,v in [('aspect_ratio',settings.aspect_ratio),('resolution',settings.resolution),('duration',settings.duration)]:
        if pm[k]:body[pm[k]]=v
    if m['audio']['native']:body[pm['audio']]=m['audio_values']['on' if settings.audio else 'off']
    if reference_url:
        body[pm['reference']]=[reference_url] if pm['reference']=='image_urls' else reference_url
    return {'path':m['api_path'],'body':body}

def reconcile(settings,catalog=CATALOG):
    m=catalog.model(settings.model_id)
    if m is None:raise CatalogError('저장된 모델이 비활성입니다. 다른 모델로 자동 전환하지 않습니다.')
    notes={};values=dict(vars(settings))
    if settings.aspect_ratio not in m['aspect_ratios']:
        values['aspect_ratio']='9:16' if '9:16' in m['aspect_ratios'] else m['default_aspect_ratio'];notes['aspect_ratio']='지원 비율로 변경했어요.'
    if settings.resolution not in m['resolutions']:
        rank={'model_default':0,'480p':480,'720p':720,'1080p':1080,'4k':2160}
        available=sorted(m['resolutions'],key=lambda x:rank[x]);under=[x for x in available if rank[x]<=rank.get(settings.resolution,0)]
        values['resolution']=under[-1] if under else available[0];notes['resolution']=f"이 모델은 {settings.resolution}를 지원하지 않아 {values['resolution']}로 변경했어요."
    durations=duration_values(m)
    if type(settings.duration) is not int or settings.duration not in durations:
        values['duration']=min(durations,key=lambda x:(abs(x-settings.duration),x)) if type(settings.duration) is int else m['duration']['default'];notes['duration']='지원되는 가장 가까운 길이로 변경했어요.'
    if settings.audio and not m['audio']['native']:values['audio']=False;notes['audio']='이 모델은 소리 생성을 지원하지 않아 꺼졌어요.'
    if settings.style_id not in styles():
        values['style_id']=next((s['id'] for s in styles().values() if s['recommended']),next(iter(styles())));notes['style_id']='기본 스타일을 적용했어요.'
    result=GenerationSettings(**values)
    if validate(result,catalog):raise CatalogError('저장 설정을 안전하게 조정하지 못했습니다.')
    return result,notes

def estimate(settings,total_seconds,catalog=CATALOG):
    if validate(settings,catalog):raise CatalogError('견적 전 모델 설정을 확인하세요.')
    m=catalog.model(settings.model_id);p=m['pricing'];rate=p['per_second']['on' if settings.audio else 'off']
    return {'currency':'USD','minimum':str(Decimal(rate[0])*total_seconds) if rate else None,
            'maximum':str(Decimal(rate[1])*total_seconds) if rate else None,'seconds':total_seconds,
            'basis':p['basis'],'note':p['note'],'official_quote':False,'audio_price_verified':p['audio_price_verified']}
