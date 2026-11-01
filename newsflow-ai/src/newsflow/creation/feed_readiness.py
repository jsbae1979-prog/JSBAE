"""Read-only production image readiness. No key decryption or network requests.

Official prices are token rates, not a guaranteed per-image ceiling. The Images
API reference exposes no per-request USD cap/quote endpoint. Do not fabricate
an upperBoundVerified receipt from a public estimate or a user-entered price.
"""
from newsflow.creation.catalog import IMAGE_MODELS
from newsflow.intelligence.provider_connections import ProviderConnections

PRICING_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-image-2.5-flare'
GUIDE_SOURCE = 'https://developers.openai.com/api/docs/guides/image-generation'
CHECKED_ON = '2026-11-01'

class FeedReadiness:
    def __init__(self, state):
        self.connections = ProviderConnections(state)

    def __call__(self, selection):
        status = self.connections.status('openai', 'image')
        configured = status.get('configured') is True
        model = selection.get('model')
        verified = bool(configured and status.get('verified') and status.get('modelVerified')
                        and status.get('model') == model)
        reasons = []
        if not configured: reasons.append('설정에서 OpenAI 키를 등록하세요.')
        elif not verified: reasons.append('선택한 이미지 모델의 저장된 연결 확인이 필요합니다.')
        reasons.append('이미지 총비용 상한 확인 연결이 필요합니다. 공개 단가만으로 생성을 승인하지 않습니다.')
        return {'keyConfigured': configured, 'modelVerified': verified,
                'costBoundVerified': False, 'generationEnabled': False,
                'code': 'cost_bound_unavailable' if verified else 'model_unverified' if configured else 'key_missing',
                'message': ' '.join(reasons),
                'rateReference': ({'textInputPerMillionUsd':'5.00', 'imageOutputPerMillionUsd':'30.00',
                                   'source':PRICING_SOURCE, 'guide':GUIDE_SOURCE, 'checkedOn':CHECKED_ON,
                                   'guaranteedMaximum':False} if model == IMAGE_MODELS[0] else None)}
