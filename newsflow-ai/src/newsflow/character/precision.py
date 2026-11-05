"""Precision workflow journals; image engine, asset store and authoring are reused."""
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import re
import time
from filelock import FileLock
from PIL import Image

from .registry import atomic_json, safe_path, safe_text
from .precision_contract import (WorkSettings, PrecisionScenario, INSTRUCTION, PROMPT_VERSION,
    validate_scenario, validate_work_timing, image_prompt, motion_rows, story_input, CONTINUITY_POLICY, CONNECTED_POLICIES)
from .precision_causal import POLICY, CausalScenario, INSTRUCTION as CAUSAL_INSTRUCTION
from .schema import CharacterError
from . import precision_visual as visual
from .service import fingerprint
from newsflow.creation.catalog import validate as image_selection
from newsflow.creation import image_pricing
from newsflow.video_models.catalog import CATALOG

def stamp(): return datetime.now(UTC).isoformat()

def positive(value):
    v=Decimal(str(value))
    if not v.is_finite() or not 0<v<=10000: raise ValueError('작업 예산을 확인하세요.')
    return v

class PrecisionService:
    def __init__(self, data_dir, registry, images, readiness, characters, authoring=None, clock=time.time):
        self.root=Path(data_dir).absolute()/'character-scene-images'
        self.registry,self.images,self.readiness,self.characters=registry,images,readiness,characters
        self.authoring,self.clock=authoring,clock

    def path(self, identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier): raise ValueError('작품을 확인하세요.')
        return safe_path(self.root/(identifier+'.json'),self.root)

    def lock(self):
        safe_path(self.root,self.root).mkdir(parents=True,exist_ok=True)
        return FileLock(str(self.root/'.precision.lock'),timeout=1)

    def read(self, identifier):
        p=self.path(identifier)
        if p.stat().st_size>2_000_000: raise ValueError('작품 기록 크기를 확인하세요.')
        work=json.loads(p.read_text(encoding='utf8'))
        if work['id']!=identifier: raise ValueError('작품을 확인하세요.')
        return work

    def save(self, work):
        work['updated_at']=stamp()
        atomic_json(self.path(work['id']),work,self.root)

    def listing(self):
        safe_path(self.root,self.root)
        if not self.root.exists(): return []
        works=(self.read(p.stem) for p in self.root.glob('*.json'))
        return [{'id':w['id'],'title':w['common']['title'],'state':w['state']} for w in
                sorted(works,key=lambda w:(w.get('updated_at',''),w.get('created_at',''),w['id']),reverse=True)]

    def create(self, common, character_ids, outfits, selection, video_settings, image_limit, video_limit, request_id):
        from .kling import snapshot
        safe_text([common,outfits])
        common=WorkSettings.model_validate(common).model_dump()
        if (not isinstance(character_ids,list) or not 1<=len(character_ids)<=4
                or len(set(character_ids))!=len(character_ids) or set(outfits)!=set(character_ids)):
            raise ValueError('캐릭터 1~4개와 의상·소품을 확인하세요.')
        if not re.fullmatch('[a-f0-9]{32}',request_id or ''): raise ValueError('요청 식별자를 확인하세요.')
        cast={cid:self.registry.snapshot(cid) for cid in character_ids}
        for cid,c in cast.items():
            if not c['species'].strip() or not isinstance(outfits[cid],str) or not 1<=len(outfits[cid].strip())<=300:
                raise ValueError('정밀 제작에는 캐릭터 종류와 의상·액세서리 설명이 필요합니다.')
            c['outfit']=outfits[cid].strip()
            c['image_version']=c['revision']
        selection=image_selection('image',selection)
        from newsflow.publishing.image_reference import reference_capacity
        if len(cast)>reference_capacity(selection['model']): raise ValueError('모델이 이 참조 이미지 수를 지원하지 않습니다.')
        if selection['size']!='864x1536': raise ValueError('정밀 제작은 9:16 이미지를 선택하세요.')
        frozen=snapshot({**video_settings,'duration':common['duration']},precise=True)
        validate_work_timing(common,CATALOG.model(video_settings['video_model']))
        payload={'common':common,'cast':cast,'selection':selection,'video_settings':frozen,
                 'image_limit':str(positive(image_limit)),'video_limit':str(positive(video_limit))}
        identity=fingerprint(payload)
        with self.lock():
            for item in self.listing():
                old=self.read(item['id'])
                if old['request_id']==request_id:
                    if old['body_hash']!=identity: raise ValueError('이미 사용한 요청입니다.')
                    return old
            w={'id':uuid4().hex,'schema_version':1,'mode':'precision','state':'needs_story','revision':1,
               'request_id':request_id,'body_hash':identity,'created_at':stamp(),'scenario':None,'scenes':[],
               'story_attempts':[],'events':[],'prompt_version':'scene-still-v4','continuity_policy':POLICY,
               'visual_reference_policy':visual.POLICY,**payload}
            self.save(w)
            return w

    def editable(self,w,revision):
        if revision!=w['revision'] or w.get('video_job_id') or w['state'] in {'writing','generating'}:
            raise ValueError('처리 중이거나 변경된 작품입니다. 다시 확인하세요.')

    def set_scenario(self,w,value):
        from .kling import check
        model=CATALOG.model(check(w['video_settings'])['video_model'])
        value=validate_scenario(w['common'],w['cast'],value,model,w.get('continuity_policy'))
        # Freeze all prospective video prompts before any image can incur cost.
        motion_rows(w['common'],w['cast'],value['scenes'],check(w['video_settings']),w.get('continuity_policy'))
        previous={s['plan']['no']:s for s in w['scenes']}
        rows=[]
        for plan in value['scenes']:
            prompt=image_prompt(w['common'],w['cast'],plan)
            prior=previous.get(plan['no'])
            if prior and prior['plan']==plan: rows.append(prior);continue
            rows.append({'plan':plan,'prompt':prompt,'versions':deepcopy(prior['versions']) if prior else [],
                         'confirmed':None,'selected':None,'state':'pending'})
        w.update(scenario=value,scenes=rows,state='images',revision=w['revision']+1)
        w.pop('quote',None)
        self.save(w)

    def edit(self,identifier,revision,scenario,image_limit=None):
        with self.lock():
            w=self.read(identifier);self.editable(w,revision)
            if image_limit is not None:
                limit=positive(image_limit)
                exposure=sum(max(Decimal(v['reserve_usd']),Decimal(v.get('observed_usd') or '0'))
                    for s in w['scenes'] for v in s['versions'])
                if limit<exposure: raise ValueError('기존 요청의 예약 비용보다 낮출 수 없습니다.')
                if limit!=positive(w['image_limit']):
                    w['events'].append({'at':stamp(),'kind':'image_budget_changed',
                        'before':w['image_limit'],'after':str(limit)})
                    w['image_limit']=str(limit)
            self.set_scenario(w,scenario)
            return w

    def write_story(self,identifier,revision,consent=False):
        from .episode_service import script_provider
        from .kling import check
        from newsflow.intelligence.provider import Options
        if consent is not True: raise ValueError('유료 스토리 생성 동의가 필요합니다.')
        with self.lock():
            w=self.read(identifier);self.editable(w,revision)
            if w['story_attempts'] or w['scenario']: raise ValueError('보관된 스토리를 편집하세요. 자동 재요청하지 않습니다.')
            if not self.authoring: raise ValueError('스토리 AI가 연결되지 않았습니다.')
            settings=check(w['video_settings']);model=CATALOG.model(settings['video_model'])
            validate_work_timing(w['common'],model)
            attempt={'request_id':'episode:'+identifier+':script:1','at':stamp(),'state':'requesting'}
            w['story_attempts'].append(attempt);w['state']='writing';self.save(w)
            try:
                causal = w.get('continuity_policy') == POLICY
                result=self.authoring.generate(INSTRUCTION+(CAUSAL_INSTRUCTION if causal else ''),story_input(w['common'],w['cast'],model),CausalScenario if causal else PrecisionScenario,
                    Options(model=settings['script_model'],max_tokens=6000,timeout=300),
                    provider=script_provider(settings['script_model']),request_id=attempt['request_id'],consent=True,
                    kind='script',max_reserved_usd=w['video_limit'])
                attempt['state']='received'
                safe_text(result.model_dump())
                attempt['candidate']=result.model_dump()
                self.set_scenario(w,result.model_dump())
                attempt['state']='success'
            except Exception:
                attempt['state']='failed' if getattr(self.authoring,'response_received',False) else 'unknown'
                candidate=getattr(self.authoring,'last_candidate',None)
                if isinstance(candidate,dict):
                    try: safe_text(candidate);attempt['candidate']=candidate
                    except ValueError: pass
                w['state']='story_failed'
            attempt['reserved_usd']=str(getattr(self.authoring,'last_reserved_usd',None) or '0')
            self.save(w)
            return w

    def refs(self,w,scene):
        result=[]
        for cid in scene['plan']['characters']:
            c=w['cast'][cid];raw=self.images.asset(c['asset']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=c['reference_image']['sha256']:
                raise ValueError('참조 이미지가 변경됐습니다.')
            result.append(raw)
        anchor=visual.binding(w,scene)
        if anchor:
            raw=self.images.asset(anchor['asset']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=anchor['sha256']:
                raise ValueError('배경 기준 이미지가 변경됐습니다.')
            result.append(raw)
        from newsflow.publishing.image_reference import checked_references
        from newsflow.publishing.image_generation import ImageGenerationError
        try:
            return checked_references(result,w['selection']['model'])
        except ImageGenerationError:
            raise ValueError('모델의 참조 이미지 개수·파일 형식을 확인하세요.') from None

    def estimate(self,w,scene):
        from io import BytesIO
        from math import ceil
        result=image_pricing.estimate(w['selection'],visual.request_prompt(w,scene),now=self.clock())
        # Same disclosed patch heuristic used by FeedBudget; never an invoice/cap.
        patches=0
        refs=self.refs(w,scene)
        for raw in refs:
            with Image.open(BytesIO(raw)) as im: patches+=ceil(im.width/16)*ceil(im.height/16)
        extra=Decimal(patches)*Decimal('8')/Decimal(1000000)
        result.update(estimatedUsd=str(Decimal(result['estimatedUsd'])+extra),
            reserveUsd=str(Decimal(result['reserveUsd'])+extra*2),
            inputBasis='text_bytes_plus_reference_16px_patch_estimate',referenceCount=len(refs),visual_anchor=visual.binding(w,scene),
            prompt_hash=fingerprint(visual.request_prompt(w,scene)),
            reference_hashes=[hashlib.sha256(raw).hexdigest() for raw in refs])
        return result

    def selected_rows(self,w,numbers):
        if not isinstance(numbers,list) or not numbers or any(type(n)!=int for n in numbers) or len(set(numbers))!=len(numbers):
            raise ValueError('장면을 선택하세요.')
        rows=[s for s in w['scenes'] if s['plan']['no'] in numbers]
        if len(rows)!=len(numbers): raise ValueError('장면을 확인하세요.')
        return rows

    def quote(self,identifier,revision,numbers,regenerate=False):
        with self.lock():
            w=self.read(identifier);self.editable(w,revision)
            if w.get('continuity_policy') in CONNECTED_POLICIES:
                from .kling import check
                validate_scenario(w['common'],w['cast'],w['scenario'],CATALOG.model(check(w['video_settings'])['video_model']),w.get('continuity_policy'))
            rows=self.selected_rows(w,numbers)
            if any(s['versions'] and not regenerate for s in rows): raise ValueError('선택 장면 재생성을 사용하세요.')
            if any(v['state'] in {'requesting','unknown'} for s in rows for v in s['versions']):
                raise ValueError('이 장면의 이전 결과가 불명확합니다. 재전송하지 않습니다.')
            scope=self.readiness.account_scope()
            if not scope or not self.readiness(w['selection'])['generationEnabled']:
                raise ValueError('이미지 모델의 연결과 단가를 확인하세요.')
            # An anchor and its dependants cannot share an approval: the new anchor needs human review.
            selected=set(numbers)
            if any((a:=visual.anchor_scene(w,s)) and a['plan']['no'] in selected for s in rows):
                raise ValueError('배경 기준 장면을 먼저 생성·확정한 뒤 나머지 장면을 만드세요.')
            bounds=[{'no':s['plan']['no'],**self.estimate(w,s)} for s in rows]
            quote={'revision':revision,'numbers':numbers,'regenerate':regenerate,'bounds':bounds,
                'account_scope':scope,'expires':min(self.clock()+3600,image_pricing.VALID_UNTIL),
                'estimated_usd':str(sum(Decimal(b['estimatedUsd']) for b in bounds)),
                'reserve_usd':str(sum(Decimal(b['reserveUsd']) for b in bounds)),
                'currency':'USD','provider_charge_cap':False,'billing_verified':False}
            quote['hash']=fingerprint(quote);w['quote']=quote;self.save(w)
            return w

    def generate(self,identifier,quote_hash,consent=False,reference_consent=False):
        if consent is not True or reference_consent is not True: raise ValueError('참조 이미지 외부 전송과 유료 이미지 생성에 동의하세요.')
        with self.lock():
            w=self.read(identifier);q=w.get('quote',{})
            self.editable(w,q.get('revision'))
            if (q.get('hash')!=quote_hash or q.get('expires',0)<=self.clock()
                    or q.get('account_scope')!=self.readiness.account_scope()
                    or not self.readiness(w['selection'])['generationEnabled']): raise ValueError('예산을 다시 확인하세요.')
            rows=self.selected_rows(w,q['numbers'])
            limit=self.readiness.standing_limit()
            exposure=sum(max(Decimal(v['reserve_usd']),Decimal(v.get('observed_usd') or '0')) for s in w['scenes'] for v in s['versions'])
            if not limit or exposure+Decimal(q['reserve_usd'])>min(positive(limit),positive(w['image_limit'])):
                raise ValueError('설정 또는 작품의 이미지 작업 예산을 초과합니다.')
            if any(s['versions'] and not q['regenerate'] for s in rows) or any(v['state'] in {'unknown','requesting'} for s in rows for v in s['versions']):
                raise ValueError('기존 요청을 확인하세요. 자동 재전송하지 않습니다.')
            # Preflight every actual input before reserving/sending anything, including modified files.
            for scene in rows:
                bound=next(b for b in q['bounds'] if b['no']==scene['plan']['no'])
                refs=self.refs(w,scene)
                if (bound.get('visual_anchor')!=visual.binding(w,scene) or
                        bound.get('prompt_hash')!=fingerprint(visual.request_prompt(w,scene)) or
                        bound.get('reference_hashes')!=[hashlib.sha256(raw).hexdigest() for raw in refs]):
                    raise ValueError('참조 이미지가 변경됐습니다. 예산을 다시 확인하세요.')
            w.update(state='generating',revision=w['revision']+1)
            w['events'].append({'at':stamp(),'kind':'image_approval','quote':deepcopy(q),'reference_consent':True})
            w.pop('quote',None);self.save(w)
            for scene in rows:
                version={'version':len(scene['versions'])+1,'request_id':uuid4().hex,'at':stamp(),
                    'state':'requesting','prompt':visual.request_prompt(w,scene),'plan_hash':fingerprint(scene['plan']),
                    'visual_anchor':visual.binding(w,scene),
                    'prompt_version':w.get('prompt_version',PROMPT_VERSION),'selection':deepcopy(w['selection']),
                    'references':[{'id':cid,'asset':w['cast'][cid]['asset'],'version':w['cast'][cid]['image_version']}
                                  for cid in scene['plan']['characters']],
                    'reserve_usd':next(b['reserveUsd'] for b in q['bounds'] if b['no']==scene['plan']['no']),
                    'billing_verified':False,'quote_hash':quote_hash}
                scene['versions'].append(version);scene['state']='generating';self.save(w)
                try:
                    refs=self.refs(w,scene)
                    draft=self.images.create(version['prompt'],w['selection'],references=refs)
                    version['draft_id']=draft;self.save(w)  # persist before external execution
                    runid=self.images.execute(draft,consent=True,reviewed=True)
                    output=self.images.output(draft)
                    version.update(run_id=runid,state=output.status,usage=output.result.get('usage'))
                    observed=image_pricing.usage_cost(output.result.get('usage'))
                    if observed is not None:
                        version.update(observed_usd=observed,over_reserve=Decimal(observed)>Decimal(version['reserve_usd']))
                    if output.status=='success':
                        asset=self.images.export(draft,reviewed=True)
                        version.update(asset=asset,sha256=hashlib.sha256(self.images.asset(asset).read_bytes()).hexdigest())
                        scene.update(state='review',selected=version['version'],confirmed=None)
                    else: scene['state']=output.status
                except Exception:
                    version['state']='unknown';scene['state']='unknown'
                self.save(w)
                if version['state']!='success' or version.get('over_reserve'): break
            w['state']='images';self.save(w)
            return w

    def reconcile(self,identifier,revision):
        """Read durable local results after interruption; never resend or poll providers."""
        with self.lock():
            w=self.read(identifier)
            if revision!=w['revision'] or w.get('video_job_id'):
                raise ValueError('현재 작품을 다시 확인하세요.')
            for scene in w['scenes']:
                for v in scene['versions']:
                    if v['state'] not in {'requesting','unknown'}: continue
                    output=self.images.output(v['draft_id']) if v.get('draft_id') else None
                    if output and output.status=='success':
                        asset=self.images.export(v['draft_id'],reviewed=True)
                        v.update(state='success',run_id=output.id,usage=output.result.get('usage'),
                                 asset=asset,sha256=hashlib.sha256(self.images.asset(asset).read_bytes()).hexdigest())
                        observed=image_pricing.usage_cost(output.result.get('usage'))
                        if observed is not None:
                            v.update(observed_usd=observed,over_reserve=Decimal(observed)>Decimal(v['reserve_usd']))
                        scene.update(state='review',selected=v['version'],confirmed=None)
                    else:
                        v['state']='failed' if output and output.status=='failed' else 'unknown'
                        scene['state']=v['state']
            for attempt in w['story_attempts']:
                if attempt['state']=='requesting': attempt['state']='unknown'
            w.update(state='images' if w['scenario'] else 'story_failed',revision=w['revision']+1)
            w.pop('quote',None)
            w['events'].append({'kind':'local_results_checked','at':stamp()})
            self.save(w);return w

    def confirm(self,identifier,revision,number,version,reviewed=False):
        if reviewed is not True: raise ValueError('외형·의상·인원·배경·구도·장면 내용을 검토하세요.')
        with self.lock():
            w=self.read(identifier);self.editable(w,revision)
            scene=self.selected_rows(w,[number])[0]
            v=next((v for v in scene['versions'] if v['version']==version),None)
            if not v or v['state']!='success' or not visual.matches(w,scene,v): raise ValueError('현재 장면의 완료 버전을 선택하세요.')
            raw=self.images.asset(v['asset']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=v['sha256']: raise ValueError('이미지 무결성을 확인하세요.')
            scene.update(selected=version,confirmed={'version':version,'sha256':v['sha256'],'at':stamp()},state='confirmed')
            w['revision']+=1;w.pop('quote',None);self.save(w);return w

    def handoff(self,identifier,revision):
        from .precision_video import handoff
        with self.lock():
            w=self.read(identifier)
            if w.get('video_job_id'): return w
            self.editable(w,revision)
            for scene in w['scenes']:
                receipt=scene.get('confirmed') or {}
                version=next((v for v in scene['versions'] if v['version']==receipt.get('version')),None)
                if not version or not visual.matches(w,scene,version):
                    raise ValueError('변경된 배경 기준에 맞는 장면 이미지를 다시 검토하세요.')
                self.refs(w,scene)
            job=handoff(self,w)
            w.update(video_job_id=job,state='video_ready',revision=w['revision']+1);self.save(w);return w

    def revise_connection(self,identifier,revision,request_id):
        if not re.fullmatch('[a-f0-9]{32}',request_id or ''): raise ValueError('요청 식별자를 확인하세요.')
        with self.lock():
            source=self.read(identifier)
            for item in self.listing():
                old=self.read(item['id'])
                if old.get('revision_request_id')==request_id:
                    if old.get('source_work_id')!=identifier or old.get('source_revision')!=revision:
                        raise ValueError('이미 사용한 요청입니다.')
                    return old
            if source['revision']!=revision or source['state'] in {'writing','generating'} or not source.get('scenario'):
                raise ValueError('원본 작업 상태를 확인하세요.')
            if any(v['state'] in {'requesting','unknown'} for row in source['scenes'] for v in row['versions']):
                raise ValueError('결과가 불명확한 이미지 요청을 먼저 확인하세요.')
            # Do not offer a route around an unresolved paid video request.
            if source.get('video_job_id'):
                video=self.characters.read(source['video_job_id'])
                if video['state'] not in {'clips_review','completed'} or len(video['scenes'])!=len(source['scenes']) or any(row['state']!='downloaded' for row in video['scenes']):
                    raise ValueError('영상 요청이 완료된 뒤 연결 보완 초안을 만드세요.')
            draft={k:deepcopy(source[k]) for k in ('common','cast','selection','video_settings','image_limit','video_limit')}
            draft.update(id=uuid4().hex,schema_version=1,mode='precision',state='connection_review',revision=1,
                request_id=request_id,revision_request_id=request_id,source_work_id=identifier,source_revision=revision,
                created_at=stamp(),prompt_version='scene-still-v4',continuity_policy=POLICY,
                visual_reference_policy=visual.POLICY,
                scenario=deepcopy(source['scenario']),scenes=[],story_attempts=[],events=[])
            # Archive the old assets as references, never pretend they were generated for a changed plan.
            draft['reference_history']=deepcopy(source['scenes'])
            for row in source['scenes']:
                plan=deepcopy(row['plan'])
                draft['scenes'].append({'plan':plan,'prompt':row['prompt'],'versions':[],
                    'confirmed':None,'selected':None,'state':'pending'})
            draft['body_hash']=fingerprint(draft['scenario'])
            draft['events'].append({'kind':'connection_revision_created','at':stamp(),'source_work_id':identifier})
            self.save(draft)
            return draft
