"""Local image drafts and existing one-shot image adapter; no startup generation."""
import hashlib
import re
import warnings
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from newsflow.db.models import IntelligenceRun
from newsflow.publishing.service import PublishingError
from newsflow.video.engine import RenderError
from newsflow.video.news_images import NewsImages

from .catalog import check_snapshot, snapshot


class ImageStudio:
    def __init__(self, sessions, data_dir, generation):
        self.sessions, self.generation = sessions, generation
        self.images = NewsImages(data_dir)

    def asset_bytes(self, raw):
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise PublishingError('이미지는 10MB 이하로 준비하세요.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw), formats=('PNG', 'JPEG', 'WEBP')) as image:
                    if getattr(image, 'is_animated', False) or not all(128 <= n <= 4096 for n in image.size) or image.width * image.height > 16_000_000:
                        raise ValueError
                    image.load()
                    clean = Image.new('RGB', image.size, 'white')
                    pixels = image.convert('RGBA')
                    clean.paste(pixels, mask=pixels.getchannel('A'))
                    out = BytesIO()
                    clean.save(out, 'PNG')
                    content = out.getvalue()
                    if len(content) > 20 * 1024 * 1024:
                        raise ValueError
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise PublishingError('지원하는 정적 PNG·JPEG·WebP 이미지를 선택하세요.') from None
        digest = hashlib.sha256(content).hexdigest()
        name = 'studio-' + digest + '.png'
        path = self.images.safe(self.images.assets / name, self.images.assets)
        self.images.safe(self.images.assets, self.images.assets).mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise PublishingError('이미지 무결성을 확인하세요.')
        else:
            with path.open('xb') as handle:
                handle.write(content)
        return name

    def asset(self, name):
        if not re.fullmatch(r'studio-[a-f0-9]{64}\.png', name):
            raise PublishingError('저장한 제작 이미지를 선택하세요.')
        try:
            path = self.images.asset(name)
        except RenderError:
            raise PublishingError('저장 이미지를 안전하게 읽지 못했습니다.') from None
        if hashlib.sha256(path.read_bytes()).hexdigest() != name[7:-4]:
            raise PublishingError('저장 이미지가 변경되었습니다.')
        return path

    def assets(self):
        if not self.images.assets.exists():
            return []
        self.images.safe(self.images.assets, self.images.assets)
        result = []
        for path in sorted(self.images.assets.glob('studio-*.png'))[:200]:
            try:
                self.asset(path.name)
                result.append(path.name)
            except (ValueError, OSError, PublishingError):
                continue
        return result

    def create(self, prompt, selection, *, reference=b''):
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 4000 or any(ord(c) < 32 and c not in '\n\r\t' for c in prompt):
            raise PublishingError('이미지 지시문은 1~4,000자로 입력하세요.')
        if re.search(r'\bsk-[A-Za-z0-9_-]{16,}', prompt):
            raise PublishingError('비밀정보를 지시문에 입력하지 마세요.')
        frozen = snapshot('image', selection)
        reference_name = self.asset_bytes(reference) if reference else None
        with self.sessions.begin() as session:
            row = IntelligenceRun(kind='image_draft', status='saved', provider='openai',
                options={'selection': frozen, 'reference': reference_name}, evidence={},
                result={'prompt': prompt}, message='로컬 초안 저장 · 생성 승인 전')
            session.add(row)
            session.flush()
            return row.id

    def get(self, identifier):
        with self.sessions() as session:
            row = session.get(IntelligenceRun, identifier)
            if not row or row.kind != 'image_draft':
                raise PublishingError('이미지 초안을 찾을 수 없습니다.')
            check_snapshot(row.options['selection'], 'image')
            return row

    def recent(self):
        with self.sessions() as session:
            return list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind == 'image_draft')
                        .order_by(IntelligenceRun.id.desc()).limit(30)))

    def execute(self, identifier, *, consent=False, reviewed=False):
        if consent is not True or reviewed is not True:
            raise PublishingError('지시문을 검토하고 외부 전송·유료 이미지 1회 생성에 동의하세요.')
        row = self.get(identifier)
        if row.options.get('reference'):
            raise PublishingError('참조 이미지는 로컬 저장·재사용만 지원합니다. 참조 기반 생성 Adapter는 미구현입니다.')
        selection = row.options['selection']
        return self.generation._generate(None, None, None, 'studio',
            {'image_studio_draft': identifier}, row.result['prompt'], draft_id=identifier, execution=selection)

    def output(self, identifier):
        self.get(identifier)
        with self.sessions() as session:
            rows = list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind == 'feed_image')
                                        .order_by(IntelligenceRun.id.desc())))
            return next((r for r in rows if r.options.get('style') == 'studio' and r.options.get('draft_id') == identifier), None)

    def export(self, identifier, *, reviewed=False):
        if reviewed is not True:
            raise PublishingError('이미지 내용·사용권·AI 표시를 검토하세요.')
        result = self.output(identifier)
        if not result or result.status != 'success':
            raise PublishingError('완료한 이미지가 필요합니다.')
        path = self.generation.path(result.id)
        self.images.safe(path, self.generation.outputs)
        return self.asset_bytes(path.read_bytes())
