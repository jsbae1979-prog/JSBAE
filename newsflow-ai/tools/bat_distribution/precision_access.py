"""Authenticated precision story/image capabilities; no startup or replay calls."""
from contextvars import ContextVar
from decimal import Decimal
import re
import time
from urllib.parse import parse_qs

from newsflow.character.authoring import AuthoringAI, provider_for_model
from newsflow.character.kling import check
from newsflow.character.precision import PrecisionService, positive
from newsflow.character.precision_contract import INSTRUCTION, PrecisionScenario, story_input, image_prompt
from newsflow.character.registry import CharacterRegistry
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint
from newsflow.creation.catalog import check_snapshot
from newsflow.creation.feed_readiness import FeedReadiness
from newsflow.creation.image_studio import ImageStudio
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, CredentialError
from newsflow.publishing.image_generation import ImageGenerationService
from newsflow.video_models.catalog import CATALOG
from .character_authoring import _Store, _unlinked

BASE = '/api/studio/character-precision'
PAID = re.compile(BASE + r'/([a-f0-9]{32})/(story|generate)\Z')
_REQUEST = ContextVar('precision_operating_request', default=None)
_KEY = ContextVar('precision_operating_key', default=None)


def deny():
    raise CharacterError('blocked')


class _Authoring(AuthoringAI):
    def __init__(self, owner, keys, budget, providers):
        self.owner = owner
        super().__init__(keys, budget, providers)

    def generate(self, instruction, payload, schema, options, *, provider, request_id,
                 consent=False, image_bytes=None, kind='script', max_reserved_usd=None, story_review=None):
        self.last_usage = self.last_candidate = self.last_reservation = None
        self.last_reserved_usd = '0'
        self.response_received = False
        self.last_failure = {'stage': 'preflight', 'dispatched': False, 'response_received': False}
        active = self.owner.request('story')
        w = self.owner.service().read(active['id'])
        settings = check(w['video_settings'])
        expected = 'episode:' + w['id'] + ':script:1'
        attempts = w['story_attempts']
        if (active['used'] or consent is not True or image_bytes is not None or story_review is not None
                or schema is not PrecisionScenario or instruction != INSTRUCTION or kind != 'script'
                or w['state'] != 'writing' or w['revision'] != active['revision'] or w['scenario']
                or len(attempts) != 1 or attempts[0]['state'] != 'requesting'
                or request_id != expected or attempts[0]['request_id'] != expected
                or options.model != settings['script_model'] or provider != provider_for_model(options.model)
                or options.max_tokens != 6000 or max_reserved_usd != w['video_limit']
                or payload != story_input(w['common'], w['cast'], CATALOG.model(settings['video_model']))):
            deny()
        active['used'] = True
        token = _KEY.set((self.owner, active, provider))
        try:
            return super().generate(instruction, payload, schema, options, provider=provider,
                request_id=request_id, consent=consent, kind=kind, max_reserved_usd=max_reserved_usd)
        finally:
            _KEY.reset(token)


class _Generation(ImageGenerationService):
    def __init__(self, owner, adapter):
        self.owner = owner
        super().__init__(owner.app.state.sessions, owner.profile, owner.keys['openai'], adapter=adapter)

    def _generate(self, article_id, analysis_id, rank, style, context, prompt, **kw):
        owner = self.owner
        active = owner.request('generate')
        service = owner.service()
        w = service.read(active['id'])
        identifier = kw.get('draft_id')
        rows = [(s, v) for s in w['scenes'] for v in s['versions'] if v.get('draft_id') == identifier]
        if len(rows) != 1 or identifier in active['drafts']:
            deny()
        scene, version = rows[0]
        approvals = [e for e in w['events'] if e['kind'] == 'image_approval'
                     and e['quote']['hash'] == active['quote_hash']]
        if len(approvals) != 1 or approvals[0]['reference_consent'] is not True:
            deny()
        q = approvals[0]['quote']
        if (w['state'] != 'generating' or version['state'] != 'requesting'
                or version is not scene['versions'][-1] or version['quote_hash'] != active['quote_hash']
                or q['hash'] != fingerprint({k: v for k, v in q.items() if k != 'hash'})
                or q['revision'] + 1 != w['revision'] or q['expires'] <= time.time()
                or scene['plan']['no'] not in q['numbers']
                or version['plan_hash'] != fingerprint(scene['plan'])
                or prompt != scene['prompt'] or prompt != version['prompt']
                or prompt != image_prompt(w['common'], w['cast'], scene['plan'])):
            deny()
        draft = owner.images.get(identifier)
        refs = service.refs(w, scene)
        expected_refs = [{'id': cid, 'asset': w['cast'][cid]['asset'], 'version': w['cast'][cid]['image_version']}
                         for cid in scene['plan']['characters']]
        if (style != 'studio' or any(x is not None for x in (article_id, analysis_id, rank))
                or context != {'image_studio_draft': identifier} or kw.get('provider', 'openai') != 'openai'
                or kw.get('card_id') is not None or kw.get('reference') != refs
                or draft.result['prompt'] != prompt or draft.options.get('reference')
                or draft.options.get('references') != [r['asset'] for r in expected_refs]
                or version['references'] != expected_refs or version['selection'] != w['selection']
                or kw.get('execution') != draft.options['selection']
                or check_snapshot(draft.options['selection'], 'image') != w['selection']):
            deny()
        if owner.images.output(identifier):
            deny()  # Local reconciliation may recover it; never send it again.
        bound = next(b for b in q['bounds'] if b['no'] == scene['plan']['no'])
        if version['reserve_usd'] != bound['reserveUsd'] or service.estimate(w, scene)['reserveUsd'] != bound['reserveUsd']:
            deny()
        # Keep the whole approved batch reserved, including not-yet-created drafts.
        old = sum(max(Decimal(v['reserve_usd']), Decimal(v.get('observed_usd') or '0')) for s in w['scenes'] for v in s['versions']
                  if v['quote_hash'] != q['hash'])
        total = old + positive(q['reserve_usd'])
        if Decimal(q['reserve_usd']) != sum(positive(b['reserveUsd']) for b in q['bounds']):
            deny()
        active.update(scope=q['account_scope'], selection=w['selection'], total=total, limit=w['image_limit'])
        owner.image_ready(active)
        active['drafts'].add(identifier)
        token = _KEY.set((owner, active, 'openai'))
        try:
            # Existing engine durably claims the request before its sole transport call.
            return super()._generate(article_id, analysis_id, rank, style, context, prompt, **kw)
        finally:
            _KEY.reset(token)


