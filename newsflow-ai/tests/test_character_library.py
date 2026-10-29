"""Explicit local character saves using synthetic pixels, never user media/providers."""
import ast
import hashlib
import hmac
import re
import secrets
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from newsflow.creation.image_studio import ImageStudio
from newsflow.publishing.service import PublishingError


def png(note='one', color='teal'):
    out = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('description', note)
    Image.new('RGB', (128, 128), color).save(out, 'PNG', pnginfo=metadata)
    return out.getvalue()


def studio(profile):
    # Saving is independent of any DB/job service or external adapter.
    return ImageStudio(None, profile, None)


def test_library_save_reopen_normalized_dedup_keeps_first_name_and_bytes(tmp_path):
    service = studio(tmp_path/'first')
    original = tmp_path/'original.png'
    original.write_bytes(png())
    first = service.save_character(original.read_bytes(), r'C:\private\캐릭터.png')
    assert first['created'] is True and first['label'] == '캐릭터.png'
    assert first['url'] == '/image-studio/assets/' + first['id']
    before = {p.relative_to(service.images.root): p.read_bytes()
              for p in service.images.root.rglob('*') if p.is_file()}
    second = studio(service.images.root).save_character(png('changed metadata'), 'different.png')
    assert second == {**first, 'created': False}
    assert before == {p.relative_to(service.images.root): p.read_bytes()
                      for p in service.images.root.rglob('*') if p.is_file()}
    assert original.read_bytes() == png()
    assert studio(service.images.root).characters() == [{k: v for k,v in first.items() if k != 'created'}]
    assert len(list(service.images.assets.glob('*.png'))) == 1
    assert not list(service.images.root.rglob('.character-*'))
    assert not (service.images.root/'character').exists()


def test_library_is_separate_from_other_profiles_and_existing_assets(tmp_path):
    first, second = studio(tmp_path/'a'), studio(tmp_path/'b')
    first.asset_bytes(png())  # Existing work references are not implicit library entries.
    assert first.characters() == [] and second.characters() == []
    first.save_character(png(), 'first')
    assert second.characters() == [] and second.assets() == []
    second.save_character(png(color='coral'), 'second')
    assert [row['label'] for row in first.characters()] == ['first']
    assert [row['label'] for row in second.characters()] == ['second']


@pytest.mark.parametrize('raw', [b'', b'not an image', b'x'*(10*1024*1024+1)], ids=['empty','invalid','oversize'])
def test_bad_library_images_do_not_create_entries(tmp_path, raw):
    service = studio(tmp_path)
    with pytest.raises(PublishingError):
        service.save_character(raw, 'bad')
    assert service.characters() == [] and service.assets() == []


def test_failed_atomic_write_keeps_existing_data_and_no_false_library_entry(tmp_path, monkeypatch):
    service = studio(tmp_path)
    first = service.save_character(png(), 'preserve')
    before = service.asset(first['id']).read_bytes()
    original = service._atomic_create
    def fail_metadata(path, content):
        if path.suffix == '.json':
            raise OSError('synthetic storage failure')
        return original(path, content)
    monkeypatch.setattr(service, '_atomic_create', fail_metadata)
    with pytest.raises(OSError):
        service.save_character(png(color='coral'), 'not saved')
    assert service.characters() == [{k: v for k,v in first.items() if k != 'created'}]
    assert service.asset(first['id']).read_bytes() == before
    assert not list(tmp_path.rglob('.character-*'))


def test_conflicting_metadata_is_never_overwritten(tmp_path):
    service = studio(tmp_path)
    first = service.save_character(png(), 'first')
    record = tmp_path/'my-characters'/(first['id'][7:-4]+'.json')
    record.write_text('{invalid existing user data', encoding='utf-8')
    with pytest.raises(ValueError):
        service.save_character(png(), 'replacement')
    assert record.read_text(encoding='utf-8') == '{invalid existing user data'
    assert service.characters() == []


def test_library_exact_local_route_preserves_auth_origin_csrf_and_opt_in(tmp_path, monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.testclient import TestClient
    from bat_distribution.operation import OperatingRequests
    from newsflow.distribution.local_access import LaunchSession, LocalAccess
    from newsflow.gui.character_routes import router
    app = FastAPI()
    app.state.image_studio = studio(tmp_path/'profile')
    app.include_router(router)
    path = Path(__file__).resolve().parents[1]/'src/newsflow/main.py'
    nodes = [n for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {'valid','security'}]
    namespace = dict(app=app, secret=b'synthetic-library-csrf', hashlib=hashlib, hmac=hmac,
                     re=re, secrets=secrets, Request=Request, HTMLResponse=HTMLResponse,
                     StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    session = LaunchSession(18771)
    client = TestClient(OperatingRequests(LocalAccess(app, session)), base_url=session.origin,
                        client=('127.0.0.1',11001))
    endpoint = '/api/studio/characters/library'
    data = {'save_to_library':'true', 'csrf_token':'bad'}
    files = {'reference':('synthetic.png',png(),'image/png')}
    headers = {'Origin':session.origin}
    assert client.post(endpoint, data=data, files=files, headers=headers).status_code == 403
    token = session.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={**headers,'X-NewsFlow-Bootstrap':token}).status_code == 204
    assert client.get('/api/studio/video-models').status_code == 200
    assert client.post(endpoint, data=data, files=files, headers=headers).status_code == 403
    data['csrf_token'] = client.cookies.get('newsflow_csrf')
    assert client.post(endpoint,data=data,files=files,headers={'Origin':'https://outside.invalid'}).status_code == 403
    assert client.post(endpoint,data={**data,'save_to_library':'false'},files=files,headers=headers).status_code == 422
    assert not app.state.image_studio.images.root.exists()
    assert client.post(endpoint,data=data,files={'reference':('bad.gif',b'bad','image/gif')},headers=headers).status_code == 422
    assert client.post(endpoint,data=data,files={'reference':('bad.png',b'bad','image/png')},headers=headers).status_code == 422
    saved = client.post(endpoint,data=data,files=files,headers=headers)
    assert saved.status_code == 200 and saved.json()['created'] is True
    assert client.post(endpoint,data=data,files=files,headers=headers).json()['created'] is False
    assert client.get(saved.json()['url']).status_code == 404  # File router is intentionally absent in this unit harness.
    assert client.get(endpoint).status_code == 403
    assert client.post(endpoint+'/',data=data,files=files,headers=headers).status_code == 403
    assert client.post('/api/studio/characters/auto-story',data=data,headers=headers).status_code == 403
    original = app.state.image_studio.save_character
    def fail(*args, **kwargs):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(app.state.image_studio, 'save_character', fail)
    response = client.post(endpoint,data=data,files=files,headers=headers)
    assert response.status_code == 409 and 'synthetic disk failure' not in response.text
    monkeypatch.setattr(app.state.image_studio, 'save_character', original)
    assert len(app.state.image_studio.characters()) == 1


def test_ui_default_off_and_only_explicit_local_save():
    source = (Path(__file__).resolve().parents[1]/'frontend/src/studio/core/CharacterStudio.tsx').read_text(encoding='utf-8')
    assert 'const [saveToLibrary, setSaveToLibrary] = useState(false)' in source
    assert 'if (saveToLibrary) void saveReference(f)' in source
    assert 'if (checked && file) void saveReference(file)' in source
    assert 'catalog.myCharacters' in source
    assert '내 캐릭터에 저장' in source
