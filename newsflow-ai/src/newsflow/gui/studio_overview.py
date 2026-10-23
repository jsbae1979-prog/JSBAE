"""Read-only cross-content projections over existing records; no credentials or execution."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlencode

from sqlalchemy import func, select

from newsflow.db.models import ImagePost, ImagePostDelivery, IntelligenceRun

CHARACTER_STATES = {
    'needs_script': ('prepare', '대본 준비', '대본 준비 열기'),
    'writing': ('running', '대본 작성 중', '대본 상태 확인'),
    'script_review': ('review', '대본 검토', '대본 검토하기'),
    'preparing': ('running', '견적 확인 중', '견적 상태 확인'),
    'quoted': ('review', '생성 승인 대기', '장면·견적 검토'),
    'generating': ('running', '장면 생성 중', '생성 상태 확인'),
    'retry_quoted': ('review', '추가 승인 대기', '추가 견적 검토'),
    'retry_quoting': ('running', '추가 견적 확인 중', '추가 견적 상태 확인'),
    'scene_review': ('review', '장면 처리 확인 필요', '장면 결과 확인'),
    'clips_review': ('review', '장면 검토', '장면 검토하기'),
    'composing': ('running', '합성 중', '합성 상태 확인'),
    'completed': ('saved', '영상 저장 기록', '영상 확인하기'),
    'submission_unknown': ('attention', '제출 결과 불명', '제출 기록 확인'),
    'script_failed': ('attention', '대본 작성 실패', '대본 오류 확인'),
    'prepare_failed': ('attention', '생성 준비 실패', '준비 오류 확인'),
    'status_or_download_failed': ('attention', '장면 확인·저장 실패', '장면 기록 확인'),
    'retry_quote_failed': ('attention', '추가 견적 확인 실패', '견적 오류 확인'),
    'compose_failed': ('attention', '영상 합성 실패', '합성 오류 확인'),
}
DELIVERY_STATES = {
    'failed': ('attention', '게시 실패', '게시 오류 확인'),
    'unknown': ('attention', '게시 결과 불명', '게시 결과 확인'),
    'ready': ('review', '공개 게시 승인 대기', '게시 검토 열기'),
    'processing': ('running', '게시 처리 확인 필요', '게시 상태 확인'),
    'checking': ('running', '게시 상태 확인 중', '게시 상태 확인'),
    'preparing': ('running', '이미지 전송 중', '전송 상태 확인'),
    'publishing': ('running', '게시 중', '게시 상태 확인'),
    'published': ('saved', '게시 완료 기록', '게시 결과 확인'),
    'published_no_link': ('attention', '게시 ID 저장 · 링크 확인 필요', '게시 결과 확인'),
}


def recorded_at(value) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value or '')
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=UTC)


def overview(session, news_tasks, news_outputs, character_jobs) -> dict:
    rows, outputs = [], []
    for task in news_tasks:
        state = ('saved' if task['completed'] else 'running' if task['status'] in {'running', 'queued'} else
                 'attention' if task['status'] in {'failed', 'unknown', 'interrupted', 'cancelled'} else 'review')
        rows.append({'id': 'news:' + task['id'], 'type': 'news', 'type_label': '뉴스 쇼츠', 'icon': 'news',
                     'title': task['title'], 'category': state, 'label': task['status_label'],
                     'next_action': task['next_action'], 'href': task.get('workspace_href') or task['href'],
                     'at': recorded_at(task.get('updated_at')), 'legacy_task': task})
    for item in news_outputs:
        outputs.append({'type': 'news', 'type_label': '뉴스 쇼츠', 'format': 'video', 'title': item['title'],
                        'at': recorded_at(item.get('recorded_at')), 'href': item['link'],
                        'media_url': item['media_url'], 'download_url': item['download_url'],
                        'poster': f"/video/jobs/{item['id']}/thumbnail", 'duration': item['duration'],
                        'preview_only': item['preview_only'],
                        'notice': ('검토용 초안 · ' if item['preview_only'] else '') +
                                  ('AI 생성 장면 포함 · 실제 촬영 영상 아님' if item['ai_scenes'] else
                                   '내용·음성·자막 검토 필요')})
    for job in character_jobs[:100]:
        if not isinstance(job.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', job['id']):
            continue
        category, label, action = CHARACTER_STATES.get(job.get('state'), ('attention', '확인 필요', '중단 원인 확인'))
        output = job.get('output') if isinstance(job.get('output'), dict) else {}
        if category == 'saved' and not re.fullmatch('[a-f0-9]{64}', str(output.get('sha256', ''))):
            category, label, action = 'attention', '저장 파일 확인 필요', '작업 기록 확인'
        href = '/character?' + urlencode({'job_id': job['id']})
        at = recorded_at(job.get('created_at'))
        script = job.get('script') if isinstance(job.get('script'), dict) else {}
        rows.append({'id': 'character:' + job['id'], 'type': 'character', 'type_label': '캐릭터 쇼츠',
                     'icon': 'character', 'title': script.get('title') or job.get('topic', '캐릭터 작업'),
                     'category': category, 'label': label, 'next_action': action, 'href': href, 'at': at})
        if category == 'saved':
            outputs.append({'type': 'character', 'type_label': '캐릭터 쇼츠', 'format': 'video',
                            'title': rows[-1]['title'], 'at': at, 'href': href, 'poster': None, 'duration': 30,
                            'media_url': f"/character/{job['id']}/file",
                            'download_url': f"/character/{job['id']}/file?download=true",
                            'notice': 'AI 생성 · 가상 이야기 · 최종 시청 검토 필요'})
    posts = list(session.scalars(select(ImagePost).order_by(ImagePost.id.desc()).limit(100)))
    latest_ids = select(func.max(ImagePostDelivery.id)).where(
        ImagePostDelivery.post_id.in_([post.id for post in posts])).group_by(
            ImagePostDelivery.post_id, ImagePostDelivery.account_id)
    deliveries = list(session.scalars(select(ImagePostDelivery).where(ImagePostDelivery.id.in_(latest_ids))))
    by_post = {}
    for delivery in deliveries:
        by_post.setdefault(delivery.post_id, []).append(delivery)
    used_runs = set()
    for post in posts:
        sources = post.sources if isinstance(post.sources, dict) else {}
        for key in ('claude_card_run_id', 'generated_image_run_id'):
            if type(sources.get(key)) is int:
                used_runs.add(sources[key])
        category, label, action = ('saved', '이미지 저장 기록', '이미지 확인·게시 준비')
        attempts = by_post.get(post.id, [])
        delivery = max(attempts, key=lambda d: ({'attention': 3, 'running': 2, 'review': 1, 'saved': 0}.get(
            DELIVERY_STATES.get(d.status, ('attention', '', ''))[0], 3), d.created_at)) if attempts else None
        if delivery:
            category, label, action = DELIVERY_STATES.get(delivery.status, ('attention', '게시 상태 확인 필요', '기록 확인'))
            if len(attempts) > 1:
                label = '계정별 확인 · ' + label
        href = f'/image-posts?post_id={post.id}#image-result'
        rows.append({'id': f'image:{post.id}', 'type': 'image', 'type_label': '이미지 게시물', 'icon': 'image',
                     'title': post.title, 'category': category, 'label': label, 'next_action': action,
                     'href': href, 'at': recorded_at(delivery.created_at if delivery else post.created_at)})
        outputs.append({'type': 'image', 'type_label': '이미지 게시물', 'format': 'image', 'title': post.title,
                        'at': recorded_at(post.created_at), 'href': href, 'media_url': f'/image-posts/{post.id}/file',
                        'download_url': f'/image-posts/{post.id}/file?download=true',
                        'notice': '저장 이미지 · 공개 게시 여부는 별도 확인'})
    runs = list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind.in_(('feed_card', 'feed_image')))
                               .order_by(IntelligenceRun.id.desc()).limit(100)))
    used_runs.update(r.options.get('claude_card_run_id') for r in runs
                     if isinstance(r.options, dict) and type(r.options.get('claude_card_run_id')) is int)
    for run in runs:
        if run.id in used_runs:
            continue
        options = run.options if isinstance(run.options, dict) else {}
        article_id = options.get('article_id')
        query = {'article_id': article_id} if type(article_id) is int and article_id > 0 else {}
        if (type(options.get('analysis_id')) is int and options['analysis_id'] > 0
                and type(options.get('rank')) is int and options['rank'] in (1, 2, 3)):
            query.update(analysis_id=options['analysis_id'], rank=options['rank'])
        if type(options.get('draft_id')) is int and options['draft_id'] > 0:
            query['draft_id'] = options['draft_id']
        if run.status == 'success' and query.get('article_id'):
            query['card_id' if run.kind == 'feed_card' else 'generated_id'] = run.id
        href = '/image-posts' + ('?' + urlencode(query) if query else '')
        category = 'review' if run.status == 'success' else 'running' if run.status == 'running' else 'attention'
        plan = run.result.get('plan', {}) if isinstance(run.result, dict) else {}
        title = plan.get('title') if isinstance(plan, dict) else None
        rows.append({'id': f'image-run:{run.id}', 'type': 'image', 'type_label': '이미지 게시물', 'icon': 'image',
                     'title': title or '이미지 제작 기록', 'category': category,
                     'label': '문구·이미지 검토' if category == 'review' else '제작 중' if category == 'running' else '결과 확인 필요',
                     'next_action': '초안 검토·이미지 저장' if category == 'review' else '기록 확인 · 자동 재실행 없음',
                     'href': href, 'at': recorded_at(run.created_at)})
    rows.sort(key=lambda row: row['at'], reverse=True)
    totals, bounded = {}, []
    for row in rows:
        totals[row['type']] = totals.get(row['type'], 0) + 1
        if totals[row['type']] <= 100:
            bounded.append(row)
    rows = sorted(bounded, key=lambda row: (row['category'] == 'running', row['at']), reverse=True)
    actionable = [row for row in rows if row['category'] != 'saved']
    outputs.sort(key=lambda row: row['at'], reverse=True)
    return {'rows': rows, 'active': actionable, 'focus': actionable[0] if actionable else None,
            'outputs': outputs[:6], 'latest_output': outputs[0] if outputs else None,
            'counts': {'active': len(actionable), 'review': sum(r['category'] == 'review' for r in rows),
                       'running': sum(r['category'] == 'running' for r in rows), 'outputs': len(outputs)},
            'scope': '최근 뉴스·캐릭터·이미지 기록 기준 · 유형별 최대 100건 · 저장과 공개 게시는 별개'}
