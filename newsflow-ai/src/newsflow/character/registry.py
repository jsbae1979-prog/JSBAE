"""User-owned character profiles, separate from immutable episode snapshots."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Literal
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import Field, field_validator, model_validator
from newsflow.publishing.service import PublishingError

from .schema import Strict, CharacterError

PROFILE_ID = re.compile(r'char_[a-f0-9]{32}')
ASSET_ID = re.compile(r'studio-[a-f0-9]{64}\.png')


def safe_text(value):
    if isinstance(value, str) and (any(ord(c) < 32 or ord(c) == 127 for c in value)
            or re.search(r'(?:sk-ant-|sk-proj-|Bearer\s|HF_KEY\s*=)', value)):
        raise ValueError('Unsafe character text')
    if isinstance(value, dict):
        for item in value.values(): safe_text(item)
    elif isinstance(value, list):
        for item in value: safe_text(item)
    return value


class ComedyFormula(Strict):
    world: str = Field(min_length=1, max_length=60)
    setup: str = Field(min_length=1, max_length=60)
    reaction: str = Field(min_length=1, max_length=60)


class ProfileComedyFormula(ComedyFormula):
    # An omitted setting is not a claimed character fact. Authoring derives it
    # from the user's setup, while image-analysis response validation stays strict.
    world: str = Field(default='', max_length=60)

    @field_validator('world', mode='before')
    @classmethod
    def blank_world(cls, value):
        return '' if isinstance(value, str) and not value.strip() else value

    @field_validator('setup', 'reaction')
    @classmethod
    def required_description(cls, value):
        if not value.strip(): raise ValueError('Required character description')
        return value


def channel_style_default():
    from newsflow.video_models.catalog import character_config
    return character_config()['style_lock']


class SupportingCast(Strict):
    id: str = Field(pattern=r'^[a-z_]{1,40}$')
    appearance: str = Field(min_length=1, max_length=600)


class CharacterProfile(Strict):
    name_ko: str = Field(min_length=1, max_length=60)
    species: str = Field(default='', max_length=40)
    appearance: str = Field(min_length=1, max_length=400)
    personality: str = Field(min_length=1, max_length=800)
    comedy_formula: ProfileComedyFormula
    style_lock: str = Field(default_factory=channel_style_default, min_length=1, max_length=600, validate_default=True)
    supporting_cast: list[SupportingCast] = Field(default_factory=list, max_length=3)
    audience: str = Field(default='general', min_length=1, max_length=80)
    made_for_kids: Literal[False] = False

    @model_validator(mode='before')
    @classmethod
    def text_safety(cls, value):
        return safe_text(value)

    @field_validator('species', 'style_lock', 'audience', mode='before')
    @classmethod
    def optional_defaults(cls, value, info):
        if isinstance(value, str) and not value.strip():
            return channel_style_default() if info.field_name == 'style_lock' else 'general' if info.field_name == 'audience' else ''
        return value

    @field_validator('name_ko', 'appearance', 'personality')
    @classmethod
    def required_description(cls, value):
        if not value.strip(): raise ValueError('Required character description')
        return value

    @field_validator('appearance', 'style_lock')
    @classmethod
    def english_direction(cls, value):
        if not re.search(r'[A-Za-z]', value) or re.search(r'[가-힣]', value):
            raise ValueError('English visual description required')
        return value

    @model_validator(mode='after')
    def unique_cast(self):
        if len({c.id for c in self.supporting_cast}) != len(self.supporting_cast):
            raise ValueError('Duplicate supporting role')
        return self


def safe_path(path: Path, root: Path):
    if not path.is_relative_to(root): raise CharacterError()
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction(): raise CharacterError()
    if not path.resolve().is_relative_to(root.resolve()): raise CharacterError()
    return path


def atomic_json(path: Path, value, root: Path):
    safe_path(path, root)
    temporary = safe_path(path.with_name('.pending-' + uuid4().hex + '.json'), root)
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        safe_path(path, root)
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()


class CharacterRegistry:
    def __init__(self, data_dir, image_studio):
        self.root = Path(data_dir).absolute() / 'character-profiles'
        self.images = image_studio

    def _path(self, identifier):
        if not isinstance(identifier, str) or not PROFILE_ID.fullmatch(identifier):
            raise CharacterError()
        return safe_path(self.root / (identifier + '.json'), self.root)

    def _lock(self):
        safe_path(self.root, self.root).mkdir(parents=True, exist_ok=True)
        return FileLock(str(safe_path(self.root / '.profiles.lock', self.root)), timeout=5)

    def get(self, identifier):
        path = self._path(identifier)
        try:
            if path.stat().st_size > 32000: raise ValueError
            record = json.loads(path.read_text(encoding='utf-8'))
            if (record.get('schema_version') != 1 or record.get('id') != identifier
                    or type(record.get('revision')) is not int or record['revision'] < 1
                    or set(record) != {'schema_version','id','revision','asset','profile','created_at','updated_at'}):
                raise ValueError
            profile = CharacterProfile.model_validate(record['profile'])
            asset = record['asset']
            if not isinstance(asset, str) or not ASSET_ID.fullmatch(asset): raise ValueError
            image = self.images.asset(asset)
            sha = hashlib.sha256(image.read_bytes()).hexdigest()
            if sha != asset[7:-4]: raise ValueError
            return {**{k:v for k,v in record.items() if k != 'profile'}, **profile.model_dump(),
                    'url': '/image-studio/assets/' + asset,
                    'reference_image': {'asset':asset, 'sha256':sha}}
        except (OSError, ValueError, TypeError, KeyError, PublishingError):
            raise CharacterError('reference') from None

    def list(self):
        safe_path(self.root, self.root)
        if not self.root.exists(): return []
        return [self.get(path.stem) for path in sorted(self.root.glob('char_*.json'))
                if PROFILE_ID.fullmatch(path.stem)]

    def save(self, profile, asset, identifier=None, expected_revision=None):
        try:
            validated = CharacterProfile.model_validate(profile).model_dump()
            if not isinstance(asset, str) or not ASSET_ID.fullmatch(asset): raise CharacterError('reference')
            self.images.asset(asset)  # Existing image validator owns path, decoding and content-addressed hash.
            with self._lock():
                stamp = datetime.now(UTC).isoformat()
                if identifier is None:
                    if expected_revision not in (None, 0): raise CharacterError('blocked')
                    identifier, revision, created = 'char_' + uuid4().hex, 1, stamp
                else:
                    old = self.get(identifier)
                    if type(expected_revision) is not int or expected_revision != old['revision']:
                        raise CharacterError('blocked')
                    revision, created = old['revision'] + 1, old['created_at']
                record = {'schema_version':1,'id':identifier,'revision':revision,'asset':asset,
                          'profile':validated,'created_at':created,'updated_at':stamp}
                atomic_json(self._path(identifier), record, self.root)
                return self.get(identifier)
        except Timeout:
            raise CharacterError('busy') from None
        except CharacterError:
            raise
        except (ValueError, TypeError, PublishingError):
            raise CharacterError() from None

    def snapshot(self, identifier):
        return deepcopy(self.get(identifier))

    def delete(self, identifier, revision):
        try:
            with self._lock():
                old = self.get(identifier)
                if type(revision) is not int or revision != old['revision']: raise CharacterError('blocked')
                self._path(identifier).unlink()  # Only the selected profile; assets and old jobs stay untouched.
        except Timeout:
            raise CharacterError('busy') from None
