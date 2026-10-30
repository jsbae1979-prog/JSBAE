"""Library-only, reversible visibility; original work and media stay untouched."""
from contextlib import nullcontext
import json
import re

from filelock import Timeout
from sqlalchemy import select

from newsflow.character.schema import CharacterError
from newsflow.db.models import AppSetting, ImagePost, IntelligenceRun, RenderJob, VideoProject, WorkspaceRemoval

PREFIX = 'library:'
IDENTIFIER = re.compile(r'(?:news:[1-9][0-9]{0,18}|image:[1-9][0-9]{0,18}|post:[1-9][0-9]{0,18}|character:[a-f0-9]{32}|reference:[a-z0-9-]{1,48})\Z')
ACTIVE = frozenset({'running', 'queued', 'submitting', 'submitted', 'waiting', 'in_progress', 'downloading',
                    'writing', 'preparing', 'generating', 'retry_quoting', 'composing'})


class LibraryVisibilityError(ValueError):
    """Constant error codes only; never expose internal paths or provider data."""


def parse_items(raw):
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        raise LibraryVisibilityError('invalid') from None
    if (not isinstance(values, list) or not 1 <= len(values) <= 100
            or any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in values)
            or any(value.split(':', 1)[0] in {'news', 'image', 'post'}
                   and int(value.split(':', 1)[1]) > 9223372036854775807 for value in values)
            or len(set(values)) != len(values)):
        raise LibraryVisibilityError('invalid')
    return values


class LibraryVisibility:
    def __init__(self, sessions, character):
        self.sessions, self.character = sessions, character

    def _item(self, session, identifier, *, removing):
        kind, value = identifier.split(':', 1)
        status = ''
        if kind == 'character':
            try:
                job = self.character.read(value)
            except (CharacterError, OSError, ValueError):
                raise LibraryVisibilityError('missing') from None
            if removing and (job['state'] in ACTIVE or any(
                    scene.get('state') in ACTIVE for scene in job.get('scenes', []))):
                raise LibraryVisibilityError('busy')
            title, status = job.get('topic', '캐릭터 쇼츠'), job['state']
        elif kind == 'reference':
            row = session.get(AppSetting, 'sample_content:v1:copy:' + value)
            try:
                record = json.loads(row.value) if row else None
            except (ValueError, TypeError):
                record = None
            if (not isinstance(record, dict) or record.get('id') != value or record.get('version') != 1
                    or not isinstance(record.get('sha256'), str)
                    or not re.fullmatch(r'[a-f0-9]{64}', record['sha256'])):
                raise LibraryVisibilityError('missing')
            title, status = '보관한 참조 파일 · ' + value, 'stored'
        else:
            model = {'news': RenderJob, 'image': IntelligenceRun, 'post': ImagePost}[kind]
            row = session.get(model, int(value))
            if row is None or kind == 'image' and row.kind != 'image_draft':
                raise LibraryVisibilityError('missing')
            if kind == 'news':
                project = session.get(VideoProject, row.project_id)
                if project is None:
                    raise LibraryVisibilityError('missing')
                title, status = project.title, row.status
            elif kind == 'image':
                title, status = row.result.get('prompt', '이미지 초안'), row.status
                outputs = list(session.scalars(select(IntelligenceRun).where(
                    IntelligenceRun.kind == 'feed_image',
                    IntelligenceRun.options['style'].as_string() == 'studio',
                    IntelligenceRun.options['draft_id'].as_integer() == row.id)))
                if removing and any(output.status in ACTIVE for output in outputs):
                    raise LibraryVisibilityError('busy')
            else:
                title, status = row.title, 'success'
        if removing and status in ACTIVE:
            raise LibraryVisibilityError('busy')
        return {'id': identifier, 'title': str(title), 'kind': kind, 'state': 'hidden',
                'originalStatus': status}

    def change(self, items, *, hidden):
        identifiers = parse_items(items)
        # Share the existing engine lock, without waiting for an active operation.
        lock = self.character.lock() if any(x.startswith('character:') for x in identifiers) else nullcontext()
        try:
            with lock, self.sessions.begin() as session:
                session.connection().exec_driver_sql('BEGIN IMMEDIATE')
                details = {identifier: self._item(session, identifier, removing=hidden) for identifier in identifiers}
                # Validate the entire request before changing even the first marker.
                for identifier in identifiers:
                    row = session.get(WorkspaceRemoval, PREFIX + identifier)
                    if hidden and row is None:
                        session.add(WorkspaceRemoval(key=PREFIX + identifier, detail=details[identifier]))
                    elif not hidden and row is not None:
                        session.delete(row)
        except Timeout:
            raise LibraryVisibilityError('busy') from None
        return {('removed' if hidden else 'restored'): identifiers,
                **({'recoverable': True} if hidden else {}), 'historicalRecordsPreserved': True}

    def listing(self):
        with self.sessions() as session:
            rows = session.scalars(select(WorkspaceRemoval).where(WorkspaceRemoval.key.startswith(PREFIX))
                                   .order_by(WorkspaceRemoval.created_at.desc()))
            result = []
            for row in rows:
                identifier = row.key.removeprefix(PREFIX)
                if not IDENTIFIER.fullmatch(identifier):
                    continue
                detail = row.detail if isinstance(row.detail, dict) else {}
                result.append({'id': identifier, 'title': str(detail.get('title', '보관한 콘텐츠')),
                               'kind': identifier.split(':', 1)[0], 'updatedAt': row.created_at.isoformat(),
                               'technicalStatus': 'hidden'})
            return result
