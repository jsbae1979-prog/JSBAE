"""Durable, explicit character stages. Never dispatched by schedulers or app startup."""
from __future__ import annotations

import hashlib
import json
import os
import re
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
from .compose import compose, digest
from .higgsfield_client import MODEL, HiggsfieldVideoClient, amount, reference_bytes
from .schema import Character, CharacterError, Storyboard, clean_text, load_character, prompts


def now():
    return datetime.now(UTC)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class CharacterService:
    def __init__(self, data_dir, sessions, keys, *, writer=None, video=None, budget=None, composer=None):
        self.root = Path(data_dir)/'character'
        self.sessions, self.keys = sessions, keys
        self.writer = writer or CharacterWriter(keys.key)
        self.video = video or HiggsfieldVideoClient()
        self.budget = budget or APIBudgetService(sessions)
        self.composer = composer or compose

    def folder(self, job_id):
        if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{32}',job_id):
            raise CharacterError()
        path = self.root/job_id
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise CharacterError()
        return path

    def read(self, job_id):
        path = self.folder(job_id)/'jobs.json'
        try:
            if path.is_symlink() or path.stat().st_size > 200000:
                raise ValueError
            result = json.loads(path.read_text(encoding='utf8'))
            if result['id'] != job_id or result['model'] != MODEL:
                raise ValueError
            if result.get('script'):
                Storyboard.model_validate(result['script'])
                assert result['plan_hash'] == self.plan_hash(result)
            return result
        except (OSError,KeyError,AssertionError,ValueError,TypeError):
            raise CharacterError() from None

    @staticmethod
    def plan_hash(job):
        return fingerprint({k:job[k] for k in ['topic','model','claude_model','character','script','prompts',
                                               'episode_limit','day_limit','reference_sha256']})

    def save(self, job):
        path = self.folder(job['id'])/'jobs.json'
        temp = path.with_suffix('.tmp')
        with temp.open('x',encoding='utf8') as f:
            json.dump(job,f,ensure_ascii=False,indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,path)

    def lock(self):
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

    def create(self, topic, episode_limit, day_limit, *, reference: bytes = b''):
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
                 'model':MODEL,'claude_model':config.model,'character':character,'script':None,
                 'reference_sha256':refhash,'episode_limit':str(per),'day_limit':str(daily),
                 'events':[],'scenes':[],'reported_billed_usd':None,'duration':30,'made_for_kids':False}
            self.save(job)
            return identifier

    @staticmethod
    def consent(value):
        if value is not True:
            raise CharacterError('consent')

    def write(self, identifier, *, consent=False):
        self.consent(consent)
        with self.lock():
            job=self.read(identifier)
            if job['state']!='needs_script':
                raise CharacterError('blocked')
            options=Options(model=job['claude_model'],timeout=300,max_tokens=3000)
            reservation=self.budget.reserve(provider='claude_api',request_id='character:'+identifier,
                kind='script',model=options.model,max_output_tokens=options.max_tokens,key_store=self.keys)
            job['state']='writing'
            job['events'].append({'stage':'claude','at':now().isoformat(),'request_id':'character:'+identifier})
            self.save(job)
            try:
                payload={'duration':30,'topic':job['topic'],'character':job['character'],
                         'recent_topics':[j['topic'] for j in self.listing() if j['id']!=identifier][:5]}
                story=self.writer.write(payload,options)
                if not isinstance(story,Storyboard):
                    story=Storyboard.model_validate(story)
            except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                job['state']='script_failed'
                self.save(job)
                self.budget.finish(reservation.id,status='unknown',usage=self.writer.last_usage)
                raise CharacterError('provider') from None
            self.budget.finish(reservation.id,status='success',usage=self.writer.last_usage)
            job['script']=story.model_dump()
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
            path=self.folder(identifier)/'reference.png'
            if not job['reference_sha256'] or digest(path)!=job['reference_sha256']:
                raise CharacterError('reference')
            reference_bytes(path)
            job['state']='preparing'
            self.save(job)
            try:
                cachefile=self.root/'references.json'
                cache=json.loads(cachefile.read_text(encoding='utf8')) if cachefile.is_file() else {}
                key_id=hashlib.sha256(self.video.credential().encode()).hexdigest()
                cache_id=fingerprint([job['reference_sha256'],key_id])
                public=cache.get(cache_id)
                if not public:
                    public=self.video.upload_reference(path)
                    cache[cache_id]=public
                    # A URL receipt is private local state; no signed upload URL or credentials are saved.
                    tmp=cachefile.with_suffix('.tmp')
                    with tmp.open('x',encoding='utf8') as f:
                        json.dump(cache,f)
                    os.replace(tmp,cachefile)
                scenes=[]
                for row in job['prompts']:
                    payload=self.video.payload(row['prompt'],row['seconds'],public)
                    quote=str(amount(self.video.estimate(payload)))
                    scenes.append({'position':row['position'],'payload':payload,'quote_usd':quote,
                                   'state':'not_submitted','idempotency_key':uuid4().hex,'attempt':1})
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
                    or hashlib.sha256(self.video.credential().encode()).hexdigest()!=job['quote_key_id']
                    or fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])!=quote_hash):
                raise CharacterError('budget')
            # Official supplier quotes only, never estimated token-dollar reservations or actual bills.
            day=(now()+timedelta(hours=9)).date().isoformat()
            used=sum((amount(j['quote_total_usd']) for j in self.listing()
                      if j.get('approved_day')==day),start=Decimal(0))
            total=amount(job['quote_total_usd'])
            if used+total>amount(job['day_limit']) or total>amount(job['episode_limit']):
                raise CharacterError('budget')
            # Unknown submissions continue consuming this approved quote exposure; no automatic release.
            job['approved_day']=day
            job['state']='generating'
            self.save(job)
            for scene in job['scenes']:
                scene['state']='submitting'
                self.save(job)
                try:
                    scene['handle']=self.video.submit_scene(scene['payload'],scene['idempotency_key'])
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
                    status=self.video.check(scene['handle'])
                    if status.state in {'failed','nsfw','canceled'}:
                        scene['state']=status.state
                        job['state']='scene_review'
                        self.save(job)
                        raise CharacterError('blocked')
                    if status.state=='completed':
                        path=folder/f'scene-{scene["position"]}.mp4'
                        scene['state']='downloading'
                        self.save(job)
                        self.video.fetch(status,path,Event())
                        info=probe_clip(path)
                        if info['duration']<scene['payload']['duration']-2:
                            raise CharacterError('media')
                        scene.update(state='downloaded',file=path.name,sha256=digest(path),media=info)
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
                output=self.composer(folder,Storyboard.model_validate(job['script']),clips,sfx_root=self.root/'sfx')
            except Exception:  # noqa: BLE001 - persist a stopped state without secret supplier diagnostics
                job['state']='compose_failed'
                self.save(job)
                raise CharacterError('media') from None
            job['output']=output
            job['state']='completed'
            self.save(job)
            review={'title':job['script']['title'],'output':output,'model':job['model'],'made_for_kids':False,
                    'quote_total_usd':job['quote_total_usd'],'reported_billed_usd':None,
                    'scenes':[{k:s[k] for k in ['position','file','sha256','state','attempt','quote_usd']} for s in job['scenes']],
                    'checklist':['캐릭터 일관성','자막·순서·30초','AI 생성 표시','아동용 아님 확인',
                                 '음악은 플랫폼에서 직접 선택','최근 웃음 구조 반복 여부'],
                    'human_review':'NOT VERIFIED','automatic_upload':False}
            (folder/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8')
            return folder/'final.mp4'


# Errors never include provider response text or filesystem paths in the UI.
SAFE_ERRORS = (CharacterError, Timeout, ProviderError, VideoProviderError, ProviderAmbiguousSubmit)
