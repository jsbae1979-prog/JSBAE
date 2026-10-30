"""Per-character topic history; no provider access or modification of old jobs."""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import Field, model_validator

from .registry import PROFILE_ID, atomic_json, safe_path, safe_text
from .schema import Strict, CharacterError

TOPIC_STATES = frozenset({'new','scripted','produced','skipped'})


class Topic(Strict):
    topic: str = Field(min_length=1, max_length=60)
    category: str = Field(default='', max_length=10)
    joke_type: str = Field(default='', max_length=20)

    @model_validator(mode='before')
    @classmethod
    def text_safety(cls, value): return safe_text(value)


def topic_key(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def validate_generated(rows, count, existing=()):
    if type(count) is not int or not 1 <= count <= 50 or not isinstance(rows, list) or len(rows) != count:
        raise CharacterError()
    try:
        result = [Topic.model_validate(row).model_dump() for row in rows]
    except (ValueError, TypeError): raise CharacterError() from None
    keys = [topic_key(row['topic']) for row in result]
    old = {topic_key(row['topic'] if isinstance(row, dict) else row) for row in existing}
    if len(set(keys)) != len(keys) or any(key in old for key in keys): raise CharacterError('blocked')
    # Smaller requested batches cannot contain five different categories.
    if len({row['category'] for row in result}) < min(5, count) or any(not row['category'] or not row['joke_type'] for row in result):
        raise CharacterError()
    if any(sum(row['joke_type'] == key for row in result) > 2 for key in {r['joke_type'] for r in result}):
        raise CharacterError()
    return result


class TopicStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir).absolute() / 'character-topics'

    def _path(self, character_id):
        if not isinstance(character_id, str) or not PROFILE_ID.fullmatch(character_id): raise CharacterError()
        return safe_path(self.root / (character_id + '.json'), self.root)

    def _lock(self, character_id):
        self._path(character_id)
        safe_path(self.root, self.root).mkdir(parents=True, exist_ok=True)
        return FileLock(str(safe_path(self.root / (character_id + '.lock'), self.root)), timeout=5)

    def list(self, character_id):
        path = self._path(character_id)
        if not path.exists(): return []
        try:
            if path.stat().st_size > 4000000: raise ValueError
            document = json.loads(path.read_text(encoding='utf-8'))
            if set(document) != {'version','character_id','topics'} or document['version'] != 1 or document['character_id'] != character_id:
                raise ValueError
            rows = document['topics']
            if not isinstance(rows, list) or len(rows) > 5000: raise ValueError
            seen = set()
            for row in rows:
                if (set(row) != {'id','character_id','topic','category','joke_type','status','revision','created_at'}
                        or row['character_id'] != character_id or not re.fullmatch(r'[a-f0-9]{32}', row['id'])
                        or row['id'] in seen or row['status'] not in TOPIC_STATES
                        or type(row['revision']) is not int or row['revision'] < 1): raise ValueError
                seen.add(row['id'])
                Topic.model_validate({key:row[key] for key in ('topic','category','joke_type')})
            return rows
        except (OSError, ValueError, TypeError, KeyError): raise CharacterError() from None

    def _save(self, character_id, rows):
        if len(rows) > 5000: raise CharacterError()
        atomic_json(self._path(character_id), {'version':1,'character_id':character_id,'topics':rows}, self.root)

    @staticmethod
    def _record(character_id, topic):
        return {'id':uuid4().hex,'character_id':character_id,**topic,'status':'new','revision':1,
                'created_at':datetime.now(UTC).isoformat()}

    def add(self, character_id, topic, category='', joke_type=''):
        try:
            entry = Topic(topic=topic, category=category, joke_type=joke_type).model_dump()
            with self._lock(character_id):
                rows = self.list(character_id)
                same = next((r for r in rows if topic_key(r['topic']) == topic_key(entry['topic'])), None)
                if same: return same
                row = self._record(character_id, entry)
                self._save(character_id, [*rows, row])
                return row
        except Timeout: raise CharacterError('busy') from None
        except CharacterError: raise
        except (ValueError, TypeError): raise CharacterError() from None

    def save_generated(self, character_id, rows, count):
        try:
            with self._lock(character_id):
                previous = self.list(character_id)
                validated = validate_generated(rows, count, previous)
                added = [self._record(character_id, row) for row in validated]
                self._save(character_id, [*previous, *added])
                return added
        except Timeout: raise CharacterError('busy') from None

    def update_status(self, character_id, identifier, status, expected_revision=None):
        if status not in TOPIC_STATES: raise CharacterError()
        try:
            with self._lock(character_id):
                rows = self.list(character_id)
                row = next((r for r in rows if r['id'] == identifier), None)
                if row is None or (expected_revision is not None and expected_revision != row['revision']):
                    raise CharacterError('blocked')
                if row['status'] != status:
                    row.update(status=status, revision=row['revision'] + 1)
                    self._save(character_id, rows)
                return row
        except Timeout: raise CharacterError('busy') from None

    def import_csv(self, character_id, text):
        if not isinstance(text, str) or len(text.encode('utf-8')) > 200000: raise CharacterError()
        parsed = []
        try:
            reader = csv.DictReader(StringIO(text.lstrip('\ufeff'), newline=''))
            names = reader.fieldnames or []
            key = 'topic' if 'topic' in names else '주제' if '주제' in names else None
            category = 'category' if 'category' in names else '카테고리'
            if key is None: raise CharacterError()
            for row in reader:
                if len(parsed) >= 500: raise CharacterError()
                parsed.append(Topic(topic=row[key],category=row.get(category,'') or '',joke_type=row.get('joke_type','') or '').model_dump())
            with self._lock(character_id):
                rows = self.list(character_id)
                seen = {topic_key(row['topic']) for row in rows}
                added, skipped = [], 0
                for row in parsed:
                    identity = topic_key(row['topic'])
                    if identity in seen: skipped += 1; continue
                    seen.add(identity)
                    added.append(self._record(character_id,row))
                if added: self._save(character_id,[*rows,*added])
                return {'created':added,'skipped':skipped}
        except Timeout: raise CharacterError('busy') from None
        except CharacterError: raise
        except (ValueError, TypeError, KeyError, csv.Error): raise CharacterError() from None
