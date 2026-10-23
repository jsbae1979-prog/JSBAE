"""One presentation-only catalogue for content entry points and sidebar ownership."""
from __future__ import annotations

CONTENT_TYPES = (
    {'id': 'news', 'label': '뉴스 쇼츠', 'icon': 'news', 'href': '/create',
     'description': '뉴스 자료로 대본·음성·세로 영상 만들기'},
    {'id': 'character', 'label': '캐릭터 쇼츠', 'icon': 'character', 'href': '/character',
     'description': '주제로 캐릭터 이야기·장면 만들기'},
    {'id': 'image', 'label': '이미지 게시물', 'icon': 'image', 'href': '/image-posts',
     'description': '뉴스를 이미지 한 장과 본문으로 만들기'},
)

NAV_GROUPS = (
    ('작업실', (('home', '/', '대시보드', 'home'), ('tasks', '/?show=tasks', '진행 · 검토', 'clock'))),
    ('만들기', tuple(('news-create' if item['id'] == 'news' else item['id'], item['href'],
                     item['label'], item['icon']) for item in CONTENT_TYPES)),
    ('자료 · 보관', (('news', '/news', '뉴스 자료', 'folder'), ('script', '/ai', 'AI 대본', 'edit'),
                    ('videos', '/videos', '뉴스 영상', 'video'), ('voices', '/voices', '음성 · 샘플', 'voice'))),
    ('게시 · 운영', (('publish', '/queue', '게시 허브', 'send'), ('analytics', '/analytics', '성과 분석', 'chart'),
                    ('schedules', '/schedules', '예약 제작', 'clock'),
                    ('settings', '/simple-settings', '설정', 'settings'))),
)


def navigation_context(path: str, query) -> dict:
    content = next((item for item in CONTENT_TYPES if path == item['href'] or path.startswith(item['href'] + '/')), None)
    if path == '/':
        current = ('tasks' if query.get('show') == 'tasks' else 'videos' if query.get('video') or query.get('show') == 'videos'
                   else 'news-create' if query.get('task') or query.get('guide') else 'home')
    elif content:
        current = 'news-create' if content['id'] == 'news' else content['id']
    elif path == '/schedules':
        current = 'schedules'
    elif path in {'/voices', '/video/tts'}:
        current = 'voices'
    elif path.startswith('/news') or path == '/sources':
        current = 'news'
    elif path == '/ai' or path.startswith('/ai/drafts/'):
        current = 'script'
    elif path == '/videos' or path.startswith('/video/jobs/'):
        current = 'videos'
    elif path in {'/create', '/video', '/video/ai'} or path.startswith(('/autopilot', '/video/ai/plans/')):
        current = 'news-create'
    elif path == '/workspace/trash':
        current = 'tasks'
    elif path == '/analytics':
        current = 'analytics'
    elif path == '/publishing/platforms':
        current = 'settings'
    elif path == '/queue' or path.startswith('/publishing'):
        current = 'publish'
    else:
        current = 'settings'
    groups = [{'label': label, 'items': [{'id': key, 'href': href, 'label': text, 'icon': icon,
                 'selected': key == current, 'secondary': key in {'script', 'videos', 'voices', 'analytics'}}
                for key, href, text, icon in entries]} for label, entries in NAV_GROUPS]
    selected = next(item for group in groups for item in group['items'] if item['selected'])
    tools = [item for group in groups for item in group['items'] if item['secondary']]
    return {'groups': groups, 'tools': tools, 'tools_open': any(item['selected'] for item in tools),
            'current': current, 'label': selected['label'], 'icon': selected['icon']}
