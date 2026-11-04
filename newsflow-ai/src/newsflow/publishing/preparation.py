"""Local platform review for any completed content; never a transmission grant."""
from datetime import UTC, datetime
from .posting_copy import platforms_for
from .service import PublishingError
from .sensitive_topics import image_review_required

def validate_preparation(source,value):
    if not isinstance(value,dict) or set(value)-{'image_safety_checked'}!={'platforms','content_reviewed','rights_reviewed','sources_reviewed'}:
        raise PublishingError('게시 준비 항목을 확인하세요.')
    if image_review_required(source) and value.get('image_safety_checked') is not True:
        raise PublishingError('AI 이미지 안전 확인을 체크해 주세요.')
    targets=value['platforms']
    if (not isinstance(targets,list) or not targets or len(targets)>4
            or any(type(x) is not str for x in targets) or len(set(targets))!=len(targets)
            or not set(targets)<=set(platforms_for(source))):
        raise PublishingError('이 콘텐츠를 지원하는 플랫폼을 선택하세요.')
    if any(value[k] is not True for k in ('content_reviewed','rights_reviewed','sources_reviewed')):
        raise PublishingError('콘텐츠·권리·출처 검토를 확인하세요.')
    return {**value,'platforms':sorted(targets),'saved_at':datetime.now(UTC).isoformat(),
            'status':'prepared','published':False,'transmission_approved':False}
