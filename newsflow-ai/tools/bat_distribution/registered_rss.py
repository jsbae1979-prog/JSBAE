"""Manual registered public RSS only; no credentials, AI, scheduler or URL input."""
from urllib.parse import urlsplit
from sqlalchemy import select
from newsflow.db.models import NewsSource
from newsflow.news.rss_adapter import validate_url, URLPolicyError
from newsflow.news.service import NewsService

# Discovery/AI source rows coexist with RSS in the legacy table. They are never
# feed inputs. This scope does not enable their adapters or load their keys.
PROVIDER_DOMAINS = ('anthropic.com', 'openai.com', 'elevenlabs.io', 'higgsfield.ai', 'serpapi.com')

def public_feed(url):
    try:
        normalized = validate_url(url)
        host = urlsplit(normalized).hostname
        return not any(host == domain or host.endswith('.' + domain) for domain in PROVIDER_DOMAINS)
    except (URLPolicyError, TypeError, ValueError):
        return False

class RegisteredRSSService(NewsService):
    def collect(self, run_id, source_ids=None):
        with self.sessions() as session:
            rows = session.scalars(select(NewsSource).where(NewsSource.enabled).order_by(NewsSource.id))
            ids = [row.id for row in rows if public_feed(row.url)
                   and (source_ids is None or row.id in source_ids)]
        # Reuse the normal collector, public DNS pinning, robots, limits, lock,
        # history and lifecycle. In particular do not replace lifecycle.py.
        return super().collect(run_id, ids)

def install(app):
    coordinator = app.state.coordinator
    previous = coordinator.service
    coordinator.service = RegisteredRSSService(previous.sessions, previous.collector)
    class Requests:
        def wrap(self, normal, authenticated):
            class Boundary:
                async def __call__(self, scope, receive, send):
                    if (scope.get('type') == 'http' and scope.get('method') == 'POST'
                            and scope.get('path') == '/collection'):
                        # LocalAccess and original CSRF/Origin middleware run
                        # before the unchanged form handler starts its worker.
                        return await authenticated(scope, receive, send)
                    return await normal(scope, receive, send)
            return Boundary()
    return Requests()
