"""Offline, read-only starter catalog; only explicit user actions create copies."""
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from newsflow.db.models import AppSetting

ROOT = Path(__file__).resolve().parents[1] / 'assets' / 'samples'
PREFIX = 'sample_content:v1:'


class SampleError(ValueError):
    pass


def safe_path(base, relative):
    base = Path(base)
    rel = Path(relative)
    if rel.is_absolute() or any(p in {'..', '.'} or ':' in p for p in rel.parts):
        raise SampleError('샘플 경로를 확인하세요.')
    path = base / rel
    if not path.resolve().is_relative_to(base.resolve()):
        raise SampleError('샘플 경로를 확인하세요.')
    for current in [path, *path.parents]:
        if current.is_symlink() or current.is_junction():
            raise SampleError('연결된 샘플 경로는 사용할 수 없습니다.')
        if current == base:
            break
    return path


class Samples:
    def __init__(self, sessions, data_dir, image_studio, root=ROOT):
        self.sessions = sessions
        self.data_dir = Path(data_dir)
        self.root = Path(root)
        self.image_studio = image_studio

    def catalog(self):
        """Missing/corrupt package assets never prevent app startup or user work."""
        try:
            path = safe_path(self.root, 'manifest.json')
            if path.stat().st_size > 100_000:
                raise SampleError()
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if manifest['version'] != 1 or not isinstance(manifest['assets'], list) or len(manifest['assets']) > 24:
                raise SampleError()
        except (OSError, ValueError, KeyError, TypeError):
            return [], '기본 샘플을 읽지 못했습니다. 내 작업에는 영향이 없습니다.'
        rows, warning = [], ''
        for row in manifest['assets']:
            try:
                if not re.fullmatch(r'[a-z0-9-]{1,48}', row['id']):
                    raise SampleError()
                if row['type'] not in {'standalone', 'news-top3', 'character', 'news-short', 'character-short'}:
                    raise SampleError()
                self.checked(row)
                if row.get('poster'):
                    self.checked(row, poster=True)
                rows.append(row)
            except (OSError, ValueError, KeyError, TypeError):
                warning = '일부 샘플 파일이 없거나 손상되어 제외했습니다. 내 작업은 보존됩니다.'
        return rows, warning

    def checked(self, row, poster=False):
        meta = row['poster'] if poster else row
        path = safe_path(self.root, meta['path'])
        if path.suffix.lower() not in {'.png', '.jpg', '.mp4'} or not path.is_file():
            raise SampleError('샘플 파일을 확인하세요.')
        if path.stat().st_size != meta['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256']:
            raise SampleError('샘플 파일이 변경되었습니다.')
        return path

    def get(self, identifier):
        rows, _ = self.catalog()
        row = next((x for x in rows if x['id'] == identifier), None)
        if row is None:
            raise SampleError('샘플을 찾지 못했습니다.')
        return row

    def states(self):
        with self.sessions() as s:
            return {r.key: r.value for r in s.scalars(select(AppSetting).where(AppSetting.key.startswith(PREFIX)))}

    def listing(self):
        rows, warning = self.catalog()
        states = self.states()
        result = []
        for row in rows:
            item = dict(row)
            identifier = row['id']
            item.update(mediaUrl=f'/api/samples/{identifier}/file',
                        posterUrl=f'/api/samples/{identifier}/poster' if row.get('poster') else None,
                        hidden=states.get(PREFIX+'hidden:'+identifier) == 'true',
                        copied=PREFIX+'copy:'+identifier in states)
            if item['copied']:
                item['copyUrl'] = f'/api/samples/{identifier}/copy-file'
            result.append(item)
        return {'schemaVersion': 1, 'sample': True, 'assets': result, 'warning': warning}

    def hide(self, identifier, hidden):
        self.get(identifier)
        with self.sessions.begin() as s:
            stmt = insert(AppSetting).values(key=PREFIX+'hidden:'+identifier, value='true' if hidden else 'false')
            s.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={'value': stmt.excluded.value}))

    def copy_path(self, row):
        relative = 'sample-copies/v1/' + row['id'] + '/' + row['sha256'] + Path(row['path']).suffix
        return safe_path(self.data_dir, relative)

    def copied_file(self, identifier):
        row = self.get(identifier)
        if PREFIX+'copy:'+identifier not in self.states():
            raise SampleError('먼저 내 작업으로 복사하세요.')
        path = self.copy_path(row)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise SampleError('복사한 참조 파일을 확인하세요.')
        return row, path

    def copy(self, identifier, use=False):
        row = self.get(identifier)
        source = self.checked(row)
        dest = self.copy_path(row)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest = self.copy_path(row)
        try:
            with dest.open('xb') as f:
                f.write(source.read_bytes())
        except FileExistsError:
            pass
        if hashlib.sha256(dest.read_bytes()).hexdigest() != row['sha256']:
            raise SampleError('기존 사용자 복사본을 덮어쓰지 않았습니다. 파일을 확인하세요.')
        reference = None
        # The existing image service validates/sanitizes local reference PNGs.
        # A video is a reference asset, never an editable source project.
        if use and row.get('referenceId'):
            ref = self.get(row['referenceId'])
            reference = self.image_studio.asset_bytes(self.checked(ref).read_bytes())
        elif use and row['type'] in {'character', 'standalone', 'news-top3'}:
            reference = self.image_studio.asset_bytes(source.read_bytes())
        with self.sessions.begin() as s:
            stmt = insert(AppSetting).values(key=PREFIX+'copy:'+identifier,
                value=json.dumps({'id': identifier, 'sha256': row['sha256'], 'sample': True, 'version': 1}))
            s.execute(stmt.on_conflict_do_nothing(index_elements=['key']))
        return {'sample': True, 'id': identifier, 'mediaUrl': f'/api/samples/{identifier}/copy-file',
                'referenceAsset': reference, 'promptExample': row.get('promptExample', ''),
                'target': row['target'], 'editableProject': False,
                'message': '샘플 참조 파일을 내 경로에 보관했습니다. 실제 생성 이력·편집 원본 프로젝트가 아닙니다.'}
