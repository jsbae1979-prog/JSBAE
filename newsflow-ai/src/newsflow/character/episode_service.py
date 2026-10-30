"""Profile-backed episode orchestration. External work is explicit and journaled."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4
import hashlib
import json
import re

from .schema import CharacterError, clean_topic
from .compose import digest, run
from .episode_story import EpisodeScript, SCRIPT_INSTRUCTION, script_input, prompts, validate_episode
from .higgsfield_client import amount, reference_bytes
from .kling import check, snapshot, normalize_reference, generation_reference
from newsflow.intelligence.provider import Options
from newsflow.video.ai.clips import probe_clip, FORMAT_WHITELIST
from newsflow.video.engine import FFmpegAdapter
from newsflow.video_models.catalog import CATALOG


def fp(value):
    from .service import fingerprint
    return fingerprint(value)


def now():
    from .service import now as current
    return current()


def dump(story):
    return story.model_dump(by_alias=True)


def script_provider(model):
    from newsflow.intelligence.api_providers import API_MODELS
    found = [p for p in ('claude_api', 'openai') if model in API_MODELS.get(p, ())]
    if len(found) != 1:
        raise CharacterError('provider')
    return found[0]


class EpisodeFlow:
    def __init__(self, owner):
        self.owner = owner

    def create(self, topic, episode_limit, *, reference, settings, request_id, profile):
        # The registry supplies a validated, user-confirmed snapshot; never a mascot fallback.
        if not isinstance(profile, dict) or not profile.get('id'):
            raise CharacterError('reference')
        topic = clean_topic(topic, 150)
        if not re.fullmatch(r'[a-f0-9]{32}', request_id or ''):
            raise CharacterError('blocked')
        frozen = snapshot(settings)
        chosen = check(frozen)
        model = CATALOG.model(chosen['video_model'])
        if not model or not model['reference_image'] or '9:16' not in model['aspect_ratios']:
            raise CharacterError('provider')
        if chosen['output_quality'] != '1080p':
            raise CharacterError('media')
        per = amount(episode_limit)
        raw = normalize_reference(reference)
        reference_hash = hashlib.sha256(raw).hexdigest()
        from .registry import CharacterProfile, PROFILE_ID, ASSET_ID
        if (not PROFILE_ID.fullmatch(profile['id']) or not ASSET_ID.fullmatch(profile.get('asset', ''))
                or profile['asset'][7:-4] != hashlib.sha256(reference).hexdigest()):
            raise CharacterError('reference')
        validated = CharacterProfile.model_validate({k: profile[k] for k in CharacterProfile.model_fields if k in profile})
        profile = {**validated.model_dump(), **{k: deepcopy(profile[k]) for k in
                   ('id', 'revision', 'asset', 'reference_image') if k in profile}}
        identity = fp([topic, reference_hash, frozen, str(per), profile])
        s = self.owner
        with s.lock():
            for existing in s.listing():
                if existing.get('studio_request_id') == request_id:
                    if existing.get('studio_body_hash') != identity:
                        raise CharacterError('blocked')
                    return existing['id'], False
            identifier = uuid4().hex
            folder = s.folder(identifier)
            folder.mkdir()
            (folder / 'reference.png').write_bytes(raw)
            job = {'id': identifier, 'automation_version': 1, 'created_at': now().isoformat(),
                   'state': 'needs_script', 'topic': topic, 'character': profile, 'character_id': profile['id'],
                   'model': chosen['video_model'], 'claude_model': chosen['script_model'],
                   'script_provider': script_provider(chosen['script_model']), 'script': None,
                   'reference_sha256': reference_hash, 'episode_limit': str(per), 'day_limit': str(per),
                   'duration': chosen['duration'], 'events': [], 'scenes': [], 'reported_billed_usd': None,
                   'made_for_kids': False, 'studio_selection': frozen,
                   'studio_request_id': request_id, 'studio_body_hash': identity}
            s.save(job)
            return identifier, True

    def validate(self, job, value):
        chosen = check(job['studio_selection'])
        model = CATALOG.model(chosen['video_model'])
        if not model:
            raise CharacterError('provider')
        return validate_episode(value, job['duration'], model, chosen['sound'] == 'on')

    def write(self, identifier, *, consent=False):
        s = self.owner
        s.consent(consent)
        with s.lock():
            job = s.read(identifier)
            attempt = job.get('script_attempts', 0) + 1
            if job['state'] != 'needs_script' and not (
                job['state'] == 'script_failed' and job.get('response_received') is True and attempt <= 3
            ):
                raise CharacterError('blocked')
            authoring = getattr(s, 'authoring', None)
            if authoring is None:
                raise CharacterError('provider')
            chosen = check(job['studio_selection'])
            payload = script_input(job['character'], job['topic'], job['duration'],
                                   CATALOG.model(chosen['video_model']), chosen['sound'] == 'on',
                                   [j['topic'] for j in s.listing() if j.get('character_id') == job['character_id']
                                    and j['id'] != identifier][:5])
            if attempt > 1:
                payload['validation_feedback'] = 'Previous response failed local schema or duration validation. Follow the supplied schema and timing.'
            remaining = amount(job['episode_limit']) - self.text_exposure(job)
            if remaining <= 0:
                raise CharacterError('budget')
            sequence = job.get('script_request_sequence', job.get('script_attempts', 0)) + 1
            job.update(state='writing', script_attempts=attempt, script_request_sequence=sequence,
                       response_received=False)
            s.save(job)  # An interrupted request cannot be automatically replayed.
            try:
                candidate = authoring.generate(SCRIPT_INSTRUCTION, payload, EpisodeScript,
                    Options(model=chosen['script_model'], max_tokens=4000, timeout=300),
                    provider=job['script_provider'], request_id=f'episode:{identifier}:script:{sequence}',
                    consent=True, kind='script', max_reserved_usd=str(remaining))
                story = self.validate(job, candidate)
            except Exception:
                self.record_text_cost(job, authoring, attempt)
                preflight = getattr(authoring, 'last_failure', None)
                not_dispatched = isinstance(preflight, dict) and preflight.get('dispatched') is False
                job.update(state='needs_script' if not_dispatched else 'script_failed',
                           response_received=bool(getattr(authoring, 'response_received', False)))
                if not_dispatched:
                    # Keep a unique request sequence but do not count a local refusal as a paid attempt.
                    job['script_attempts'] = attempt - 1
                job['script_failure'] = {'failure_stage': 'preflight' if not_dispatched else 'schema',
                    'message': '설정·한도를 확인한 뒤 다시 요청하세요. 자동 실행하지 않습니다.' if not_dispatched else
                               '대본 형식·길이를 확인하세요. 자동 재생성하지 않습니다.'}
                s.save(job)
                raise CharacterError('provider') from None
            self.record_text_cost(job, authoring, attempt)
            job.update(state='script_review', script=dump(story), response_received=True)
            try:
                job['prompts'] = prompts(story, chosen, job['character'])
                job.pop('prompt_validation_error', None)
            except CharacterError:
                # Preserve the paid, valid script and reservation for a local edit.
                # Prompt assembly failure must not lose the result or trigger another AI call.
                job['prompts'] = []
                job['prompt_validation_error'] = True
            job['plan_hash'] = s.plan_hash(job)
            job['script_hash'] = fp(job['script'])
            s.save(job)
            (s.folder(identifier) / 'script.json').write_text(json.dumps(job['script'], ensure_ascii=False, indent=2), encoding='utf8')

    @staticmethod
    def record_text_cost(job, authoring, attempt):
        value = getattr(authoring, 'last_reserved_usd', None)
        if value is None:
            value = getattr(authoring, 'last_estimated_usd', None)
        if value is not None and Decimal(value) != 0:
            job.setdefault('text_reservations', []).append({'attempt': attempt, 'usd': str(amount(value)),
                'basis': 'reserved_ceiling_not_actual_bill'})

    @staticmethod
    def text_exposure(job):
        return sum((amount(r['usd']) for r in job.get('text_reservations', [])), Decimal(0))

    def edit(self, identifier, script, expected_hash):
        s = self.owner
        with s.lock():
            job = s.read(identifier)
            if job['state'] not in {'script_review', 'quoted'} or job.get('quote_approvals') or expected_hash != fp(job['script']):
                raise CharacterError('blocked')
            story = self.validate(job, script)
            if job.get('scenes'):
                job.setdefault('quote_history', []).append({'scenes': deepcopy(job['scenes']), 'at': now().isoformat()})
            job.update(script=dump(story), prompts=prompts(story, check(job['studio_selection']), job['character']),
                       scenes=[], state='script_review')
            job.pop('prompt_validation_error', None)
            for key in ('script_approval', 'quote_hash', 'quote_total_usd', 'quoted_at', 'quote_key_id'):
                job.pop(key, None)
            job['script_hash'] = fp(job['script'])
            job['plan_hash'] = s.plan_hash(job)
            s.save(job)
            (s.folder(identifier) / 'script.json').write_text(json.dumps(job['script'], ensure_ascii=False, indent=2), encoding='utf8')

    def prepare(self, identifier, *, consent=False, script_reviewed=False):
        s = self.owner
        s.consent(consent)
        s.consent(script_reviewed)
        with s.lock():
            job = s.read(identifier)
            if job['state'] != 'script_review':
                raise CharacterError('blocked')
            story = self.validate(job, job['script'])
            chosen = check(job['studio_selection'])
            planned = prompts(story, chosen, job['character'])
            folder = s.folder(identifier)
            if digest(folder / 'reference.png') != job['reference_sha256']:
                raise CharacterError('reference')
            job['state'] = 'preparing'
            s.save(job)
            try:
                video = s.video_for(job)
                path = generation_reference(folder, chosen)
                public = video.upload_reference(path)
                scenes = []
                for row in planned:
                    payload = video.payload(row['prompt'], row['seconds'], public)
                    if row['continuity'] == 'continue':
                        payload = self.with_start(job, payload, public)
                    price = str(amount(video.estimate(payload)))
                    scenes.append({**row, 'payload': payload, 'quote_usd': price, 'state': 'not_submitted',
                                   'attempt': 1, 'idempotency_key': f'{identifier}-s{row["position"]}-t1',
                                   'quoted_reference': public})
                job['script_approval'] = {'at': now().isoformat(), 'sha256': fp(job['script']),
                                          'plan_hash': job['plan_hash']}
                job.update(scenes=scenes, quote_total_usd=str(sum(amount(x['quote_usd']) for x in scenes)),
                           quoted_at=now().isoformat(), quote_key_id=hashlib.sha256(video.credential().encode()).hexdigest(),
                           state='quoted')
                job['quote_hash'] = fp([job['plan_hash'], scenes, job['quoted_at'], job['quote_key_id']])
                s.save(job)
                (folder / 'script.json').write_text(json.dumps({'script': job['script'], 'approval': job['script_approval']},
                    ensure_ascii=False, indent=2), encoding='utf8')
            except Exception:
                job['state'] = 'prepare_failed'
                s.save(job)
                raise CharacterError('provider') from None

    def with_start(self, job, payload, url):
        from newsflow.video.ai.download import safe_url
        model = CATALOG.model(job['model'])
        field = model.get('continuation_param') if model else None
        if not field:
            raise CharacterError('provider')
        return {**payload, field: safe_url(url)}

    def submit(self, identifier, *, consent=False, quote_hash=''):
        s = self.owner
        s.consent(consent)
        with s.lock():
            job = s.read(identifier)
            if (job['state'] != 'quoted' or quote_hash != job.get('quote_hash') or
                fp([job['plan_hash'], job['scenes'], job['quoted_at'], job['quote_key_id']]) != quote_hash or
                not timedelta(0) <= now() - datetime.fromisoformat(job['quoted_at']) <= timedelta(minutes=15) or
                hashlib.sha256(s.video_for(job).credential().encode()).hexdigest() != job['quote_key_id'] or
                job.get('script_approval', {}).get('sha256') != fp(job['script'])):
                raise CharacterError('blocked')
            self.validate(job, job['script'])
            if amount(job['quote_total_usd']) + self.text_exposure(job) > amount(job['episode_limit']):
                raise CharacterError('budget')
            job['quote_approvals'] = [{'usd': job['quote_total_usd'], 'scope': 'initial', 'at': now().isoformat()}]
            job['approved_plan_hash'] = job['plan_hash']
            for scene in job['scenes']:
                scene['approved_template_hash'] = fp(scene['payload'])
                scene['state'] = 'waiting_dependency' if scene['continuity'] == 'continue' else 'ready'
            job['state'] = 'generating'
            s.save(job)
            self.dispatch(job)

    def dispatch(self, job):
        """Only already approved cuts/dependencies. No retry, even on HTTP timeout."""
        s = self.owner
        if job.get('approved_plan_hash') != job['plan_hash']:
            raise CharacterError('blocked')
        ready = [row for row in job['scenes'] if row['state'] == 'ready']
        for row in ready:
            row.update(state='submitting', submitted_at=now().isoformat())
        s.save(job)  # Persist all intents before any concurrent POST.
        failure = False
        with ThreadPoolExecutor(max_workers=min(20, max(1, len(ready)))) as pool:
            futures = {pool.submit(copy_context().run, s.video_for(job).submit_scene, row['payload'], row['idempotency_key']): row for row in ready}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    row.update(handle=future.result(), state='submitted')
                except Exception:
                    row['state'] = 'unknown'
                    failure = True
                s.save(job)
        if failure:
            job['state'] = 'submission_unknown'
            s.save(job)
            raise CharacterError('blocked')

    def last_frame(self, job, parent):
        s = self.owner
        folder = s.folder(job['id'])
        clip = folder / parent['file']
        if parent['state'] != 'downloaded' or digest(clip) != parent['sha256']:
            raise CharacterError('media')
        frames = folder / 'frames'
        if frames.is_symlink() or frames.is_junction():
            raise CharacterError('reference')
        frames.mkdir(exist_ok=True)
        output = frames / f'scene-{parent["position"]}-t{parent["attempt"]}-last.png'
        if output.exists():
            if output.is_symlink() or output.is_junction() or digest(output) != parent.get('last_frame_sha256'):
                raise CharacterError('media')
        else:
            binary = str(FFmpegAdapter.executable('ffmpeg', s.ffmpeg))
            run([binary, '-nostdin', '-n', '-v', 'error', '-protocol_whitelist', 'file',
                 '-format_whitelist', FORMAT_WHITELIST, '-sseof', '-0.1', '-i', str(clip.resolve()),
                 '-frames:v', '1', '-update', '1', str(output.resolve())], folder)
            reference_bytes(output)
            parent['last_frame_sha256'] = digest(output)
            s.save(job)
        return output

    def check(self, identifier, *, consent=False):
        s = self.owner
        s.consent(consent)
        with s.lock():
            job = s.read(identifier)
            if job['state'] not in {'generating', 'scene_review', 'submission_unknown', 'status_or_download_failed'}:
                raise CharacterError('blocked')
            video = s.video_for(job)
            folder = s.folder(identifier)
            for row in job['scenes']:
                if row['state'] == 'downloaded':
                    if digest(folder / row['file']) != row['sha256']:
                        raise CharacterError('media')
                    continue
                if row['state'] not in {'submitted', 'downloading'}:
                    continue
                try:
                    result = video.check(row['handle'])
                    if result.state in {'failed', 'nsfw', 'canceled'}:
                        row.update(state=result.state, finished_at=now().isoformat())
                        s.save(job)
                    elif result.state == 'completed':
                        filename = f'scene-{row["position"]}.mp4' if row['attempt'] == 1 else f'scene-{row["position"]}-t{row["attempt"]}.mp4'
                        path = folder / filename
                        row['state'] = 'downloading'
                        row['download_expected'] = {'request_id': row['handle']['request_id'], 'seconds': row['seconds']}
                        s.save(job)
                        if path.exists():
                            if path.is_symlink() or path.is_junction() or not path.is_file():
                                raise CharacterError('media')
                            current_hash = digest(path)
                            if row.get('download_sha256') != current_hash:
                                receipt = row.get('partial_download_receipt', {})
                                if (receipt.get('request_id') != row['handle']['request_id']
                                        or receipt.get('sha256') != current_hash
                                        or receipt.get('bytes') != path.stat().st_size):
                                    raise CharacterError('media')  # Foreign/unowned bytes are never replaced.
                                archived = folder / f'partial-s{row["position"]}-t{row["attempt"]}-{uuid4().hex}.mp4'
                                path.rename(archived)  # Preserve the owned failed transfer, never delete it.
                                row.setdefault('partial_downloads', []).append({**receipt, 'file': archived.name})
                                row.pop('partial_download_receipt', None)
                                row.pop('download_sha256', None)
                                s.save(job)
                        if not path.exists():
                            try:
                                video.fetch(result, path, Event())
                            except Exception:
                                if path.is_file() and not path.is_symlink() and not path.is_junction():
                                    row['partial_download_receipt'] = {
                                        'request_id': row['handle']['request_id'],
                                        'sha256': digest(path), 'bytes': path.stat().st_size}
                                raise
                        row['download_sha256'] = digest(path)
                        s.save(job)
                        info = probe_clip(path, s.ffprobe)
                        if info['duration'] < row['seconds'] - .2:
                            raise CharacterError('media')
                        row.update(state='downloaded', file=path.name, sha256=digest(path), media=info,
                                   finished_at=now().isoformat())
                        s.save(job)
                except Exception:
                    job['state'] = 'status_or_download_failed'
                    s.save(job)
                    raise CharacterError('provider') from None
            uncertain = any(r['state'] in {'unknown', 'submitting'} for r in job['scenes'])
            if not uncertain:
                for row in job['scenes']:
                    if row['state'] != 'waiting_dependency':
                        continue
                    parent = job['scenes'][row['from'] - 1]
                    if parent['state'] != 'downloaded':
                        continue
                    if fp(row['payload']) != row['approved_template_hash']:
                        raise CharacterError('blocked')
                    # The only dynamic field is the approved dependency's verified last frame.
                    frame = self.last_frame(job, parent)
                    row['state'] = 'preparing_dependency'
                    s.save(job)
                    try:
                        public = video.upload_reference(frame)
                        payload = self.with_start(job, row['payload'], public)
                        quote = amount(video.estimate(payload))
                        if quote > amount(row['quote_usd']):
                            row['state'] = 'dependency_quote_changed'
                            job['state'] = 'scene_review'
                            s.save(job)
                            raise CharacterError('budget')
                        row.update(payload=payload, state='ready', dependency={
                            'position': parent['position'], 'attempt': parent['attempt'],
                            'clip_sha256': parent['sha256'], 'frame_sha256': digest(frame)},
                            execution_quote_usd=str(quote))
                        s.save(job)
                    except Exception:
                        if row['state'] == 'preparing_dependency':
                            row['state'] = 'dependency_failed'
                            job['state'] = 'scene_review'
                            s.save(job)
                        raise CharacterError('provider') from None
                self.dispatch(job)
            states = {r['state'] for r in job['scenes']}
            job['state'] = ('clips_review' if states == {'downloaded'} else 'submission_unknown' if uncertain else
                            'scene_review' if states & {'failed', 'nsfw', 'canceled', 'dependency_failed', 'dependency_quote_changed'} else 'generating')
            s.save(job)

    def update_settings(self, identifier, settings, episode_limit):
        s = self.owner
        frozen = snapshot(settings)
        with s.lock():
            job = s.read(identifier)
            if job['state'] not in {'script_review', 'quoted'} or job.get('quote_approvals'):
                raise CharacterError('blocked')
            old = check(job['studio_selection'])
            if settings['duration'] != old['duration'] or settings['script_model'] != old['script_model']:
                raise CharacterError('retime')  # A different target requires a newly generated script.
            candidate = {**job, 'studio_selection': frozen}
            story = self.validate(candidate, job['script'])
            job.setdefault('quote_history', []).append({k: deepcopy(job[k]) for k in
                ('scenes', 'quote_hash', 'quote_total_usd', 'quoted_at') if k in job})
            job.update(studio_selection=frozen, model=settings['video_model'], episode_limit=str(amount(episode_limit)),
                       prompts=prompts(story, settings, job['character']), state='script_review', scenes=[])
            for key in ('script_approval', 'quote_hash', 'quote_total_usd', 'quoted_at', 'quote_key_id'):
                job.pop(key, None)
            job['plan_hash'] = s.plan_hash(job)
            s.save(job)
