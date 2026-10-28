"""Verify wheel bytes/RECORD/metadata and spread files without executing code."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import stat
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.tags import compatible_tags, cpython_tags, parse_tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from newsflow.distribution.offline import relative

from .lifecycle import Blocked, ordinary_absolute

MAX_EXPANDED = 512 * 1024 * 1024


def compatible():
    return set(cpython_tags((3, 14), ['cp314'], ['win_amd64'])) | set(
        compatible_tags((3, 14), interpreter='cp314', platforms=['win_amd64']))


def archive_name(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise Blocked('wheel-path')
    try:
        relative(value)
    except ValueError:
        raise Blocked('wheel-path') from None
    return value


def read_wheel(path: Path, expected: dict):
    """Return immutable member bytes and declared requirements; never import."""
    path = ordinary_absolute(path)
    data = path.read_bytes()
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise Blocked('wheel-outer-hash')
    name, release, _, tags = parse_wheel_filename(path.name)
    if (canonicalize_name(name) != expected['name'] or release != Version(expected['version'])
            or not tags & compatible()):
        raise Blocked('wheel-name-version-or-platform')
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        if len(wheel.infolist()) > 20000:
            raise Blocked('wheel-member-limit')
        total, folded = 0, set()
        for entry in wheel.infolist():
            if entry.orig_filename != entry.filename or entry.flag_bits & 1:
                raise Blocked('wheel-entry-type')
            item = archive_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
            mode = (entry.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.external_attr & 0x400:
                raise Blocked('wheel-link-or-reparse')
            if entry.is_dir():
                continue
            if item.casefold() in folded:
                raise Blocked('wheel-duplicate-path')
            folded.add(item.casefold())
            total += entry.file_size
            if total > MAX_EXPANDED:
                raise Blocked('wheel-expanded-limit')
            files[item] = wheel.read(entry)
    records = [name for name in files if name.endswith('.dist-info/RECORD')]
    if len(records) != 1:
        raise Blocked('wheel-record-missing')
    record_name = records[0]
    info = record_name.rsplit('/', 1)[0]
    metadata = BytesParser().parsebytes(files[info + '/METADATA'])
    wheel_metadata = BytesParser().parsebytes(files[info + '/WHEEL'])
    if (canonicalize_name(metadata['Name']) != expected['name']
            or Version(metadata['Version']) != Version(expected['version'])
            or wheel_metadata['Wheel-Version'] != '1.0'):
        raise Blocked('wheel-metadata-identity')
    declared_tags = set()
    for value in wheel_metadata.get_all('Tag', []):
        declared_tags.update(parse_tag(value))
    if declared_tags != tags:
        raise Blocked('wheel-declared-tag-mismatch')
    requires_python = metadata.get('Requires-Python')
    if requires_python and not SpecifierSet(requires_python).contains('3.14.7'):
        raise Blocked('wheel-python-requirement')
    declared, checked = set(), 0
    for row in csv.reader(io.StringIO(files[record_name].decode('utf8'))):
        if len(row) != 3:
            raise Blocked('wheel-record-row')
        member, digest, size = row
        archive_name(member)
        if member in declared or member not in files:
            raise Blocked('wheel-record-duplicate-or-missing')
        declared.add(member)
        if member == record_name or member in {record_name + '.jws', record_name + '.p7s'}:
            if digest or size:
                raise Blocked('wheel-self-record')
            continue
        if not digest or not size.isdecimal() or len(files[member]) != int(size):
            raise Blocked('wheel-record-size')
        algorithm, encoded = digest.split('=', 1)
        if algorithm not in {'sha256', 'sha384', 'sha512'}:
            raise Blocked('wheel-record-algorithm')
        actual = base64.urlsafe_b64encode(hashlib.new(algorithm, files[member]).digest()).rstrip(b'=').decode()
        if actual != encoded:
            raise Blocked('wheel-record-hash')
        checked += 1
    unsigned_record_files = set(files) - declared
    if unsigned_record_files - {record_name + '.jws', record_name + '.p7s'}:
        raise Blocked('wheel-unrecorded-member')
    return {'files': files, 'distInfo': info, 'record': record_name, 'recordHashesChecked': checked,
            'requires': metadata.get_all('Requires-Dist', []), 'tags': wheel_metadata.get_all('Tag', []),
            'version': metadata['Version'], 'name': expected['name']}


def spread_target(member: str) -> str:
    archive_name(member)
    parts = member.split('/')
    if parts[0].endswith('.data'):
        if len(parts) < 3:
            raise Blocked('wheel-data-scheme')
        if parts[1] in {'purelib', 'platlib'}:
            return 'app/site-packages/' + '/'.join(parts[2:])
        if parts[1] == 'scripts':
            return 'app/runtime/Scripts/' + '/'.join(parts[2:])
        raise Blocked('wheel-unsupported-data-scheme')
    return 'app/site-packages/' + member


def write_member(root: Path, name: str, data: bytes):
    root = ordinary_absolute(root)
    target = ordinary_absolute(root / archive_name(name))
    if not target.is_relative_to(root) or target == root:
        raise Blocked('bundle-path-escape')
    target.parent.mkdir(parents=True, exist_ok=True)
    ordinary_absolute(target.parent)
    if target.exists():
        if not target.is_file() or target.read_bytes() != data:
            raise Blocked('bundle-member-collision')
    else:
        with target.open('xb') as stream:
            stream.write(data)
    return target


def spread_wheel(root: Path, verified: dict, *, omit_optional_examples=False):
    """PEP427 spread; retain original wheel elsewhere and rewrite installed RECORD.

    Do not run .pth/postinstall, create launchers, call pip or compile bytecode.
    Script shebangs remain inactive originals; this package uses no wheel CLI.
    """
    root = ordinary_absolute(root)
    installed, rows, excluded = [], [], []
    site = root / 'app/site-packages'
    for name, data in verified['files'].items():
        if name == verified['record']:
            continue
        if omit_optional_examples and name.startswith('isapi/samples/'):
            excluded.append(name)
            continue
        target = write_member(root, spread_target(name), data)
        record_relative = Path(os.path.relpath(target, site)).as_posix()
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        rows.append([record_relative, 'sha256=' + digest, str(len(data))])
        installed.append(target.relative_to(root).as_posix())
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerows(sorted(rows))
    writer.writerow([verified['record'], '', ''])
    write_member(root, 'app/site-packages/' + verified['record'], output.getvalue().encode('utf8'))
    return {'distribution': verified['name'], 'files': len(installed) + 1,
            'postinstallExecuted': False, 'pthExecuted': False, 'bytecodeCompiled': False,
            'scriptsRewrittenOrExecuted': False, 'excludedISAPIDeveloperExamples': excluded}


def read_plan(path):
    return json.loads(Path(path).read_text(encoding='utf8'))
