"""Local-only composition attempts. Never replay provider requests or discard clips."""
from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from .compose import digest
from .schema import CharacterError


def owned(root: Path, path: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise CharacterError('media')
    for part in (root, *reversed(path.parents), path):
        if part == root or part.is_relative_to(root):
            if part.is_symlink() or part.is_junction():
                raise CharacterError('media')
    return path


def downloaded_clips(folder, job):
    rows = job.get('scenes', [])
    if not rows:
        raise CharacterError('media')
    clips, positions = [], set()
    for scene in rows:
        position = scene.get('position')
        filename = scene.get('file')
        if (type(position) is not int or position <= 0 or position in positions
                or scene.get('state') != 'downloaded' or not isinstance(filename, str)
                or not re.fullmatch(rf'scene-{position}(?:-t[0-9]+)?\.mp4', filename)):
            raise CharacterError('media')
        clip = owned(folder, folder / filename)
        if not clip.is_file() or digest(clip) != scene.get('sha256'):
            raise CharacterError('media')
        clips.append(clip)
        positions.add(position)
    return clips


def new_attempt(folder):
    attempts = owned(folder, folder / 'compose-runs')
    attempts.mkdir(exist_ok=True)
    target = owned(folder, attempts / uuid4().hex[:12])
    target.mkdir(exist_ok=False)
    return target


def move_owned(folder, source, destination):
    # Both absolute targets must remain inside this exact job before a directory move.
    owned(folder, source)
    owned(folder, destination)
    if destination.exists():
        raise CharacterError('media')
    if source.is_dir():
        for base, dirs, files in os.walk(source, followlinks=False):
            for name in (*dirs, *files):
                owned(folder, Path(base) / name)
    source.rename(destination)


def publish_attempt(folder, attempt, output):
    candidate = owned(folder, attempt / 'final.mp4')
    if (output.get('file') != 'final.mp4' or not candidate.is_file()
            or digest(candidate) != output.get('sha256')):
        raise CharacterError('media')
    # Preserve all old failed/interrupted artifacts. Each attempt is a separate
    # workspace, so a surviving FFmpeg process cannot write into a later attempt.
    previous = owned(folder, attempt / 'previous')
    previous.mkdir(exist_ok=False)
    for name in ('compose', 'final.mp4', 'review.json'):
        old = folder / name
        owned(folder, old)
        if old.exists():
            move_owned(folder, old, previous / name)
    for name in ('compose', 'review.json', 'final.mp4'):
        source = attempt / name
        if source.exists():
            move_owned(folder, source, folder / name)
    if not (folder / 'review.json').is_file() or digest(folder / 'final.mp4') != output['sha256']:
        raise CharacterError('media')
