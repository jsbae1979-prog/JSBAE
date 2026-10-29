"""Inert private ZIP assembly. No interpreter/app/media/postinstall execution."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from .lifecycle import Blocked, ordinary_absolute
from .wheel_materials import read_wheel, spread_wheel, write_member
from .zip_update import MAX_ZIP, FileRecord, _zip_members, payload_name

RUNTIME_SHA = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'
MEDIA_HASHES = {
    'ffmpeg.exe': '26f21efe3d78e27699baa71c6fe668c28aaffd56db8ce11f361ed71987119dea',
    'ffprobe.exe': 'a9e63afd32450722e6b1ab94dac955edc643c4943322713c4652185f10246e50',
}
CONTROLLER = ('__init__.py', 'contract_entry.py', 'windows_live.py', 'restored_install.py', 'lifecycle.py', 'zip_update.py',
              'publisher_verifier.py', 'verify_manifest_content.ps1')
PTH = ('python314.zip\n.\n../site-packages\n../site-packages/win32\n'
       '../site-packages/win32/lib\n../site-packages/pywin32_system32\n'
       '../product\n../controller\n# No import site; no .pth startup code executed.\n')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def program_records(root):
    root = ordinary_absolute(root)
    rows = []
    for path in sorted(root.rglob('*')):
        ordinary_absolute(path)
        if path.is_file():
            name = payload_name(path.relative_to(root).as_posix())
            rows.append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    if len({r['path'].casefold() for r in rows}) != len(rows):
        raise Blocked('program-casefold-collision')
    return rows


def create_zip(root, target, *, prefix=''):
    """Store immutable program bytes, no directory/symlink/extra fields."""
    root, target = ordinary_absolute(root), ordinary_absolute(target)
    if target.exists() or target.is_relative_to(root):
        raise Blocked('zip-output-must-be-new-and-outside-program')
    if prefix not in ('', 'NewsFlowAI/'):
        raise Blocked('zip-prefix')
    rows = program_records(root)
    if sum(row['bytes'] for row in rows) > MAX_ZIP - 8 * 1024 * 1024:
        raise Blocked('candidate-exceeds-existing-update-limit')
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for row in rows:
            content = (root / row['path']).read_bytes()
            if len(content) != row['bytes'] or hashlib.sha256(content).hexdigest() != row['sha256']:
                raise Blocked('program-changed-during-packaging')
            entry = zipfile.ZipInfo(prefix + row['path'], date_time=(2026, 10, 28, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = (0o100644 << 16)
            archive.writestr(entry, content)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None or len(archive.infolist()) != len(rows):
            raise Blocked('candidate-zip-corruption')
        for entry, row in zip(archive.infolist(), rows, strict=True):
            if entry.filename != prefix + row['path'] or hashlib.sha256(archive.read(entry)).hexdigest() != row['sha256']:
                raise Blocked('candidate-zip-member-mismatch')
    return rows


def copy_tree(root, source, destination, *, excluded_parts=(), allowed_suffixes=None):
    source = ordinary_absolute(source)
    for path in sorted(source.rglob('*')):
        ordinary_absolute(path)
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part.casefold() in excluded_parts for part in relative.parts):
            continue
        if allowed_suffixes is not None and path.suffix.casefold() not in allowed_suffixes:
            continue
        write_member(root, destination + '/' + relative.as_posix(), path.read_bytes())


def _generated(root, name, data):
    # Only these two generated files may change between the two candidate versions.
    if name not in {'app/layout.json', 'README.txt'}:
        raise Blocked('not-generated-release-file')
    root = ordinary_absolute(root)
    target = ordinary_absolute(root / name)
    if not target.is_relative_to(root):
        raise Blocked('generated-file-outside-program')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _set_release(root, version, source_sha):
    readme = f'''NewsFlow AI {version} — 비공개·비실행 패키징 후보

이 ZIP은 일반 사용자 전달용 완성품이 아닙니다. 실제 앱/BAT 실행은 검증하지 않았습니다.
Start/Stop dispatcher는 exit2, Update는 exit3으로 거절합니다. 실행을 활성화하지 마세요.
현재 앱의 보안 정책 문제를 피하기 위한 다른 진입점은 제공하지 않습니다.

제품 코드 SHA: {source_sha}
1.0.0/1.1.0 후보는 같은 제품 코드에 릴리스 메타데이터만 다릅니다.
실제 기능 버전 간 업데이트·실행 성공을 증명하지 않습니다.

사용자 데이터 계약: %LOCALAPPDATA%\\NewsFlowAI-Desktop\\v1
운영 기본 경로 %LOCALAPPDATA%\\NewsFlowAI 및 운영 포트8765를 사용하지 않습니다.
이 후보는 사용자 DB·키·OAuth·설정·미디어·ledger·백업을 포함하지 않습니다.
권리 미확인 샘플12개는 제외했습니다. 샘플 없음 상태의 실제 GUI는 미검증입니다.

런타임·wheel·FFmpeg 파일은 들어 있으나 DLL 초기화/portable import/전체 앱을 실행하지 않았습니다.
배포자 인증서·신뢰 앵커·오프라인 검증이 없어 실제 업데이트는 비활성입니다.
SHA-256은 무결성 자료이며 배포자 진위 증명이 아닙니다. manifest는 서명되지 않았습니다.
실행·정상 종료·업데이트·외부 전달에는 이후 정식 허용 경로와 별도 승인이 필요합니다.
보안 프로그램 해제·예외 등록·ACL 완화·강제 종료를 하지 마세요.

licenses/의 Python·wheel notices와 FFmpeg source/recipe는 보존 자료입니다.
라이선스·대응 소스 완전성·외부 전달 권리의 최종 승인을 의미하지 않습니다.

기본 browser runtime에서는 미사용 PythonWin GUI·MAPI 및 ISAPI 개발 예제를 제외했습니다.
원본 wheel27개는 별도로 보존하며 실제 COM/DLL 초기화 성공은 미검증입니다.
'''
    _generated(root, 'README.txt', readme.replace('\n', '\r\n').encode('utf8'))
    rows = [row for row in program_records(root) if row['path'] != 'app/layout.json']
    layout = {'schemaVersion': 1, 'pythonVersion': '3.14.7', 'architecture': 'AMD64',
              'releaseVersion': version, 'sourceSha': source_sha, 'candidateOnly': True,
              'liveStartStopConnected': False, 'updatesEnabled': False, 'files': rows}
    _generated(root, 'app/layout.json', (json.dumps(layout, ensure_ascii=False, indent=2) + '\n').encode('utf8'))


def assemble(project, output, python_zip, wheels, wheelhouse, media, source_sidecar, tracked_product, source_sha):
    """Fresh path only. Does not reuse current profile or overwrite any old bundle."""
    project, output = ordinary_absolute(project), ordinary_absolute(output)
    if output.exists() or output.is_relative_to(project) or project.is_relative_to(output):
        raise Blocked('fresh-separate-candidate-output-required')
    if digest(python_zip) != RUNTIME_SHA:
        raise Blocked('runtime-origin-hash')
    for name, expected in MEDIA_HASHES.items():
        if digest(media / name) != expected:
            raise Blocked('media-source-binding-mismatch')
    output.mkdir()
    root = output / 'staging/NewsFlowAI'
    root.mkdir(parents=True)
    runtime_rows = []
    with zipfile.ZipFile(python_zip) as runtime:
        if len(runtime.infolist()) != 37 or runtime.testzip() is not None:
            raise Blocked('runtime-member-integrity')
        for entry in runtime.infolist():
            data = runtime.read(entry)
            write_member(root, 'app/runtime/' + entry.filename, data)
            runtime_rows.append({'file': entry.filename, 'sha256': hashlib.sha256(data).hexdigest()})
    # Only startup search-path data is changed. No site/.pth/postinstall is executed.
    (root / 'app/runtime/python314._pth').write_bytes(PTH.replace('\n', '\r\n').encode('ascii'))
    spread = []
    for wheel in wheels:
        checked = read_wheel(wheelhouse / wheel['file'], wheel)
        spread.append(spread_wheel(root, checked, omit_optional_examples=True, omit_unused_windows_extras=True))
    product_excluded = {'__pycache__', 'tests', 'validation', '.git'}
    for relative in tracked_product:
        if any(part.casefold() in product_excluded for part in Path(relative).parts):
            continue
        if relative.startswith('newsflow/assets/samples/') or Path(relative).name == 'publisher-trust.json':
            continue
        name = 'app/product/' + relative
        payload_name(name)
        write_member(root, name, (project / 'src' / relative).read_bytes())
    copy_tree(root, project / 'frontend/dist', 'app/frontend/dist', excluded_parts={'__pycache__'},
              allowed_suffixes={'.html', '.js', '.css', '.woff', '.woff2', '.svg', '.png', '.jpg', '.webp'})
    for name in CONTROLLER:
        write_member(root, 'app/controller/bat_distribution/' + name,
                     (project / 'tools/bat_distribution' / name).read_bytes())
    for path in (project / 'tools/bat_distribution/templates').glob('*.bat'):
        write_member(root, path.name, path.read_bytes())
    for name in MEDIA_HASHES:
        write_member(root, 'tools/' + name, (media / name).read_bytes())
    copy_tree(root, project / 'src/newsflow/assets/distribution/licenses', 'licenses/product-notices')
    write_member(root, 'licenses/CPython-LICENSE.txt', (root / 'app/runtime/LICENSE.txt').read_bytes())
    binding = json.loads((source_sidecar / 'BINARY_SOURCE_BINDING.json').read_bytes())
    for row in binding['sourceArchives']:
        original = ordinary_absolute(source_sidecar / row['file'])
        if digest(original) != row['sha256']:
            raise Blocked('ffmpeg-source-archive-mismatch')
        write_member(root, 'licenses/ffmpeg-corresponding-sources/' + row['file'], original.read_bytes())
    for name in ('BINARY_SOURCE_BINDING.json', 'build-local-media.sh'):
        write_member(root, 'licenses/ffmpeg-corresponding-sources/' + name, (source_sidecar / name).read_bytes())
    for name in ('source-licenses', 'build-evidence'):
        copy_tree(root, source_sidecar / name, 'licenses/ffmpeg-corresponding-sources/' + name,
                  allowed_suffixes={'.txt', '.json', '.h', '.mak', '.md', '.sh'})
    _set_release(root, '1.0.0', source_sha)
    initial = output / 'NewsFlowAI_v1.0.0.zip'
    first_rows = create_zip(root, initial, prefix='NewsFlowAI/')
    _set_release(root, '1.1.0', source_sha)
    update = output / 'NewsFlowAI_Update_v1.1.0.zip'
    update_rows = create_zip(root, update)
    manifest = {'schemaVersion': 1, 'appId': 'NewsFlowAI', 'channel': 'private-bat', 'version': '1.1.0',
                'sequence': 2, 'supportedFrom': ['1.0.0'], 'pythonVersion': '3.14.7', 'architecture': 'AMD64',
                'migration': 'none', 'zipName': update.name, 'zipBytes': update.stat().st_size,
                'zipSha256': digest(update), 'files': update_rows}
    # Existing ZIP content validator is reused without changing signature/trust gates.
    _zip_members(update.read_bytes(), tuple(FileRecord(r['path'], r['bytes'], r['sha256']) for r in update_rows))
    (output / 'NewsFlowAI_Update_v1.1.0.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    result = {'candidateOnly': True, 'sourceSha': source_sha, 'productPayloadSameCode': True,
              'liveStartStopConnected': False, 'updatesEnabled': False, 'publisherSignaturePresent': False,
              'samplesIncluded': 0, 'runtimeSourceFiles': 37, 'runtimePthModifiedAsDataOnly': True,
              'wheels': spread, 'sourcesIncluded': len(binding['sourceArchives']),
              'initial': {'file': initial.name, 'bytes': initial.stat().st_size, 'sha256': digest(initial),
                          'members': len(first_rows), 'prefix': 'NewsFlowAI/'},
              'update': {'file': update.name, 'bytes': update.stat().st_size, 'sha256': digest(update),
                         'members': len(update_rows), 'prefix': ''},
              'runtimeSourceManifest': runtime_rows, 'appExecuted': False, 'BATExecuted': False,
              'postinstallExecuted': False, 'externalDelivery': False}
    (output / 'PACKAGE_RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    return result
