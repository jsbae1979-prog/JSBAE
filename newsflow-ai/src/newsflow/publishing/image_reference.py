"""Bounded multipart encoding for the official OpenAI Images edits endpoint."""
from io import BytesIO
from uuid import uuid4
import warnings
from PIL import Image
from .image_generation import ImageGenerationError

def checked_reference(raw):
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 20 * 1024 * 1024:
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=("PNG",)) as image:
                if image.is_animated or not all(128 <= n <= 4096 for n in image.size) or image.width * image.height > 16_000_000:
                    raise ValueError
                image.load()
                if image.info: raise ValueError
    except Exception:
        raise ImageGenerationError("invalid_reference", uncertain=False) from None
    return raw

def reference_capacity(model):
    # Official /images/edits multipart supports arrays. App cap is deliberately 4.
    # https://developers.openai.com/api/reference/resources/images/methods/edit
    from newsflow.creation.catalog import IMAGE_MODELS
    return 4 if model in IMAGE_MODELS else 0

def checked_references(raw, model):
    rows = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    if not 1 <= len(rows) <= reference_capacity(model):
        raise ImageGenerationError('invalid_reference_count', uncertain=False)
    if sum(len(x) for x in rows if isinstance(x,bytes)) > 40*1024*1024:
        raise ImageGenerationError('invalid_reference', uncertain=False)
    return [checked_reference(x) for x in rows]

def multipart_edit(payload, raw):
    # Single-reference call shape remains compatible.
    rows = checked_references(raw, payload['model'])
    boundary = "newsflow-" + uuid4().hex
    fields = []
    for key, value in payload.items():
        fields.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                       + str(value) + '\r\n').encode('utf-8'))
    for index, image in enumerate(rows):
        name='reference.png' if len(rows)==1 else f'reference-{index+1}.png'
        fields.append((f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="{name}"'
                       '\r\nContent-Type: image/png\r\n\r\n').encode('ascii'))
        fields.extend([image,b'\r\n'])
    fields.append(f'--{boundary}--\r\n'.encode('ascii'))
    return b''.join(fields), 'multipart/form-data; boundary=' + boundary
