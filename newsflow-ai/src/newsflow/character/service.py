"""Durable, explicit character stages. Never dispatched by schedulers or app startup."""
from __future__ import annotations

from copy import deepcopy

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

from .claude import CharacterWriter, StudioResponseError
from .story_response import persist_candidate, public_failure
from .kling import catalog as studio_catalog  # Load the local capability cache once, without network calls.
from .compose import compose, digest
from .higgsfield_client import MODEL, HiggsfieldVideoClient, amount, reference_bytes
from .schema import Character, CharacterError, Storyboard, clean_topic, load_character, prompts


def now():
    return datetime.now(UTC)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def day_exposure(job, day):
    rows=job.get('quote_approvals')
    if rows is not None:
        return sum((amount(r['usd']) for r in rows if r['day']==day),Decimal(0))
    return amount(job['quote_total_usd']) if job.get('approved_day')==day else Decimal(0)



def quote_settings_editable(job):
    """Only a never-submitted quote may be explicitly replaced by another quote."""
    if (job.get('state') not in {'script_review','quoted','prepare_failed'}
            or not job.get('studio_selection') or not job.get('script')
            or job.get('quote_approvals') or job.get('approved_day')
            or job.get('reported_billed_usd') is not None):
        return False
    evidence=('submitted_at','submit_diagnostics','reserved_usd','reserved_at','reservation',
              'submit_reservation','billed_usd','retry','retry_hash')
    if any(job.get(key) is not None for key in evidence):
        return False
    return all(scene.get('state')=='not_submitted'
               and not any(scene.get(key) is not None for key in (*evidence,'handle','history'))
               for scene in job.get('scenes',[]))


def retime_studio_story(story, settings):
    """Apply timing to a local copy of five saved beats, without rewriting content."""
    from .studio_story import StudioStoryboard
    revised=StudioStoryboard.model_validate(story).model_dump()
    if len(revised['scenes'])!=5:
        if sum(scene['seconds'] for scene in revised['scenes'])!=settings['duration']:
            raise CharacterError('retime')
        return StudioStoryboard.model_validate(revised)
    # Only the saved five-beat format uses this relationship. V3 episodes
    # validate their variable scene plan in EpisodeFlow instead.
    if settings['clip_seconds'] * 5 != settings['duration']:
        raise CharacterError('media')
    for scene in revised['scenes']:
        scene['seconds']=settings['clip_seconds']
    return StudioStoryboard.model_validate(revised)


def generation_rows(job):
    """New quotes share one film setup and continue the preceding saved action."""
    if job.get('direct_video'):
        from .direct_video import validate_plan, prompts as direct_prompts
        from .kling import check
        from newsflow.video_models.catalog import CATALOG
        chosen=check(job['studio_selection'])
        plan=validate_plan(job['script'],job['duration'],CATALOG.model(job['model']),job['topic'],allow_continuation=job.get('direct_extension',False))
        return direct_prompts(plan,chosen,job['character'])
    if job.get('automation_version')==1:
        from .episode_story import validate_episode, prompts as episode_prompts
        from .kling import check
        from newsflow.video_models.catalog import CATALOG
        chosen=check(job['studio_selection'])
        story=validate_episode(job['script'],job['duration'],CATALOG.model(job['model']),chosen['sound']=='on')
        return episode_prompts(story,chosen,job['character'])
    rows=job['prompts']
    if not job.get('studio_selection'):
        return rows
    from .kling import check,validate_video_prompt
    from newsflow.video_models.catalog import CATALOG,duration_values
    settings=check(job['studio_selection'])
    model=CATALOG.model(settings['video_model'])
    if model is None:
        raise CharacterError('provider')
    supported=duration_values(model)
    if (len(rows)!=5 or sum(row['seconds'] for row in rows)!=job['duration']
            or any(row.get('position')!=position for position,row in enumerate(rows,1))
            or any(type(row['seconds']) is not int or row['seconds'] not in supported
                   or row['seconds']*5!=job['duration'] for row in rows)):
        raise CharacterError('media')
    from .studio_story import StudioStoryboard
    story=StudioStoryboard.model_validate(job['script'])
    # Shared setup anchors all clips. Prior action is context, not another action
    # to squeeze into this clip. No saved story/payload/approval is rewritten.
    shared=(f"ONE {job['duration']}-second film in 5 consecutive shots. "
            'Same cast species/faces/clothes/voices, set, props, light and time. '
            'No recasting, location reset or time jump.\n'
            f"Shared situation (unspoken): {story.plan.situation}\n"
            f"Opening setup (context only; do not replay): {story.scenes[0].action}\n")
    result=[]
    for row in rows:
        validate_video_prompt(row.get('prompt'))
        index=row['position']-1
        prior=(f"Already happened: {story.scenes[index-1].action} "
               'Continue from its end; do not repeat it.\n'
               if index else 'Establish this one setting and cast.\n')
        focus=(f"Now shot {row['position']}/5, {row['seconds']} seconds only. "
               + ('End ready for the next action; no reset.\n' if index<4
                  else 'Finish this same incident; no new scene.\n'))
        prompt=shared+prior+focus+row['prompt']
        validate_video_prompt(prompt)  # Before upload/estimate. Never slice input.
        result.append({**row,'prompt':prompt})
    return result  # Stored story/prompts, old payloads/quotes/approvals remain unchanged.