class PrecisionAccess:
    def __init__(self, app, profile, nativefactory, *, adapter=None, providers=None, budget=None):
        self.app, self.profile = app, _unlinked(profile)
        if self.profile != _unlinked(app.state.config.data_dir):
            deny()
        self.ready = FeedReadiness(app.state)
        native = nativefactory()
        self.keys = {provider: _Store(self, provider, kind, native) for provider, kind in
                     (('claude_api', AnthropicKeyStore), ('openai', AIKeyStore))}
        self.generation = _Generation(self, adapter)
        self.images = ImageStudio(app.state.sessions, self.profile, self.generation)
        self.authoring = _Authoring(self, self.keys, budget or APIBudgetService(app.state.sessions), providers)
        app.state.precision_image_studio = self.images
        app.state.precision_authoring = self.authoring

    def service(self):
        return PrecisionService(self.profile, CharacterRegistry(self.profile, self.images),
                                self.images, self.ready, self.app.state.character, self.authoring)

    def request(self, action):
        active = _REQUEST.get()
        if not isinstance(active, dict) or active.get('owner') is not self or active.get('action') != action:
            deny()
        return active

    def image_ready(self, active):
        limit = self.ready.standing_limit()
        if (not limit or active['scope'] != self.ready.account_scope()
                or not self.ready(active['selection'])['generationEnabled']
                or active['total'] > min(positive(limit), positive(active['limit']))):
            deny()

    def active_key(self, provider):
        active = _REQUEST.get()
        if not active or active.get('owner') is not self or _KEY.get() != (self, active, provider):
            raise CredentialError('현재 승인된 정밀 제작 요청에서만 키를 사용할 수 있습니다.')
        if active['action'] == 'generate':
            if provider != 'openai': deny()
            self.image_ready(active)

    def wrap(self, normal, authenticated):
        async def call(scope, receive, send):
            path = scope.get('path', '')
            if scope.get('type') == 'http' and scope.get('method') == 'GET' and path == BASE:
                return await authenticated({**scope, 'newsflow.precision_paid_available': True}, receive, send)
            match = PAID.fullmatch(path)
            if scope.get('type') != 'http' or scope.get('method') != 'POST' or not match:
                return await normal(scope, receive, send)
            try:
                headers = dict(scope.get('headers', []))
                if headers.get(b'content-type', b'').split(b';')[0] != b'application/x-www-form-urlencoded': deny()
                body = b''
                while True:
                    message = await receive()
                    if message['type'] != 'http.request': deny()
                    body += message.get('body', b'')
                    if len(body) > 4096: deny()
                    if not message.get('more_body'): break
                values = parse_qs(body.decode('utf8'), keep_blank_values=True)
                if any(len(v) != 1 for v in values.values()) or values.get('consent') != ['true']: deny()
                active = {'owner': self, 'id': match[1], 'action': match[2], 'used': False, 'drafts': set()}
                if match[2] == 'story':
                    active['revision'] = int(values['revision'][0])
                    if active['revision'] < 1: deny()
                else:
                    active['quote_hash'] = values['quote_hash'][0]
                    if values.get('reference_consent') != ['true'] or not re.fullmatch('[a-f0-9]{64}', active['quote_hash']): deny()
            except (CharacterError, ValueError, KeyError, UnicodeError):
                await send({'type': 'http.response.start', 'status': 403, 'headers': []})
                return await send({'type': 'http.response.body', 'body': b'Precision request scope denied.'})
            delivered = False
            async def replay():
                nonlocal delivered
                if delivered: return await receive()
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            token = _REQUEST.set(active)
            try:
                return await authenticated(scope, replay, send)
            finally:
                _REQUEST.reset(token)
        return call


def install(app, profile, nativefactory):
    if getattr(app.state, 'precision_authoring', None) is not None:
        deny()
    return PrecisionAccess(app, profile, nativefactory)
