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

def multipart_edit(payload, raw):
    checked_reference(raw)
    boundary = "newsflow-" + uuid4().hex
    fields = []
    for key, value in payload.items():
        fields.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                       + str(value) + '\r\n').encode('utf-8'))
    fields.append((f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="reference.png"'
                   '\r\nContent-Type: image/png\r\n\r\n').encode('ascii'))
    fields.extend([raw, f'\r\n--{boundary}--\r\n'.encode('ascii')])
    return b''.join(fields), 'multipart/form-data; boundary=' + boundary
