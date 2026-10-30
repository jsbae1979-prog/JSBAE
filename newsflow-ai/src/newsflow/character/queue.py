"""Explicit user-started episode batches. No scheduler, automatic retries or final review."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from filelock import FileLock, Timeout

from .registry import atomic_json, safe_path
from .schema import CharacterError
from .topics import TopicStore


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def money(value):
    try:
        if not re.fullmatch(r'\d{1,6}(?:\.\d{1,8})?',str(value)):raise ValueError
        number=Decimal(str(value))
        if not number.is_finite() or number <= 0:raise ValueError
        return number
    except (ValueError,TypeError):raise CharacterError('budget') from None


class EpisodeQueue:
    def __init__(self,data_dir,service,registry,topics=None):
        self.root=Path(data_dir).absolute()/'character-queues'
        self.service,self.registry=service,registry
        self.topics=topics or TopicStore(data_dir)

    def _path(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):raise CharacterError()
        return safe_path(self.root/(identifier+'.json'),self.root)

    def _lock(self,identifier,*,timeout=5):
        self._path(identifier)
        safe_path(self.root,self.root).mkdir(parents=True,exist_ok=True)
        return FileLock(str(safe_path(self.root/(identifier+'.lock'),self.root)),timeout=timeout)

    def _save(self,row):atomic_json(self._path(row['id']),row,self.root)

    def get(self,identifier):
        path=self._path(identifier)
        try:
            if path.stat().st_size>1000000:raise ValueError
            value=json.loads(path.read_text(encoding='utf8'))
            if value.get('version')!=1 or value.get('id')!=identifier or not isinstance(value.get('rows'),list) or not 1<=len(value['rows'])<=50:
                raise ValueError
            return value
        except (ValueError,TypeError,OSError):raise CharacterError() from None

    def list(self):
        safe_path(self.root,self.root)
        if not self.root.exists():return []
        rows=[self.get(path.stem) for path in sorted(self.root.glob('*.json')) if re.fullmatch(r'[a-f0-9]{32}',path.stem)]
        return [row for row in rows if not row.get('archived_at')]

    def delete(self,identifier,*,consent=False):
        """Remove the queue from the list without deleting any execution evidence."""
        if consent is not True:raise CharacterError('consent')
        try:
            # A running request holds this same lock; do not wait and hide its result.
            with self._lock(identifier,timeout=0):
                queue=self.get(identifier)
                if not queue.get('archived_at'):
                    if queue['state'] in {'scripts_running','videos_running'}:raise CharacterError('busy')
                    queue['archived_at']=datetime.now(UTC).isoformat()
                    self._save(queue)
                return {'deleted':True,'historicalJobsPreserved':True}
        except Timeout:raise CharacterError('busy') from None

    def create(self,character_id,topic_ids,settings,episode_limit,request_id):
        if (not isinstance(topic_ids,list) or not 1<=len(topic_ids)<=50
                or any(not isinstance(t,str) for t in topic_ids) or len(set(topic_ids))!=len(topic_ids)):
            raise CharacterError()
        identity=fingerprint([character_id,topic_ids,settings,str(money(episode_limit))])
        try:
            with self._lock(request_id):
                if self._path(request_id).exists():
                    queue=self.get(request_id)
                    if queue.get('archived_at'):raise CharacterError('blocked')
                    if queue['request_hash']!=identity:raise CharacterError('blocked')
                else:
                    profile=self.registry.snapshot(character_id)
                    topics={row['id']:row for row in self.topics.list(character_id)}
                    if any(t not in topics for t in topic_ids):raise CharacterError()
                    queue={'version':1,'id':request_id,'request_hash':identity,'state':'drafts','character_id':character_id,
                           'profile':profile,'settings':deepcopy(settings),'episode_limit':str(money(episode_limit)),
                           'created_at':datetime.now(UTC).isoformat(),'rows':[
                               {'topic_id':t,'topic':topics[t]['topic'],'job_id':None,'state':'draft'} for t in topic_ids]}
                    self._save(queue)
                reference=self.registry.images.asset(queue['profile']['asset']).read_bytes()
                for row in queue['rows']:
                    if row['job_id']:continue
                    stable_request=hashlib.sha256((request_id+':'+row['topic_id']).encode()).hexdigest()[:32]
                    identifier,_=self.service.create_episode(row['topic'],queue['episode_limit'],reference=reference,
                        settings=queue['settings'],request_id=stable_request,profile=queue['profile'])
                    row['job_id']=identifier
                    self._save(queue)
                return queue
        except Timeout:raise CharacterError('busy') from None

    def run_scripts(self,identifier,*,consent=False):
        if consent is not True:raise CharacterError('consent')
        try:
            with self._lock(identifier):
                queue=self.get(identifier)
                if queue.get('archived_at'):raise CharacterError('blocked')
                if queue['state'] not in {'drafts','scripts_running','scripts_ready'}:raise CharacterError('blocked')
                queue['state']='scripts_running';self._save(queue)
                for row in queue['rows']:
                    if not row['job_id']:raise CharacterError('blocked')
                    job=self.service.read(row['job_id'])
                    if job['state'] in {'script_review','quoted','generating','clips_review','completed'} and job.get('script'):
                        row['state']='script_ready';self._save(queue);continue
                    if row['state']=='writing' or job['state']!='needs_script':
                        queue['state']='blocked';row['state']='needs_review';self._save(queue)
                        raise CharacterError('blocked')
                    row['state']='writing';self._save(queue)
                    try:
                        self.service.write(row['job_id'],consent=True)
                    except Exception:
                        row['state']='needs_review';queue['state']='blocked';self._save(queue)
                        raise CharacterError('provider') from None
                    job=self.service.read(row['job_id'])
                    if job['state']!='script_review' or not job.get('script'):
                        row['state']='needs_review';queue['state']='blocked';self._save(queue)
                        raise CharacterError('blocked')
                    row['state']='script_ready';self._save(queue)
                    self.topics.update_status(queue['character_id'],row['topic_id'],'scripted')
                queue['state']='scripts_ready';self._save(queue)
                return queue
        except Timeout:raise CharacterError('busy') from None

    def approve_videos(self,identifier,approvals,max_total_usd,*,consent=False):
        if consent is not True:raise CharacterError('consent')
        if not isinstance(approvals,list) or not approvals or len(approvals)>50:raise CharacterError()
        try:
            with self._lock(identifier):
                queue=self.get(identifier)
                if queue.get('archived_at'):raise CharacterError('blocked')
                if queue['state'] not in {'scripts_ready','drafts'} or queue.get('video_approval'):raise CharacterError('blocked')
                job_ids={row['job_id'] for row in queue['rows']}
                if (any(not isinstance(a,dict) or set(a)!={'job_id','quote_hash'} or a['job_id'] not in job_ids for a in approvals)
                        or len({a['job_id'] for a in approvals})!=len(approvals)):raise CharacterError()
                accepted=[];total=Decimal(0)
                for approval in approvals:
                    job=self.service.read(approval['job_id'])
                    if (job['state']!='quoted' or job.get('quote_hash')!=approval['quote_hash']
                            or job.get('script_approval',{}).get('sha256')!=fingerprint(job.get('script'))
                            or job.get('quote_approvals')):raise CharacterError('blocked')
                    price=money(job['quote_total_usd']);total+=price
                    accepted.append({**approval,'quote_usd':str(price),'state':'approved'})
                if total>money(max_total_usd):raise CharacterError('budget')
                queue.update(state='videos_approved',video_approval={'at':datetime.now(UTC).isoformat(),
                    'total_usd':str(total),'max_total_usd':str(money(max_total_usd)),'rows':accepted})
                self._save(queue);return queue
        except Timeout:raise CharacterError('busy') from None

    def advance_videos(self,identifier,*,consent=False):
        if consent is not True:raise CharacterError('consent')
        try:
            with self._lock(identifier):
                queue=self.get(identifier)
                if queue.get('archived_at'):raise CharacterError('blocked')
                if queue['state'] not in {'videos_approved','videos_running','clips_ready'}:raise CharacterError('blocked')
                if queue['state']=='clips_ready':return queue
                for entry in queue['video_approval']['rows']:
                    job=self.service.read(entry['job_id'])
                    if entry['state']=='clips_ready':continue
                    if entry['state'] in {'submitted','submitting'}:
                        if job['state']=='generating':
                            try:self.service.check(job['id'],consent=True)
                            except Exception:
                                queue['state']='blocked';self._save(queue);raise CharacterError('provider') from None
                            job=self.service.read(job['id'])
                        if job['state'] in {'clips_review','completed'}:
                            entry['state']='clips_ready';self._save(queue);continue
                        if job['state']=='generating':return queue
                        queue['state']='blocked';entry['state']='needs_review';self._save(queue)
                        raise CharacterError('blocked')
                    if entry['state']!='approved' or job['state']!='quoted' or job.get('quote_hash')!=entry['quote_hash']:
                        queue['state']='blocked';self._save(queue);raise CharacterError('blocked')
                    # Persist intent first. An interrupted submit must be reconciled, never replayed.
                    entry['state']='submitting';queue['state']='videos_running';self._save(queue)
                    try:self.service.submit(job['id'],consent=True,quote_hash=entry['quote_hash'])
                    except Exception:
                        queue['state']='blocked';entry['state']='needs_review';self._save(queue)
                        raise CharacterError('provider') from None
                    entry['state']='submitted';self._save(queue)
                    return queue  # One episode at a time, even when all quotes were approved together.
                queue['state']='clips_ready';self._save(queue)
                return queue
        except Timeout:raise CharacterError('busy') from None
