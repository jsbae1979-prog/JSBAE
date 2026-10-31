"""Explicitly requote reviewed scenes and their continuation descendants.

Quote preparation never submits a generation. Old clips, final output and
receipts remain available as revision evidence; no paid result is overwritten.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import hashlib
import re
from uuid import uuid4

from .compose import digest
from .episode_service import EpisodeFlow, fp, now
from .episode_story import prompts
from .higgsfield_client import amount
from .kling import check, generation_reference
from .schema import CharacterError


def affected_positions(scenes, position):
    if type(position) is not int or position not in {row['position'] for row in scenes}:
        raise CharacterError('blocked')
    affected = {position}
    # Validated script dependencies always point backwards. A fixed-point walk
    # is nevertheless explicit about transitive descendants, not adjacent cuts.
    while True:
        larger = affected | {row['position'] for row in scenes
                             if row.get('continuity') == 'continue' and row.get('from') in affected}
        if larger == affected:
            return sorted(affected)
        affected = larger


def owned_clip(folder, row):
    name = row.get('file')
    if not isinstance(name, str) or not re.fullmatch(r'scene-[1-9][0-9]*(?:-t[1-9][0-9]*)?\.mp4', name):
        raise CharacterError('media')
    path = folder / name
    if (path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(folder.resolve())
            or not path.is_file() or digest(path) != row['sha256']):
        raise CharacterError('media')
    return path


class RegenerationFlow:
    def __init__(self, owner):
        self.owner = owner
        self.flow = EpisodeFlow(owner)

    def prepare(self, identifier, position, *, consent=False):
        s = self.owner
        s.consent(consent)
        with s.lock():
            job = s.read(identifier)
            prior_state = (job.get('regeneration', {}).get('source_state')
                           if job['state'] == 'regeneration_quoted' else job['state'])
            if (job.get('automation_version') != 1 or prior_state not in {'clips_review', 'completed'}
                    or any(row['state'] != 'downloaded' for row in job['scenes'])):
                raise CharacterError('blocked')
            affected = affected_positions(job['scenes'], position)
            if any(row['attempt'] >= 3 for row in job['scenes'] if row['position'] in affected):
                raise CharacterError('blocked')
            folder = s.folder(identifier)
            if digest(folder / 'reference.png') != job['reference_sha256']:
                raise CharacterError('reference')
            for row in job['scenes']:
                owned_clip(folder, row)
            story = self.flow.validate(job, job['script'])
            chosen = check(job['studio_selection'])
            planned = {row['position']: row for row in prompts(story, chosen, job['character'])}
            video = s.video_for(job)
            public = video.upload_reference(generation_reference(folder, chosen))
            items = []
            for number in affected:
                old, plan = job['scenes'][number - 1], planned[number]
                payload = video.payload(plan['prompt'], plan['seconds'], public)
                waiting, dependency = False, None
                if plan['continuity'] == 'continue':
                    parent = job['scenes'][plan['from'] - 1]
                    waiting = plan['from'] in affected
                    start = public
                    if not waiting:
                        frame = self.flow.last_frame(job, parent)
                        start = video.upload_reference(frame)
                        dependency = {'position': parent['position'], 'attempt': parent['attempt'],
                                      'clip_sha256': parent['sha256'], 'frame_sha256': digest(frame)}
                    payload = self.flow.with_start(job, payload, start)
                items.append({**plan, 'payload': payload, 'quote_usd': str(amount(video.estimate(payload))),
                              'attempt': old['attempt'] + 1, 'waiting_dependency': waiting,
                              'quoted_reference': public, 'dependency': dependency})
            extra = sum((amount(row['quote_usd']) for row in items), Decimal(0))
            exposure = self.exposure(job)
            if exposure + extra > amount(job['episode_limit']):
                raise CharacterError('budget')
            quotation = {'position': position, 'affected': affected, 'items': items,
                         'quote_total_usd': str(extra), 'exposure_usd': str(exposure),
                         'total_after_usd': str(exposure + extra), 'at': now().isoformat(),
                         'key_id': hashlib.sha256(video.credential().encode()).hexdigest(),
                         'source_state': prior_state, 'source_hash': fp(job['scenes']),
                         'plan_hash': job['plan_hash']}
            if job.get('regeneration'):
                job.setdefault('regeneration_quote_history', []).append({
                    key: job['regeneration'][key] for key in ('position', 'affected', 'quote_total_usd', 'at')})
            job.update(regeneration=quotation, regeneration_hash=fp(quotation), state='regeneration_quoted')
            s.save(job)

    def exposure(self, job):
        return sum((amount(row['usd']) for row in job.get('quote_approvals', [])), Decimal(0)) + self.flow.text_exposure(job)

    def cancel(self, identifier, *, quote_hash=''):
        s = self.owner
        with s.lock():
            job = s.read(identifier)
            quotation = job.get('regeneration', {})
            if (job.get('automation_version') != 1 or job['state'] != 'regeneration_quoted'
                    or quote_hash != job.get('regeneration_hash') or fp(quotation) != quote_hash
                    or quotation.get('source_hash') != fp(job['scenes'])):
                raise CharacterError('blocked')
            job.setdefault('regeneration_quote_history', []).append({
                key: quotation[key] for key in ('position', 'affected', 'quote_total_usd', 'at')})
            job['regeneration_quote_history'][-1]['canceled_at'] = now().isoformat()
            job['state'] = quotation['source_state']
            job.pop('regeneration', None)
            job.pop('regeneration_hash', None)
            s.save(job)

    def submit(self, identifier, *, consent=False, quote_hash=''):
        s = self.owner
        s.consent(consent)
        with s.lock():
            job = s.read(identifier)
            quotation = job.get('regeneration')
            if (job.get('automation_version') != 1 or job['state'] != 'regeneration_quoted'
                    or not isinstance(quotation, dict) or quote_hash != job.get('regeneration_hash')
                    or fp(quotation) != quote_hash or fp(job['scenes']) != quotation['source_hash']
                    or job['plan_hash'] != quotation['plan_hash']
                    or job.get('script_approval', {}).get('sha256') != fp(job['script'])
                    or any(row['state'] != 'downloaded' for row in job['scenes'])):
                raise CharacterError('blocked')
            from datetime import datetime
            age = now() - datetime.fromisoformat(quotation['at'])
            if (not timedelta(0) <= age <= timedelta(minutes=15)
                    or hashlib.sha256(s.video_for(job).credential().encode()).hexdigest() != quotation['key_id']):
                raise CharacterError('blocked')
            self.flow.validate(job, job['script'])
            extra = amount(quotation['quote_total_usd'])
            if self.exposure(job) + extra > amount(job['episode_limit']):
                raise CharacterError('budget')
            folder = s.folder(identifier)
            for old in job['scenes']:
                owned_clip(folder, old)
            revision = uuid4().hex
            job['regeneration_intent'] = {'revision': revision, 'quote_hash': quote_hash,
                                          'affected': quotation['affected'], 'at': now().isoformat()}
            job['state'] = 'regeneration_preparing'
            s.save(job)  # Interrupted local preparation is never replayed into a paid submit.
            try:
                self.archive_edit(job, revision)
                previous = {'revision': revision, 'at': now().isoformat(),
                            'scenes': deepcopy(job['scenes']), 'affected': quotation['affected'],
                            'output': deepcopy(job.get('output'))}
                if previous['output']:
                    previous['output']['file'] = f'revisions/{revision}/final.mp4'
                job.setdefault('generation_history', []).append(previous)
                for item in quotation['items']:
                    old = job['scenes'][item['position'] - 1]
                    history = deepcopy(old.get('history', []))
                    history.append({k: deepcopy(v) for k, v in old.items() if k != 'history'})
                    fresh = {key: deepcopy(item[key]) for key in
                             ('position', 'seconds', 'continuity', 'from', 'prompt', 'payload',
                              'quote_usd', 'attempt', 'quoted_reference')}
                    fresh.update(history=history, approved_template_hash=fp(item['payload']),
                                 idempotency_key=f'{identifier}-s{item["position"]}-t{item["attempt"]}',
                                 state='waiting_dependency' if item['waiting_dependency'] else 'ready')
                    if item['dependency'] is not None:
                        fresh['dependency'] = deepcopy(item['dependency'])
                    job['scenes'][item['position'] - 1] = fresh
                job['quote_total_usd'] = str(amount(job['quote_total_usd']) + extra)
                job['quote_approvals'].append({'scope': 'scene_regeneration', 'usd': str(extra),
                    'positions': quotation['affected'], 'quote_hash': quote_hash, 'at': now().isoformat()})
                job.pop('output', None)
                job['state'] = 'generating'
                s.save(job)
            except Exception:
                job['state'] = 'regeneration_failed'
                s.save(job)
                raise CharacterError('media') from None
            self.flow.dispatch(job)  # Only now do explicitly approved replacement requests leave the process.

    def archive_edit(self, job, revision):
        """Preserve only this job's verified output and own compose directory."""
        s = self.owner
        folder = s.folder(job['id'])
        revisions = folder / 'revisions'
        archive = revisions / revision
        if (revisions.is_symlink() or revisions.is_junction()
                or not archive.resolve().is_relative_to(folder.resolve())):
            raise CharacterError('media')
        archive.mkdir(parents=True, exist_ok=False)
        for name in ('final.mp4', 'compose', 'review.json'):
            source, target = folder / name, archive / name
            if not source.exists():
                continue
            if (source.is_symlink() or source.is_junction()
                    or not source.resolve().is_relative_to(folder.resolve())
                    or not target.resolve().is_relative_to(folder.resolve())):
                raise CharacterError('media')
            if name == 'final.mp4' and digest(source) != job.get('output', {}).get('sha256'):
                raise CharacterError('media')
            # Record source/destination before the bounded move, so a stopped
            # preparation can be recovered locally without requesting new clips.
            receipt = {'source': name, 'file': f'revisions/{revision}/{name}', 'moved': False}
            job['regeneration_intent'].setdefault('preserved', []).append(receipt)
            s.save(job)
            source.rename(target)
            receipt['moved'] = True
            s.save(job)
