"""Deterministic local 4:5 typesetting. No network, silent clipping or font shrinking."""
from io import BytesIO
from copy import deepcopy
import re
import warnings
from PIL import Image, ImageDraw, ImageFont, ImageOps
from newsflow.video.engine import font_path
from .service import PublishingError

STYLE = 'photo_feed_v1'
DEFAULT = dict(style=STYLE, title='', description='', caption='', hashtags='', brand='NewsFlow AI', date='',
               credit='', source='', emphasis='', accent='#76e4ff', title_size=64, text_y=.64,
               gradient_height=.58, gradient_strength=.85, image_height=1., crop=[0.,0.,1.,1.], caption_sections={}, typography='legacy')
LABELS = {'ai':'AI 생성 이미지 · 실제 현장 사진 아님', 'photo':'실제 사진', 'stock':'자료사진 · 설명용'}

def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT): raise PublishingError('편집 항목을 확인하세요.')
    v={**deepcopy(DEFAULT),**deepcopy(value)}
    from newsflow.creation.feed_growth import caption_parts
    caption_parts(v['caption_sections'])
    limits={'title':140,'description':140,'caption':1800,'hashtags':200,'brand':30,'date':30,'credit':160,'source':200,'emphasis':40}
    for k,n in limits.items():
        if not isinstance(v[k],str) or len(v[k])>n or any(ord(c)<32 and c!='\n' for c in v[k]):
            raise PublishingError(f"{ {'title':'피드 제목','description':'핵심 설명','caption':'캡션','hashtags':'해시태그','brand':'브랜드','date':'날짜','credit':'크레딧','source':'출처','emphasis':'강조 단어'}[k]}: 글자 수({n}자 이내)와 입력 형식을 확인하세요.")
    if v['style']!=STYLE or not isinstance(v['accent'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v['accent']): raise PublishingError('스타일·강조색을 확인하세요.')
    for k,low,high in [('title_size',48,84),('text_y',.35,.78),('gradient_height',.25,.9),('gradient_strength',.3,1),('image_height',.6,1)]:
        if type(v[k]) not in (int,float) or not low<=v[k]<=high: raise PublishingError('배치 범위를 확인하세요.')
    if v['typography'] not in {'legacy','editorial_v1'}: raise PublishingError('글꼴 구성을 확인하세요.')
    c=v['crop']
    if (not isinstance(c,list) or len(c)!=4 or any(type(x) not in (int,float) or not 0<=x<=1 for x in c)
            or c[2]-c[0]<.1 or c[3]-c[1]<.1): raise PublishingError('자르기 영역을 확인하세요.')
    return v

def clean_image(raw):
    if not raw or len(raw)>20*1024*1024: raise PublishingError('20MB 이하의 로컬 이미지를 선택하세요.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw),formats=['PNG','JPEG','WEBP']) as im:
                if im.width*im.height>16_000_000: raise PublishingError('이미지 픽셀 수가 너무 큽니다.')
                image=ImageOps.exif_transpose(im).convert('RGB'); image.load()
        out=BytesIO(); image.save(out,'PNG'); return out.getvalue()
    except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise PublishingError('이미지를 읽을 수 없습니다. PNG·JPG·WEBP 파일을 확인하세요.') from None

def lines(draw,text,font,width,max_lines,label):
    out=[]
    for paragraph in text.split('\n'):
        line=''
        for ch in paragraph:
            if draw.textlength(line+ch,font=font)>width:
                out.append(line.rstrip());line=ch.lstrip()
            else:line+=ch
        out.append(line.rstrip())
    if len(out)>max_lines: raise PublishingError(f'{label}이 {max_lines}줄을 넘습니다. 줄바꿈·문구·글자 크기를 직접 조정하세요. 자동 축소·자르기는 하지 않습니다.')
    return out

def typeface(size, *, bold=False, editorial=False):
    path=font_path()
    candidate=path.with_name('malgunbd.ttf') if bold and path.name.lower()=='malgun.ttf' else path
    font=ImageFont.truetype(str(candidate if candidate.exists() else path),size)
    if editorial:
        try: names=font.get_variation_names()
        except OSError: names=[]  # A static font has no variation table.
        weight=b'Bold' if bold else b'Regular'
        if weight in names: font.set_variation_by_name(weight)
    return font


def render(raw,value,kind):
    v=validate(value)
    if not v['title'].strip(): raise PublishingError('피드 제목을 입력하세요.')
    if not v['credit'].strip(): raise PublishingError('이미지 크레딧을 입력하세요.')
    if kind not in LABELS: raise PublishingError('이미지 구분을 확인하세요.')
    with Image.open(BytesIO(clean_image(raw))) as im:
        c=v['crop'];image=ImageOps.fit(im.crop((int(c[0]*im.width),int(c[1]*im.height),int(c[2]*im.width),int(c[3]*im.height))),
                                     (1080,round(1350*v['image_height'])),method=Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',(1080,1350),'#08111d');canvas.paste(image,(0,0));canvas=canvas.convert('RGBA')
    overlay=Image.new('RGBA',canvas.size);d=ImageDraw.Draw(overlay);start=round(1350*(1-v['gradient_height']))
    for y in range(start,1350):
        a=round(255*v['gradient_strength']*((y-start)/(1350-start))**.7)
        d.line((0,y,1080,y),fill=(0,0,0,a))
    canvas=Image.alpha_composite(canvas,overlay);d=ImageDraw.Draw(canvas)
    titlefont=typeface(round(v['title_size']),bold=True,editorial=v['typography']=='editorial_v1')
    descfont=typeface(34,editorial=v['typography']=='editorial_v1')
    title=lines(d,v['title'],titlefont,968,3,'제목');desc=lines(d,v['description'],descfont,968,2,'핵심 설명') if v['description'] else []
    # Provenance stays in the editable draft, immutable version and publishing caption.
    # Only the selected headline and description are drawn on the photo.
    bottom=1350-48
    y=round(v['text_y']*1350)
    if y+len(title)*(titlefont.size+14)+20+len(desc)*46>bottom-24:
        raise PublishingError('텍스트가 이미지 아래 여백과 겹칩니다. 텍스트 위치를 위로 옮기거나 문구·줄바꿈을 조정하세요.')
    for line in title:
        x=56
        for part in re.split('('+re.escape(v['emphasis'])+')',line) if v['emphasis'] else [line]:
            d.text((x,y),part,font=titlefont,fill=v['accent'] if part==v['emphasis'] else 'white',stroke_width=1,stroke_fill='#152031',anchor='lt')
            x+=d.textlength(part,font=titlefont)
        y+=titlefont.size+14
    y+=20
    for line in desc:d.text((56,y),line,font=descfont,fill='white',anchor='lt');y+=46
    out=BytesIO();canvas.convert('RGB').save(out,'JPEG',quality=95)
    return out.getvalue()
