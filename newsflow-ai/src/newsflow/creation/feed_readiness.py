"""Read-only production image readiness. No key decryption or network requests.

Official prices are token rates, not a guaranteed per-image ceiling. The Images
API reference exposes no per-request USD cap/quote endpoint. App budget
readiness is separate from a provider-guaranteed maximum charge.
"""
from newsflow.creation.catalog import IMAGE_MODELS
from . import image_pricing as rates
from .feed_costs import fingerprint
from datetime import datetime,timezone
from newsflow.intelligence.provider_connections import revision
from newsflow.intelligence.provider_connections import ProviderConnections

PRICING_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-image-2.5-flare'
GUIDE_SOURCE = 'https://developers.openai.com/api/docs/guides/image-generation'
CHECKED_ON = '2026-11-01'

class FeedReadiness:
    def __init__(self, state):
        self.connections = ProviderConnections(state)

    def standing_limit(self):
        from newsflow.intelligence.api_settings import read_api_settings
        saved=read_api_settings(self.connections.sessions,'openai')
        return str(saved.request_limit_usd) if saved.approved and saved.request_limit_usd>0 else None

    def account_scope(self):
        status=self.connections.status('openai','image')
        rev=revision(self.connections.stores['openai'])
        if not rev or not status.get('verified') or not status.get('modelVerified'):return None
        return fingerprint({'credentialRevision':rev,'model':status['model'],'checkedAt':status.get('checkedAt')})

    def __call__(self, selection):
        status = self.connections.status('openai', 'image')
        configured = status.get('configured') is True
        model = selection.get('model')
        verified = bool(configured and status.get('verified') and status.get('modelVerified')
                        and status.get('model') == model)
        reasons = []
        if not configured: reasons.append('설정에서 OpenAI 키를 등록하세요.')
        elif not verified: reasons.append('선택한 이미지 모델의 저장된 연결 확인이 필요합니다.')
        valid=rates.current(datetime.now(timezone.utc).timestamp())
        reasons.append('앱 작업 예산을 계산하고 승인하세요. 실제 청구액과 다를 수 있습니다.' if valid else '공식 이미지 단가 갱신이 필요합니다.')
        return {'keyConfigured': configured, 'modelVerified': verified,
                'costBoundVerified': False, 'budgetAvailable':valid, 'generationEnabled':verified and valid,
                'code': 'app_budget_ready' if verified and valid else 'model_unverified' if configured else 'key_missing',
                'message': ' '.join(reasons),
                'rateReference': ({'textInputPerMillionUsd':'5.00', 'imageOutputPerMillionUsd':'30.00',
                                   'source':PRICING_SOURCE, 'guide':GUIDE_SOURCE, 'checkedOn':CHECKED_ON,
                                   'guaranteedMaximum':False} if model in IMAGE_MODELS else None)}