class CharacterService:
    def __init__(self, data_dir, sessions, keys, *, writer=None, video=None, budget=None, composer=None, video_keys=None, ffmpeg=None, ffprobe=None):
        self.root = Path(data_dir)/'character'
        self.sessions, self.keys = sessions, keys
        self.writer = writer or CharacterWriter(keys.key)
        self.video = video or HiggsfieldVideoClient()
        self.video_override, self.video_keys = video, video_keys
        self.budget = budget or APIBudgetService(sessions)
        self.composer = composer or compose
        self.ffmpeg = Path(ffmpeg) if ffmpeg is not None else None
        self.ffprobe = Path(ffprobe) if ffprobe is not None else None
        self.daily_limit_approval = None  # Compatibility hook for older trial installers; no daily execution gate.

    def create_episode(self, topic, episode_limit, *, reference, settings, request_id, profile=None, reference_asset='', direct_video=False, direct_extension=False):
        from .episode_service import EpisodeFlow
        return EpisodeFlow(self).create(topic,episode_limit,reference=reference,settings=settings,
            request_id=request_id,profile=profile,reference_asset=reference_asset,direct_video=direct_video,direct_extension=direct_extension)

    def edit_episode(self, identifier, script, expected_hash):
        from .episode_service import EpisodeFlow
        return EpisodeFlow(self).edit(identifier,script,expected_hash)

    def prepare_regeneration(self, identifier, position, *, consent=False):
        from .episode_regeneration import RegenerationFlow
        return RegenerationFlow(self).prepare(identifier, position, consent=consent)

    def regenerate_scenes(self, identifier, *, consent=False, quote_hash=''):
        from .episode_regeneration import RegenerationFlow
        return RegenerationFlow(self).submit(identifier, consent=consent, quote_hash=quote_hash)

    def cancel_regeneration(self, identifier, *, quote_hash=''):
        from .episode_regeneration import RegenerationFlow
        return RegenerationFlow(self).cancel(identifier, quote_hash=quote_hash)

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
                from .episode_story import EpisodeScript
                from .direct_video import DirectVideoPlan
                schema=(DirectVideoPlan
                        if result.get('direct_video') else EpisodeScript if result.get('automation_version')==1
                        else StudioStoryboard if result.get('studio_selection') else Storyboard)
                script=schema.model_validate(result['script'])
                if result.get('automation_version')!=1 and sum(s.seconds for s in script.scenes)!=result['duration']: raise ValueError
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

    def create(self, topic, episode_limit, day_limit=None, *, reference: bytes = b'', selection=None):
        from newsflow.creation.catalog import snapshot
        frozen = snapshot('character', selection) if selection is not None else None
        topic = clean_topic(topic,150)
        per=amount(episode_limit)
        daily=amount(day_limit if day_limit not in (None,'') else episode_limit)
        if len(reference)>10*1024*1024:
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

    def create_studio(self, topic, episode_limit, day_limit=None, *, reference, settings, request_id):
        from .kling import normalize_reference, snapshot, check
        from newsflow.video_models.catalog import character_config, styles
        topic=clean_topic(topic,150)
        if not re.fullmatch(r'[a-f0-9]{32}',request_id or ''): raise CharacterError()
        frozen=snapshot(settings)
        chosen=check(frozen)
        if chosen['clip_seconds'] * 5 != chosen['duration']:
            raise CharacterError('media')
        per=amount(episode_limit)
        daily=amount(day_limit if day_limit not in (None,'') else episode_limit)
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

    def reuse_story(self, source_id, settings, episode_limit, day_limit=None, *, request_id, dialogues=None,
                    reference=None, reference_job='', consent=False):
        """Local explicit copy only. Never resubmit or mutate the source job."""
        self.consent(consent)
        from .kling import snapshot,check,normalize_reference
        from .studio_story import StudioStoryboard,prompts as studio_prompts
        if reference is not None and reference_job:raise CharacterError('reference')
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id):
            raise CharacterError('blocked')
        frozen=snapshot(settings)
        chosen=check(frozen)
        per=amount(episode_limit)
        daily=amount(day_limit if day_limit not in (None,'') else episode_limit)
        with self.lock():
            source=self.read(source_id)
            if source['state'] in {'writing','preparing','generating','retry_quoting','composing'}:
                raise CharacterError('busy')
            if not source.get('script') or not source.get('studio_selection'):
                raise CharacterError('blocked')
            if chosen['script_model']!=source['claude_model']:
                raise CharacterError('blocked')
            source_reference=self.folder(source_id)/'reference.png'
            raw=reference_bytes(source_reference)
            source_reference_hash=hashlib.sha256(raw).hexdigest()
            if source_reference_hash!=source.get('reference_sha256'):raise CharacterError('reference')
            if reference is not None:
                raw=normalize_reference(reference)
            elif reference_job:
                selected=self.read(reference_job)
                selected_raw=reference_bytes(self.folder(reference_job)/'reference.png')
                if hashlib.sha256(selected_raw).hexdigest()!=selected.get('reference_sha256'):
                    raise CharacterError('reference')
                raw=normalize_reference(selected_raw)
            reference_hash=hashlib.sha256(raw).hexdigest()
            story=retime_studio_story(source['script'],chosen)
            provided=dialogues not in (None,[])
            if provided and (not isinstance(dialogues,list) or len(dialogues)!=len(story.scenes)
                             or chosen['sound']!='on'):
                raise CharacterError('blocked')
            revised=story.model_dump()
            for index,scene in enumerate(revised['scenes']):
                text=dialogues[index] if provided else ''
                if chosen['sound']=='on':
                    if (not isinstance(text,str) or len(text.strip())>160
                            or (text.strip() and not re.search(r'[가-힣]',text))):
                        raise CharacterError('blocked')
                    scene['narration']=text.strip()
                else:scene['narration']=''
            revised=StudioStoryboard.model_validate(revised)
            provenance={'source_job_id':source_id,'source_story_sha256':fingerprint(source['script']),
                        'source_plan_hash':source['plan_hash'],'source_reference_sha256':source_reference_hash,
                        'dialogue_source':'user_edited' if provided else 'story_inferred_audio'}
            if [s['seconds'] for s in source['script']['scenes']]!=[s.seconds for s in revised.scenes]:
                provenance['retimed']={'source_duration':source['duration'],'duration':chosen['duration'],
                                      'clip_seconds':chosen['clip_seconds']}
            if reference is not None or reference_job:
                provenance['target_reference_sha256']=reference_hash
            body_hash=fingerprint(['reuse_story_v1',provenance,revised.model_dump(),frozen,str(per),str(daily),
                                   reference_hash,reference_job,reference is not None])
            # Durable local request identity also covers a failed/uncertain file copy.
            # Such receipts are preserved, never silently retried or deleted.
            for receipt in self.root.glob('*/reuse-request.json'):
                if receipt.parent!=self.folder(receipt.parent.name):raise CharacterError('blocked')
                if receipt.is_symlink() or receipt.stat().st_size>4096:raise CharacterError('blocked')
                prior=json.loads(receipt.read_text(encoding='utf8'))
                if prior.get('request_id')!=request_id:continue
                if prior.get('body_hash')!=body_hash or prior.get('state')!='complete':
                    raise CharacterError('blocked')
                self.read(prior['id'])
                return prior['id'],False
            for existing in self.listing():
                if existing.get('studio_request_id')==request_id:raise CharacterError('blocked')
            identifier=uuid4().hex
            folder=self.folder(identifier)
            folder.mkdir()
            receipt=folder/'reuse-request.json'
            pending={'id':identifier,'request_id':request_id,'body_hash':body_hash,'state':'copying_or_unknown'}
            with receipt.open('x',encoding='utf8') as stream:
                json.dump(pending,stream);stream.flush();os.fsync(stream.fileno())
            with (folder/'reference.png').open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            job={'id':identifier,'created_at':now().isoformat(),'state':'script_review','topic':source['topic'],
                 'model':chosen['video_model'],'claude_model':source['claude_model'],
                 'character':dict(source['character']),'script':revised.model_dump(),
                 'reference_sha256':reference_hash,'episode_limit':str(per),'day_limit':str(daily),
                 'events':[{'stage':'reuse_story','at':now().isoformat(),'source_job_id':source_id}],
                 'scenes':[],'reported_billed_usd':None,'duration':chosen['duration'],
                 'made_for_kids':source.get('made_for_kids'),'studio_selection':frozen,
                 'studio_request_id':request_id,'studio_body_hash':body_hash,'reused_story':provenance}
            job['prompts']=studio_prompts(revised,chosen,job['character'])
            job['plan_hash']=self.plan_hash(job)
            self.save(job)
            pending['state']='complete'
            temporary=receipt.with_suffix('.new')
            with temporary.open('x',encoding='utf8') as stream:
                json.dump(pending,stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,receipt)
            return identifier,True

    def update_studio_settings(self, identifier, settings, episode_limit, day_limit=None):
        if self.read(identifier).get('automation_version')==1:
            from .episode_service import EpisodeFlow
            return EpisodeFlow(self).update_settings(identifier,settings,episode_limit)
        from .kling import snapshot, check
        from .studio_story import prompts as studio_prompts
        frozen=snapshot(settings)
        chosen=check(frozen)
        per=amount(episode_limit)
        with self.lock():
            job=self.read(identifier)
            if not quote_settings_editable(job): raise CharacterError('blocked')
            daily=amount(day_limit if day_limit not in (None,'') else job.get('day_limit') or episode_limit)
            if chosen['script_model']!=job['claude_model']:
                raise CharacterError('blocked')
            revised=retime_studio_story(job['script'],chosen)
            prepared_prompts=studio_prompts(revised,chosen,job['character'])
            same_generation=(frozen==job['studio_selection'] and revised.model_dump()==job['script']
                             and prepared_prompts==job['prompts'] and daily==amount(job['day_limit']))
            if job['state']=='quoted' and same_generation:
                # A ceiling edit changes approval identity, not supplier input or the quote's lifetime.
                try:
                    age=now()-datetime.fromisoformat(job['quoted_at'])
                    valid=(bool(job['scenes']) and timedelta(0)<=age
                           and sum(amount(scene['quote_usd']) for scene in job['scenes'])==amount(job['quote_total_usd'])
                           and fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])==job['quote_hash'])
                except (KeyError,TypeError,ValueError):
                    raise CharacterError('budget') from None
                if not valid:raise CharacterError('budget')
                if age<=timedelta(minutes=15):
                    if per!=amount(job['episode_limit']):
                        previous={'episode_limit':job['episode_limit'],'plan_hash':job['plan_hash'],
                                  'quote_hash':job['quote_hash'],'changed_at':now().isoformat()}
                        job['episode_limit']=str(per)
                        job['plan_hash']=self.plan_hash(job)
                        job['quote_hash']=fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])
                        previous.update(new_episode_limit=job['episode_limit'],new_quote_hash=job['quote_hash'])
                        job.setdefault('quote_limit_changes',[]).append(previous)
                        self.save(job)
                    return
            if job['state'] in {'quoted','prepare_failed'}:
                archived={key:deepcopy(job[key]) for key in (
                    'state','studio_selection','model','duration','script','episode_limit','day_limit','plan_hash','prompts','scenes',
                    'quote_total_usd','quoted_at','quote_key_id','quote_hash','message','prepare_failure','failure','error')
                    if key in job}
                archived['archived_at']=now().isoformat()
                job.setdefault('quote_history',[]).append(archived)
                for key in ('quote_total_usd','quoted_at','quote_key_id','quote_hash','message','prepare_failure','failure','error'):
                    job.pop(key,None)
                job.update(state='script_review',scenes=[])
            job.update(studio_selection=frozen,model=chosen['video_model'],duration=chosen['duration'],
                       script=revised.model_dump(),
                       episode_limit=str(per),day_limit=str(daily))
            job['prompts']=prepared_prompts
            job['plan_hash']=self.plan_hash(job)
            self.save(job)

    @staticmethod
    def consent(value):
        if value is not True:
            raise CharacterError('consent')

    def _record_story_response(self, job, attempt):
        if not job.get('studio_selection'):return
        try:
            saved=persist_candidate(self.folder(job['id']),attempt,getattr(self.writer,'last_candidate',None),
                                    getattr(self.writer,'last_usage',None))
            if saved:
                history=job.setdefault('script_responses',[])
                if not any(row.get('attempt')==attempt for row in history):history.append(saved)
        except (OSError,ValueError,TypeError):
            job['script_evidence_error']='write_unavailable'

    def write(self, identifier, *, consent=False, review_token='', review_consent=False):
        if self.read(identifier).get('automation_version')==1:
            from .episode_service import EpisodeFlow
            return EpisodeFlow(self).write(identifier,consent=consent,
                                          review_token=review_token,review_consent=review_consent)
        if review_token or review_consent:
            raise CharacterError('blocked')
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
            if attempt>1:
                job.setdefault('script_attempt_history',[]).append({
                    'attempt':attempt-1,'state':job['state'],'response_received':job.get('response_received',False),
                    'failure':public_failure(job.get('script_failure'))})
            job['state']='writing'
            job.pop('script_failure', None)
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
                    # New topic-only stories never prescribe dialogue; preserve legacy stored stories on read.
                    for scene in story.scenes:scene.narration=''
                    if (sum(s.seconds for s in story.scenes)!=job['duration'] or len(story.scenes)!=payload['scene_count']
                            or any(s.seconds!=settings['clip_seconds'] for s in story.scenes)): raise CharacterError()
                else:
                    story=self.writer.write(payload,options)
                    if not isinstance(story,Storyboard):
                        story=Storyboard.model_validate(story)
            except Exception as error:  # noqa: BLE001 - only finite safe diagnostics may be retained
                job['state']='script_failed'
                self._record_story_response(job,attempt)
                if isinstance(error,StudioResponseError):job['script_failure']=error.diagnostics()
                from newsflow.intelligence.provider import ProviderHTTPResponseError
                if isinstance(error, ProviderHTTPResponseError):
                    job['script_failure'] = error.diagnostics()
                usage=self.writer.last_usage
                response_known=(isinstance(usage,dict) and all(
                    type(usage.get(k)) is int for k in ['prompt_tokens','completion_tokens']))
                job['response_received']=response_known
                self.save(job)
                self.budget.finish(reservation.id,status='failed' if response_known else 'unknown',usage=usage)
                raise CharacterError('provider') from None
            self._record_story_response(job,attempt)
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

    def recover_story_response(self, identifier, *, consent=False, script=None, expected_hash=''):
        """Validate a complete saved response locally; never call or refund a provider."""
        self.consent(consent)
        if self.read(identifier).get('automation_version')==1:
            from .episode_recovery import recover
            return recover(self,identifier,consent=consent,script=script,expected_hash=expected_hash)
        if script is not None or expected_hash:raise CharacterError('blocked')
        from .studio_story import StudioStoryboard, timing_errors, prompts as studio_prompts
        from .kling import check
        with self.lock():
            job=self.read(identifier)
            failure=job.get('script_failure') or {}
            if (job['state']!='script_failed' or job.get('response_received') is not True
                    or not job.get('studio_selection') or job.get('script') or job.get('scenes')
                    or failure.get('stop_reason')!='end_turn'
                    or failure.get('failure_stage') not in {'schema','timing'}):
                raise CharacterError('blocked')
            attempt=job.get('script_attempts')
            rows=[r for r in job.get('script_responses',[]) if r.get('attempt')==attempt]
            if len(rows)!=1:raise CharacterError('blocked')
            row=rows[0];folder=self.folder(identifier)
            if row.get('file')!=f'story-response-attempt-{attempt}.private.json':raise CharacterError('blocked')
            path=folder/row['file']
            if (path.is_symlink() or path.is_junction() or not path.is_file()
                    or not 0<path.stat().st_size<=512*1024 or digest(path)!=row.get('sha256')):
                raise CharacterError('blocked')
            record=json.loads(path.read_bytes())
            if record.get('schemaVersion')!=1 or record.get('attempt')!=attempt or record.get('provider')!='claude_api':
                raise CharacterError('blocked')
            story=StudioStoryboard.model_validate(record['candidate'])
            chosen=check(job['studio_selection'])
            payload={'scene_count':job['duration']//chosen['clip_seconds'],
                     'clip_seconds':chosen['clip_seconds'],'duration':job['duration']}
            if timing_errors(story,payload) or any(s.narration for s in story.scenes):raise CharacterError('blocked')
            if digest(folder/'reference.png')!=job['reference_sha256']:raise CharacterError('reference')
            reference_bytes(folder/'reference.png')
            prepared=studio_prompts(story,chosen,job['character'])
            for name,data in [('script.json',story.model_dump_json(indent=2)),
                              ('prompts.json',json.dumps(prepared,ensure_ascii=False,indent=2))]:
                target=folder/name
                if target.exists() and target.read_text(encoding='utf8')!=data:raise CharacterError('blocked')
            job['script_recovery']={'at':now().isoformat(),'attempt':attempt,'sha256':row['sha256'],
                                    'previous_failure':failure,'provider_calls':0}
            job.update(script=story.model_dump(),prompts=prepared,state='script_review',claude_usage=record.get('usage',{}))
            job.pop('script_failure',None)
            job['plan_hash']=self.plan_hash(job)
            (folder/'script.json').write_text(story.model_dump_json(indent=2),encoding='utf8')
            (folder/'prompts.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2),encoding='utf8')
            self.save(job)

    def prepare(self, identifier, *, consent=False, script_reviewed=False):
        if self.read(identifier).get('automation_version')==1:
            from .episode_service import EpisodeFlow
            return EpisodeFlow(self).prepare(identifier,consent=consent,script_reviewed=script_reviewed)
        self.consent(consent)
        self.consent(script_reviewed)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='script_review':
                raise CharacterError('blocked')
            planned=generation_rows(job)
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
        if self.read(identifier).get('automation_version')==1:
            from .episode_service import EpisodeFlow
            return EpisodeFlow(self).submit(identifier,consent=consent,quote_hash=quote_hash)
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='quoted' or quote_hash!=job['quote_hash']:
                raise CharacterError('blocked')
            if job.get('studio_selection'):
                from .kling import validate_video_prompt
                for scene in job['scenes']:
                    validate_video_prompt(scene['payload'].get('prompt'))
            if (now()-datetime.fromisoformat(job['quoted_at'])>timedelta(minutes=15)
                    or hashlib.sha256(self.video_for(job).credential().encode()).hexdigest()!=job['quote_key_id']
                    or fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])!=quote_hash):
                raise CharacterError('budget')
            # Official supplier quotes only, never estimated token-dollar reservations or actual bills.
            day=(now()+timedelta(hours=9)).date().isoformat()
            total=amount(job['quote_total_usd'])
            if total>amount(job['episode_limit']):
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
                except Exception as exc:  # noqa: BLE001 - fixed non-sensitive diagnostics only
                    scene['state']='unknown'
                    job['state']='submission_unknown'
                    details=getattr(exc,'safe_diagnostics',{})
                    if isinstance(details,dict):
                        from .higgsfield_client import SAFE_ERROR_CODES
                        from newsflow.video.ai.contracts import ERROR_MESSAGES
                        safe={}
                        status=details.get('http_status')
                        code=details.get('error_code')
                        if type(status) is int and 100<=status<=599:safe['http_status']=status
                        if isinstance(code,str) and code in SAFE_ERROR_CODES|set(ERROR_MESSAGES):safe['error_code']=code
                        if safe:
                            scene['submit_diagnostics']=safe
                            job['submit_diagnostics']=dict(safe)
                            job['message']='영상 요청을 중단했습니다. 자동 재전송하지 않습니다.'
                            if 'http_status' in safe:job['message']+=f" HTTP {safe['http_status']}."
                    self.save(job)
                    raise CharacterError('blocked') from None

    def check(self, identifier, *, consent=False):
        if self.read(identifier).get('automation_version')==1:
            from .episode_service import EpisodeFlow
            return EpisodeFlow(self).check(identifier,consent=consent)
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            if job['state'] not in {'generating','scene_review'}:
                raise CharacterError('blocked')
            terminal={'failed','nsfw','canceled'}
            # Collect already submitted siblings after a known terminal failure.
            # Unknown/unsubmitted work must never become an implicit retry.
            if not job.get('scenes') or any(s.get('state') not in terminal|{'submitted','downloaded'} for s in job['scenes']):
                raise CharacterError('blocked')
            folder=self.folder(identifier)
            for scene in job['scenes']:
                if scene['state'] in terminal:
                    continue
                if scene['state']=='downloaded':
                    if digest(folder/scene['file'])!=scene['sha256']:
                        raise CharacterError('media')
                    continue
                if scene['state']!='submitted':
                    raise CharacterError('blocked')
                stage='status'
                try:
                    status=self.video_for(job).check(scene['handle'])
                    if status.state in terminal:
                        from .status_diagnostics import diagnostic, private_inputs
                        scene['status_diagnostics']=diagnostic(status,status.state,now().isoformat(),private_inputs(job))
                        scene['state']=status.state
                        scene['finished_at']=now().isoformat()
                        job['state']='scene_review'
                        self.save(job)
                        continue
                    if status.state=='completed':
                        path=folder/f'scene-{scene["position"]}.mp4'
                        scene['state']='downloading'
                        self.save(job)
                        stage='download'
                        self.video_for(job).fetch(status,path,Event())
                        stage='local_validation'
                        info=probe_clip(path,self.ffprobe) if self.ffprobe is not None else probe_clip(path)
                        if info['duration']<scene['payload']['duration']-2:
                            raise CharacterError('media')
                        scene.update(state='downloaded',file=path.name,sha256=digest(path),media=info)
                        scene['finished_at']=now().isoformat()
                        self.save(job)
                except CharacterError:
                    raise
                except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                    job['state']='status_or_download_failed'
                    job['last_failure']={'stage':stage,'code':'local_media_validation_failed' if stage=='local_validation' else 'provider_response_failed'}
                    self.save(job)
                    raise CharacterError('media' if stage=='local_validation' else 'provider') from None
            if all(s['state']=='downloaded' for s in job['scenes']):
                job['state']='clips_review'
                self.save(job)
            elif any(s['state'] in terminal for s in job['scenes']) and job['state']!='scene_review':
                job['state']='scene_review'
                self.save(job)

    def diagnose(self, identifier, *, consent=False):
        """Explicit existing terminal-request observation; alter diagnostics only."""
        self.consent(consent)
        from .higgsfield_client import request_url
        from .status_diagnostics import TERMINAL, diagnostic, private_inputs
        with self.lock():
            job=self.read(identifier)
            scenes=job.get('scenes',[])
            if (job['state']!='scene_review' or not 1<=len(scenes)<=60
                    or any(s.get('state') not in TERMINAL|{'submitted','downloaded'} for s in scenes)):
                raise CharacterError('blocked')
            targets=[s for s in scenes if s['state'] in TERMINAL]
            if not targets:
                raise CharacterError('blocked')
            positions=set()
            handles=set()
            # Validate the complete target set before the first GET.
            for scene in targets:
                position=scene.get('position')
                handle=scene.get('handle')
                if (type(position) is not int or not 1<=position<=60 or position in positions
                        or not isinstance(handle,dict) or set(handle)!={'request_id','status_url'}):
                    raise CharacterError('blocked')
                try:
                    request_url(handle['status_url'],handle['request_id'])
                except (VideoProviderError,TypeError):
                    raise CharacterError('blocked') from None
                if handle['request_id'] in handles:
                    raise CharacterError('blocked')
                positions.add(position)
                handles.add(handle['request_id'])
            protected=private_inputs(job)
            for scene in targets:
                status=self.video_for(job).diagnose(scene['handle'],protected=protected)
                scene['status_diagnostics']=diagnostic(status,scene['state'],now().isoformat(),protected)
                self.save(job)  # No state/finished_at/quote/attempt/payload/handle changes.

    def recover_local_download(self, identifier, *, consent=False, expected_sha256='', expected_bytes=0):
        """Explicitly adopt an already downloaded clip; never contact a provider or retry a request."""
        self.consent(consent)
        if (not isinstance(expected_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_sha256)
                or type(expected_bytes) is not int or expected_bytes<=0):
            raise CharacterError('media')
        with self.lock():
            job=self.read(identifier)
            scenes=job.get('scenes',[])
            if (job.get('state')!='status_or_download_failed' or len(scenes)!=1
                    or scenes[0].get('state')!='downloading' or scenes[0].get('position')!=1
                    or not isinstance(job.get('studio_selection'),dict)):
                raise CharacterError('blocked')
            scene=scenes[0]
            from .kling import check
            from .higgsfield_client import request_url
            settings=check(job['studio_selection'])
            handle=scene.get('handle')
            if (not isinstance(handle,dict) or set(handle)!={'request_id','status_url'}
                    or scene.get('payload',{}).get('duration')!=job['duration']
                    or scene['payload'].get('sound')!=settings['sound']):
                raise CharacterError('blocked')
            request_url(handle['status_url'],handle['request_id'])  # Pure validation; never a status request.
            path=self.folder(identifier)/'scene-1.mp4'
            import stat
            try:
                before=path.lstat()
                if (not stat.S_ISREG(before.st_mode) or path.is_symlink() or path.is_junction()
                        or getattr(before,'st_file_attributes',0)&0x400
                        or before.st_size!=expected_bytes or digest(path)!=expected_sha256):
                    raise CharacterError('media')
                probe=getattr(self,'ffprobe',None)
                info=probe_clip(path,probe) if probe is not None else probe_clip(path)
                after=path.lstat()
                if (before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns
                        or before.st_ino!=after.st_ino or digest(path)!=expected_sha256
                        or abs(info['duration']-job['duration'])>2
                        or bool(info['has_audio'])!=(settings['sound']=='on')):
                    raise CharacterError('media')
            except (OSError,ValueError,KeyError,TypeError):
                raise CharacterError('media') from None
            recovered=now().isoformat()
            history=job.setdefault('local_recoveries',[])
            if not isinstance(history,list) or len(history)>=20:
                raise CharacterError('blocked')
            history.append({'at':recovered,'action':'recover_local_download',
                            'from_job_state':job['state'],'from_scene_state':scene['state'],
                            'file':'scene-1.mp4','sha256':expected_sha256,'bytes':expected_bytes,
                            'provider_calls':0})
            scene.update(state='downloaded',file='scene-1.mp4',sha256=expected_sha256,
                         media=info,finished_at=recovered)
            job['state']='clips_review'
            self.save(job)
            return {'state':'clips_review','file':'scene-1.mp4','sha256':expected_sha256,
                    'media':info,'providerCalls':0}

    def prepare_retry(self, identifier, *, consent=False):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            pending=next((s for s in job['scenes'] if s['state']=='failed' and s['attempt']<3),None)
            if job['state']!='scene_review' or pending is None:
                raise CharacterError('blocked')
            if job.get('studio_selection'):
                from .kling import validate_video_prompt
                validate_video_prompt(pending['payload'].get('prompt'))
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
            if job.get('studio_selection'):
                from .kling import validate_video_prompt
                validate_video_prompt(scene['payload'].get('prompt'))
            if (fingerprint(retry)!=quote_hash or fingerprint(scene)!=retry['original']
                    or scene['state']!='failed' or scene['attempt']>=3
                    or now()-datetime.fromisoformat(retry['at'])>timedelta(minutes=15)
                    or hashlib.sha256(self.video_for(job).credential().encode()).hexdigest()!=retry['key_id']):
                raise CharacterError('blocked')
            day=(now()+timedelta(hours=9)).date().isoformat()
            extra=amount(retry['quote_usd'])
            exposure=sum((amount(r['usd']) for r in job.get('quote_approvals',[])),Decimal(0))
            exposure+=sum((amount(r['usd']) for r in job.get('text_reservations',[])),Decimal(0))
            if extra+exposure>amount(job['episode_limit']):
                raise CharacterError('budget')
            history=scene.get('history',[])
            history.append({k:v for k,v in scene.items() if k!='history'})
            next_key=(f"{identifier}-s{scene['position']}-t{scene['attempt']+1}" if job.get('automation_version')==1 else uuid4().hex)
            scene.update(history=history,attempt=scene['attempt']+1,idempotency_key=next_key,
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
            tools={name:value for name,value in (('ffmpeg',self.ffmpeg),('ffprobe',self.ffprobe)) if value is not None}
            try:
                if job.get('studio_selection'):
                    from .compose_studio import compose_studio
                    from .studio_story import StudioStoryboard
                    from .kling import check
                    from .episode_story import parse_script
                    output=compose_studio(folder,parse_script(job['script']),clips,
                                          settings=check(job['studio_selection']),**tools)
                else:
                    output=self.composer(folder,Storyboard.model_validate(job['script']),clips,sfx_root=self.root/'sfx',**tools)
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
                    'checklist':['캐릭터 일관성','장면 순서·길이','자막·추가 음성 없음','모델 원본 소리 확인',
                                 'AI 생성 사실·게시 플랫폼 표시 설정','시청 연령·아동용 여부 확인',
                                 '음악은 플랫폼에서 직접 선택','최근 웃음 구조 반복 여부'],
                    'human_review':'NOT VERIFIED','automatic_upload':False}
            if job.get('automation_version')==1:
                review['upload']=job['script']['upload']
                review['checklist']=['주인공 외모·연속성','대사·웅얼거림·음악 없음','속도·반응 대비','자막 오탈자·위치','효과음·연결 음량','선택 길이·마지막 반전','업로드 정보·AI 표시·시청 연령']
            if job.get('character',{}).get('style_warn'):
                review['checklist'].append(job['character']['style_warn'])
            (folder/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8')
            return folder/'final.mp4'


# Errors never include provider response text or filesystem paths in the UI.
SAFE_ERRORS = (CharacterError, Timeout, ProviderError, VideoProviderError, ProviderAmbiguousSubmit)
