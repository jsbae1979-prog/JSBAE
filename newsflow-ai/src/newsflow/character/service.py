"""Durable, explicit character stages. Never dispatched by schedulers or app startup."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from uuid import uuid4

from filelock import FileLock, Timeout

from newsflow.intelligence.api_settings import APIBudgetService, read_api_settings
from newsflow.intelligence.provider import Options, ProviderError
from newsflow.video.ai.clips import probe_clip
from newsflow.video.ai.contracts import ProviderAmbiguousSubmit, VideoProviderError

from .claude import CharacterWriter
from .kling import catalog as studio_catalog  # Load the local capability cache once, without network calls.
from .compose import compose, digest
from .higgsfield_client import MODEL, HiggsfieldVideoClient, amount, reference_bytes
from .schema import Character, CharacterError, Storyboard, clean_text, load_character, prompts


def now():
    return datetime.now(UTC)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def day_exposure(job, day):
    rows=job.get('quote_approvals')
    if rows is not None:
        return sum((amount(r['usd']) for r in rows if r['day']==day),Decimal(0))
    return amount(job['quote_total_usd']) if job.get('approved_day')==day else Decimal(0)


def generation_rows(job):
    """Keep the story plan intact; use one provider clip when its full length fits."""
    rows=job['prompts']
    if not job.get('studio_selection'):
        return rows
    from .kling import check
    from newsflow.video_models.catalog import CATALOG,duration_values
    settings=check(job['studio_selection'])
    model=CATALOG.model(settings['video_model'])
    if model is None:
        raise CharacterError('provider')
    supported=duration_values(model)
    if job['duration']>max(supported):
        return rows  # Preserve the accepted multi-clip behavior for longer jobs.
    if job['duration'] not in supported or not rows or sum(row['seconds'] for row in rows)!=job['duration']:
        raise CharacterError('media')
    if any(not isinstance(row['prompt'],str) or not row['prompt'] for row in rows):
        raise CharacterError('media')
    # studio_story.prompts prepends this exact appearance/style to each beat.
    # Factor only that known common prefix; never truncate or rewrite actions.
    character=job.get('character',{})
    appearance,style=character.get('appearance'),character.get('style_lock')
    prefix=f'{appearance} {style} ' if isinstance(appearance,str) and isinstance(style,str) else ''
    shared=bool(prefix) and all(row['prompt'].startswith(prefix) for row in rows)
    lines=[prefix.strip()] if shared else []
    lines.append(f"Create one continuous {job['duration']}-second video. Follow every story beat in order; keep the reference character consistent.")
    elapsed=0
    for row in rows:
        text=row['prompt'][len(prefix):] if shared else row['prompt']
        lines.append(f"{elapsed}-{elapsed+row['seconds']} seconds: {text}")
        elapsed+=row['seconds']
    prompt='\n'.join(lines)
    if len(prompt)>4500:
        raise CharacterError('media')
    return [{'position':1,'seconds':job['duration'],'prompt':prompt,
             'story_positions':[row['position'] for row in rows]}]


class CharacterService:
    def __init__(self, data_dir, sessions, keys, *, writer=None, video=None, budget=None, composer=None, video_keys=None):
        self.root = Path(data_dir)/'character'
        self.sessions, self.keys = sessions, keys
        self.writer = writer or CharacterWriter(keys.key)
        self.video = video or HiggsfieldVideoClient()
        self.video_override, self.video_keys = video, video_keys
        self.budget = budget or APIBudgetService(sessions)
        self.composer = composer or compose

    def video_for(self, job):
        if self.video_override is not None or not (job.get('selection') or job.get('studio_selection')):
            return self.video
        if job.get('studio_selection'):
            from .kling import KlingClient, check
            if self.video_keys is None: raise CharacterError('provider')
            return KlingClient(self.video_keys.key, check(job['studio_selection']))
        from newsflow.creation.catalog import check_snapshot
        chosen = check_snapshot(job['selection'], 'character')
        if chosen['credential_source'] == 'legacy_env':
            return self.video
        if self.video_keys is None:
            raise CharacterError('Higgsfield API 키를 설정에서 등록하세요.')
        return HiggsfieldVideoClient(self.video_keys.key)

    def folder(self, job_id):
        if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{32}',job_id):
            raise CharacterError()
        path = self.root/job_id
        if (self.root.is_symlink() or self.root.is_junction() or path.is_symlink() or path.is_junction()
                or not path.resolve().is_relative_to(self.root.resolve())):
            raise CharacterError()
        return path

    def read(self, job_id):
        path = self.folder(job_id)/'jobs.json'
        try:
            if path.is_symlink() or path.stat().st_size > 200000:
                raise ValueError
            result = json.loads(path.read_text(encoding='utf8'))
            from .kling import check
            if result['id'] != job_id:
                raise ValueError
            if result.get('studio_selection'):
                chosen=check(result['studio_selection'])
                if result['model']!=chosen['video_model'] or result['claude_model']!=chosen['script_model'] or result['duration']!=chosen['duration']:
                    raise ValueError
            elif result['model']!=MODEL:
                raise ValueError
            if result.get('selection'):
                from newsflow.creation.catalog import check_snapshot
                chosen = check_snapshot(result['selection'], 'character')
                if result['claude_model'] != chosen['script_model'] or result['model'] != chosen['video_model']:
                    raise ValueError
            if result.get('script'):
                from .studio_story import StudioStoryboard
                schema=StudioStoryboard if result.get('studio_selection') else Storyboard
                script=schema.model_validate(result['script'])
                if sum(s.seconds for s in script.scenes)!=result['duration']: raise ValueError
                assert result['plan_hash'] == self.plan_hash(result)
            return result
        except (OSError,KeyError,AssertionError,ValueError,TypeError):
            raise CharacterError() from None

    @staticmethod
    def plan_hash(job):
        return fingerprint({k:job[k] for k in ['topic','model','claude_model','character','script','prompts',
                                               'episode_limit','day_limit','reference_sha256'] + (['selection'] if 'selection' in job else []) + (['studio_selection'] if 'studio_selection' in job else [])})

    def save(self, job):
        path = self.folder(job['id'])/'jobs.json'
        temp = path.with_suffix('.tmp')
        with temp.open('x',encoding='utf8') as f:
            json.dump(job,f,ensure_ascii=False,indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Windows scanners/readers can briefly deny an atomic rename. Retry this
        # local commit only; never rerun the enclosing paid operation or discard
        # either journal when replacement remains impossible.
        for attempt in range(3):
            try:
                os.replace(temp,path)
                break
            except PermissionError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 2:
                    raise
                time.sleep(.025)


    def lock(self):
        if self.root.is_symlink() or self.root.is_junction():
            raise CharacterError()
        self.root.mkdir(parents=True,exist_ok=True)
        return FileLock(str(self.root/'character.lock'),timeout=0)

    def listing(self):
        if not self.root.is_dir():
            return []
        rows=[]
        for p in sorted(self.root.glob('*/jobs.json'),key=lambda p:p.parent.name):
            try:
                rows.append(self.read(p.parent.name))
            except CharacterError:
                continue
        return sorted(rows,key=lambda r:r['created_at'],reverse=True)

    def create(self, topic, episode_limit, day_limit, *, reference: bytes = b'', selection=None):
        from newsflow.creation.catalog import snapshot
        frozen = snapshot('character', selection) if selection is not None else None
        topic = clean_text(topic,150)
        per, daily = amount(episode_limit),amount(day_limit)
        if per>daily or len(reference)>10*1024*1024:
            raise CharacterError('budget')
        with self.lock():
            config = read_api_settings(self.sessions,'claude_api')
            identifier=uuid4().hex
            folder=self.folder(identifier)
            folder.mkdir()
            refhash=None
            if reference:
                path=folder/'reference.png'
                path.write_bytes(reference)
                reference_bytes(path)
                refhash=digest(path)
            character=load_character().model_dump()
            job={'id':identifier,'created_at':now().isoformat(),'state':'needs_script','topic':topic,
                 'model':MODEL,'claude_model':frozen['script_model'] if frozen else config.model,'character':character,'script':None,
                 'reference_sha256':refhash,'episode_limit':str(per),'day_limit':str(daily),
                 'events':[],'scenes':[],'reported_billed_usd':None,'duration':30,'made_for_kids':False}
            if frozen:
                job['selection'] = frozen
            self.save(job)
            return identifier

    def create_studio(self, topic, episode_limit, day_limit, *, reference, settings, request_id):
        from .kling import normalize_reference, snapshot, check
        from newsflow.video_models.catalog import character_config, styles
        topic=clean_text(topic,150)
        if not re.fullmatch(r'[a-f0-9]{32}',request_id or ''): raise CharacterError()
        frozen=snapshot(settings)
        per,daily=amount(episode_limit),amount(day_limit)
        if per>daily: raise CharacterError('budget')
        raw=normalize_reference(reference)
        body_hash=fingerprint([topic,hashlib.sha256(raw).hexdigest(),frozen,str(per),str(daily)])
        with self.lock():
            for existing in self.listing():
                if existing.get('studio_request_id')==request_id:
                    if existing.get('studio_body_hash')!=body_hash: raise CharacterError('blocked')
                    return existing['id'],False
            identifier=uuid4().hex
            folder=self.folder(identifier)
            folder.mkdir()
            (folder/'reference.png').write_bytes(raw)
            chosen=check(frozen)
            job={'id':identifier,'created_at':now().isoformat(),'state':'needs_script','topic':topic,
                 'model':chosen['video_model'],'claude_model':chosen['script_model'],
                 'character':{**character_config(),'source':'user_reference','style_warn':styles()[chosen['style']]['warn']},'script':None,
                 'reference_sha256':digest(folder/'reference.png'),'episode_limit':str(per),'day_limit':str(daily),
                 'events':[],'scenes':[],'reported_billed_usd':None,'duration':chosen['duration'],
                 'made_for_kids':None,'studio_selection':frozen,
                 'studio_request_id':request_id,'studio_body_hash':body_hash}
            self.save(job)
            return identifier,True

    def update_studio_settings(self, identifier, settings, episode_limit, day_limit):
        from .kling import snapshot, check
        from .studio_story import StudioStoryboard, prompts as studio_prompts
        frozen=snapshot(settings)
        per,daily=amount(episode_limit),amount(day_limit)
        with self.lock():
            job=self.read(identifier)
            if not job.get('studio_selection') or job['state']!='script_review': raise CharacterError('blocked')
            if (settings['duration']!=job['duration'] or settings['clip_seconds']!=check(job['studio_selection'])['clip_seconds']
                    or settings['script_model']!=job['claude_model']):
                raise CharacterError('blocked')
            if per>daily: raise CharacterError('budget')
            job.update(studio_selection=frozen,model=settings['video_model'],
                       episode_limit=str(per),day_limit=str(daily))
            job['prompts']=studio_prompts(StudioStoryboard.model_validate(job['script']),settings,job['character'])
            job['plan_hash']=self.plan_hash(job)
            self.save(job)

    @staticmethod
    def consent(value):
        if value is not True:
            raise CharacterError('consent')

    def write(self, identifier, *, consent=False):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            attempt=job.get('script_attempts',0)+1
            retry_known=(job['state']=='script_failed' and job.get('response_received') is True and attempt<=3)
            if job['state']!='needs_script' and not retry_known:
                raise CharacterError('blocked')
            if job.get('studio_selection'):
                reference=self.folder(identifier)/'reference.png'
                if digest(reference)!=job['reference_sha256']: raise CharacterError('reference')
                reference_bytes(reference)
            options=Options(model=job['claude_model'],timeout=300,max_tokens=3000)
            request_id='character:'+identifier+(':'+str(attempt) if attempt>1 else '')
            reservation=self.budget.reserve(provider='claude_api',request_id=request_id,
                kind='script',model=options.model,max_output_tokens=options.max_tokens,key_store=self.keys)
            job['state']='writing'
            job['script_attempts']=attempt
            job['events'].append({'stage':'claude','at':now().isoformat(),'request_id':request_id})
            self.save(job)
            try:
                payload={'duration':job['duration'],'topic':job['topic'],'character':job['character'],
                         'recent_topics':[j['topic'] for j in self.listing() if j['id']!=identifier][:5]}
                if job.get('studio_selection'):
                    from .kling import check
                    from .studio_story import StudioStoryboard
                    settings=check(job['studio_selection'])
                    payload.update(sound=settings['sound'],clip_seconds=settings['clip_seconds'],
                                   scene_count=job['duration']//settings['clip_seconds'])
                    story=self.writer.write_studio(payload,options,reference_bytes(self.folder(identifier)/'reference.png'))
                    story=StudioStoryboard.model_validate(story)
                    if (sum(s.seconds for s in story.scenes)!=job['duration'] or len(story.scenes)!=payload['scene_count']
                            or any(s.seconds!=settings['clip_seconds'] for s in story.scenes)): raise CharacterError()
                else:
                    story=self.writer.write(payload,options)
                    if not isinstance(story,Storyboard):
                        story=Storyboard.model_validate(story)
            except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                job['state']='script_failed'
                usage=self.writer.last_usage
                response_known=(isinstance(usage,dict) and all(
                    type(usage.get(k)) is int for k in ['prompt_tokens','completion_tokens']))
                job['response_received']=response_known
                self.save(job)
                self.budget.finish(reservation.id,status='failed' if response_known else 'unknown',usage=usage)
                raise CharacterError('provider') from None
            self.budget.finish(reservation.id,status='success',usage=self.writer.last_usage)
            job['script']=story.model_dump()
            if job.get('studio_selection'):
                from .kling import check
                from .studio_story import prompts as studio_prompts
                job['prompts']=studio_prompts(story,check(job['studio_selection']),job['character'])
            else:
                job['prompts']=prompts(story,Character.model_validate(job['character']))
            job['plan_hash']=self.plan_hash(job)
            job['state']='script_review'
            job['claude_usage']=self.writer.last_usage
            self.save(job)
            (self.folder(identifier)/'script.json').write_text(story.model_dump_json(indent=2),encoding='utf8')
            (self.folder(identifier)/'prompts.json').write_text(json.dumps(job['prompts'],ensure_ascii=False,indent=2),encoding='utf8')

    def prepare(self, identifier, *, consent=False, script_reviewed=False):
        self.consent(consent)
        self.consent(script_reviewed)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='script_review':
                raise CharacterError('blocked')
            planned=generation_rows(job)
            if job.get('studio_selection'):
                from .kling import check, as_generation
                from newsflow.video_models.catalog import estimate
                forecast=estimate(as_generation(check(job['studio_selection'])),job['duration'])
                if forecast['maximum'] is not None and Decimal(forecast['maximum'])>amount(job['episode_limit']):
                    raise CharacterError('budget')
            path=self.folder(identifier)/'reference.png'
            if not job['reference_sha256'] or digest(path)!=job['reference_sha256']:
                raise CharacterError('reference')
            reference_bytes(path)
            job['state']='preparing'
            self.save(job)
            try:
                if job.get('studio_selection'):
                    from .kling import check, generation_reference
                    path=generation_reference(self.folder(identifier),check(job['studio_selection']))
                cachefile=self.root/'references.json'
                if cachefile.is_symlink() or (cachefile.is_file() and cachefile.stat().st_size>1000000):
                    raise CharacterError()
                cache=json.loads(cachefile.read_text(encoding='utf8')) if cachefile.is_file() else {}
                key_id=hashlib.sha256(self.video_for(job).credential().encode()).hexdigest()
                cache_id=fingerprint([digest(path),key_id])
                public=cache.get(cache_id)
                if not public:
                    public=self.video_for(job).upload_reference(path)
                    cache[cache_id]=public
                    # A URL receipt is private local state; no signed upload URL or credentials are saved.
                    tmp=cachefile.with_suffix('.tmp')
                    with tmp.open('x',encoding='utf8') as f:
                        json.dump(cache,f)
                    os.replace(tmp,cachefile)
                scenes=[]
                for row in planned:
                    payload=self.video_for(job).payload(row['prompt'],row['seconds'],public)
                    quote=str(amount(self.video_for(job).estimate(payload)))
                    scenes.append({'position':row['position'],'payload':payload,'quote_usd':quote,
                                   'state':'not_submitted','idempotency_key':uuid4().hex,'attempt':1})
                    if row.get('story_positions'):scenes[-1]['story_positions']=list(row['story_positions'])
                total=sum(amount(s['quote_usd']) for s in scenes)
                if total>amount(job['episode_limit']):
                    raise CharacterError('budget')
                job['scenes']=scenes
                job['quote_total_usd']=str(total)
                job['quoted_at']=now().isoformat()
                job['quote_key_id']=key_id
                job['quote_hash']=fingerprint([job['plan_hash'],scenes,job['quoted_at'],key_id])
                job['state']='quoted'
                self.save(job)
            except Exception as exc:  # noqa: BLE001 - fixed public diagnostics only
                job['state']='prepare_failed'
                self.save(job)
                raise CharacterError(exc.code if isinstance(exc,CharacterError) else 'provider') from None

    def submit(self, identifier, *, consent=False, quote_hash=''):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='quoted' or quote_hash!=job['quote_hash']:
                raise CharacterError('blocked')
            if (now()-datetime.fromisoformat(job['quoted_at'])>timedelta(minutes=15)
                    or hashlib.sha256(self.video_for(job).credential().encode()).hexdigest()!=job['quote_key_id']
                    or fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])!=quote_hash):
                raise CharacterError('budget')
            # Official supplier quotes only, never estimated token-dollar reservations or actual bills.
            day=(now()+timedelta(hours=9)).date().isoformat()
            used=sum((day_exposure(j,day) for j in self.listing()),start=Decimal(0))
            total=amount(job['quote_total_usd'])
            if used+total>amount(job['day_limit']) or total>amount(job['episode_limit']):
                raise CharacterError('budget')
            # Unknown submissions continue consuming this approved quote exposure; no automatic release.
            job['approved_day']=day
            job['quote_approvals']=[{'day':day,'usd':str(total),'scope':'initial'}]
            job['state']='generating'
            self.save(job)
            for scene in job['scenes']:
                scene['state']='submitting'
                scene['submitted_at']=now().isoformat()
                self.save(job)
                try:
                    scene['handle']=self.video_for(job).submit_scene(scene['payload'],scene['idempotency_key'])
                    scene['state']='submitted'
                    self.save(job)
                except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                    scene['state']='unknown'
                    job['state']='submission_unknown'
                    self.save(job)
                    raise CharacterError('blocked') from None

    def check(self, identifier, *, consent=False):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='generating':
                raise CharacterError('blocked')
            folder=self.folder(identifier)
            for scene in job['scenes']:
                if scene['state']=='downloaded':
                    if digest(folder/scene['file'])!=scene['sha256']:
                        raise CharacterError('media')
                    continue
                if scene['state']!='submitted':
                    raise CharacterError('blocked')
                try:
                    status=self.video_for(job).check(scene['handle'])
                    if status.state in {'failed','nsfw','canceled'}:
                        scene['state']=status.state
                        scene['finished_at']=now().isoformat()
                        job['state']='scene_review'
                        self.save(job)
                        raise CharacterError('blocked')
                    if status.state=='completed':
                        path=folder/f'scene-{scene["position"]}.mp4'
                        scene['state']='downloading'
                        self.save(job)
                        self.video_for(job).fetch(status,path,Event())
                        info=probe_clip(path)
                        if info['duration']<scene['payload']['duration']-2:
                            raise CharacterError('media')
                        scene.update(state='downloaded',file=path.name,sha256=digest(path),media=info)
                        scene['finished_at']=now().isoformat()
                        self.save(job)
                except CharacterError:
                    raise
                except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                    job['state']='status_or_download_failed'
                    self.save(job)
                    raise CharacterError('provider') from None
            if all(s['state']=='downloaded' for s in job['scenes']):
                job['state']='clips_review'
                self.save(job)

    def prepare_retry(self, identifier, *, consent=False):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            pending=next((s for s in job['scenes'] if s['state']=='failed' and s['attempt']<3),None)
            if job['state']!='scene_review' or pending is None:
                raise CharacterError('blocked')
            job['state']='retry_quoting'
            self.save(job)
            try:
                quote=str(amount(self.video_for(job).estimate(pending['payload'])))
                retry={'position':pending['position'],'quote_usd':quote,'at':now().isoformat(),
                       'key_id':hashlib.sha256(self.video_for(job).credential().encode()).hexdigest(),
                       'original':fingerprint(pending)}
                job['retry']=retry
                job['retry_hash']=fingerprint(retry)
                job['state']='retry_quoted'
                self.save(job)
            except Exception:  # noqa: BLE001 - fixed public diagnostics, no supplier body
                job['state']='retry_quote_failed'
                self.save(job)
                raise CharacterError('provider') from None

    def retry_scene(self, identifier, *, consent=False, quote_hash=''):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='retry_quoted' or quote_hash!=job['retry_hash']:
                raise CharacterError('blocked')
            retry=job['retry']
            scene=next(s for s in job['scenes'] if s['position']==retry['position'])
            if (fingerprint(retry)!=quote_hash or fingerprint(scene)!=retry['original']
                    or scene['state']!='failed' or scene['attempt']>=3
                    or now()-datetime.fromisoformat(retry['at'])>timedelta(minutes=15)
                    or hashlib.sha256(self.video_for(job).credential().encode()).hexdigest()!=retry['key_id']):
                raise CharacterError('blocked')
            day=(now()+timedelta(hours=9)).date().isoformat()
            exposure=sum((day_exposure(j,day) for j in self.listing()),Decimal(0))
            extra=amount(retry['quote_usd'])
            if (amount(job['quote_total_usd'])+extra>amount(job['episode_limit'])
                    or exposure+extra>amount(job['day_limit'])):
                raise CharacterError('budget')
            history=scene.get('history',[])
            history.append({k:v for k,v in scene.items() if k!='history'})
            scene.update(history=history,attempt=scene['attempt']+1,idempotency_key=uuid4().hex,
                         state='submitting',quote_usd=retry['quote_usd'],submitted_at=now().isoformat())
            scene.pop('handle',None)
            scene.pop('finished_at',None)
            job['quote_total_usd']=str(amount(job['quote_total_usd'])+extra)
            job['quote_approvals'].append({'day':day,'usd':str(extra),'scope':'scene_retry',
                                           'position':scene['position'],'attempt':scene['attempt']})
            job['state']='generating'
            self.save(job)
            try:
                scene['handle']=self.video_for(job).submit_scene(scene['payload'],scene['idempotency_key'])
                scene['state']='submitted'
                self.save(job)
            except Exception:  # noqa: BLE001 - retain the new intent and prior terminal receipt
                scene['state']='unknown'
                job['state']='submission_unknown'
                self.save(job)
                raise CharacterError('blocked') from None

    def render(self, identifier, *, reviewed=False):
        self.consent(reviewed)
        with self.lock():
            job=self.read(identifier)
            if job['state']=='completed':
                path=self.folder(identifier)/'final.mp4'
                if digest(path)!=job['output']['sha256']:
                    raise CharacterError('media')
                return path
            if job['state']!='clips_review':
                raise CharacterError('blocked')
            folder=self.folder(identifier)
            clips=[folder/s['file'] for s in job['scenes']]
            if any(digest(p)!=s['sha256'] for p,s in zip(clips,job['scenes'])):
                raise CharacterError('media')
            job['state']='composing'
            self.save(job)
            try:
                if job.get('studio_selection'):
                    from .compose_studio import compose_studio
                    from .studio_story import StudioStoryboard
                    from .kling import check
                    output=compose_studio(folder,StudioStoryboard.model_validate(job['script']),clips,
                                          settings=check(job['studio_selection']))
                else:
                    output=self.composer(folder,Storyboard.model_validate(job['script']),clips,sfx_root=self.root/'sfx')
            except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                job['state']='compose_failed'
                self.save(job)
                raise CharacterError('media') from None
            job['output']=output
            job['state']='completed'
            self.save(job)
            review={'title':job['script']['title'],'output':output,'model':job['model'],'made_for_kids':job.get('made_for_kids'),
                    'quote_total_usd':job['quote_total_usd'],'reported_billed_usd':None,
                    'scenes':[{**{k:s[k] for k in ['position','file','sha256','state','attempt','quote_usd']},
                               'history':[{**{k:old.get(k) for k in ['attempt','state','quote_usd','submitted_at',
                                                                    'finished_at']},
                                           'request_id':old.get('handle',{}).get('request_id')}
                                          for old in s.get('history',[])]} for s in job['scenes']],
                    'checklist':['캐릭터 일관성','자막·장면 순서·길이','AI 생성 표시','시청 연령·아동용 여부 확인',
                                 '음악은 플랫폼에서 직접 선택','최근 웃음 구조 반복 여부'],
                    'human_review':'NOT VERIFIED','automatic_upload':False}
            if job.get('character',{}).get('style_warn'):
                review['checklist'].append(job['character']['style_warn'])
            (folder/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8')
            return folder/'final.mp4'


# Errors never include provider response text or filesystem paths in the UI.
SAFE_ERRORS = (CharacterError, Timeout, ProviderError, VideoProviderError, ProviderAmbiguousSubmit)
