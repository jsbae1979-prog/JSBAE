"""Conservative, local text rules. These do not inspect pixels or establish truth."""
import re

PROTECTION = ("No human faces or realistic people at all. No national flags, religious or political "
    "symbols, protest signs, weapons, damaged vehicles, blood, crime scenes or attackers. "
    "Use only neutral symbolic objects (e.g. map outline, building silhouette, document, "
    "abstract shapes) or a typography-only card.")
MINIMAL_TEXT = ("On the image show only the title and at most one short line (≤40 Korean characters). "
    "Do not place the full body paragraph on the image.")
NOTICE = "민감 주제: 인물·국기·사건 장면 없이 상징 이미지로 만듭니다"
RULES = {
    "violence": r"폭력|공격|테러|살해|살인|총격|흉기|무기|차량.{0,10}돌진|피습|중상|\b(?:attack(?:s|ed|er)?|terror\w*|murder\w*|shooting|weapon\w*|stabb\w*)\b",
    "conflict": r"전쟁|분쟁|무장단체|\b(?:war|conflict|militant\w*)\b",
    "disaster": r"재난|사망|지진|홍수|참사|\b(?:disaster|death\w*|killed|earthquake|flood\w*)\b",
    "sexual_crime": r"성범죄|성폭력|성추행|\b(?:rape|sexual assault)\b",
    "children": r"아동|어린이|미성년|\b(?:child(?:ren)?|minor(?:s)?)\b",
    "protest_hate": r"시위|혐오|\b(?:protest\w*|hate crime\w*)\b",
    "group_identity": r"팔레스타인|이스라엘|우크라이나|러시아|민족|종교|무슬림|유대|이슬람|기독교|민주당|공화당|국민의힘|\b(?:palestin\w*|israel\w*|ukrain\w*|russia\w*|muslim\w*|jewish|islam\w*|christian\w*|democrats?|republicans?)\b",
}
# Title followed by a name, or a name followed by a title. Deliberately conservative.
NAMED_PERSON = re.compile(r"(?:의원|대통령|총리|용의자|피해자|장관)\s+[가-힣]{2,8}(?:\s+[가-힣]{2,8})?|[가-힣]{2,8}(?:\s+[가-힣]{2,8})?\s+(?:의원|대통령|총리|용의자|피해자|장관)|\b(?:MP|President|Senator|Minister|suspect|victim)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")

def classify(title, body):
    text = str(title or '') + '\n' + str(body or '')
    reasons = [name for name, pattern in RULES.items() if re.search(pattern, text, re.I)]
    if NAMED_PERSON.search(text): reasons.append('named_person')
    return {'sensitive': bool(reasons), 'reasons': reasons}

def context_text(value):
    """Only editorial text, not URLs, credentials, identifiers, or provider metadata."""
    if isinstance(value, list): return '\n'.join(context_text(v) for v in value)
    if not isinstance(value, dict): return ''
    pieces = []
    for key, item in value.items():
        if key in {'title','body','summary','description','image_prompt'} and isinstance(item,str): pieces.append(item)
        elif key in {'source','sources','articles','plan','references','content'}: pieces.append(context_text(item))
    return '\n'.join(pieces)

def context_safety(context):
    return classify('', context_text(context))

def protect(prompt, context):
    return prompt + ('\n' + PROTECTION if context_safety(context)['sensitive'] else '')

def claim_warnings(copy, source_body):
    """Warnings are literal source gaps, not a factual judgement or a save gate."""
    text, source = str(copy or ''), str(source_body or '')
    terms = ['지목','활동가','동기','테러범','친팔레스타인','친이스라엘']
    terms += re.findall(r'(?<![가-힣])[가-힣]{2,12}계(?=\s|$|[,.]|(?:인|의|가|를|는|로))', text)
    return [f"원문에서 ‘{term}’ 표현을 확인하지 못했습니다. 근거를 검토하고 수사 중인 사건은 ‘수사 중’으로 표현하세요."
            for term in dict.fromkeys(terms) if term in text and term not in source]

def image_review_required(source):
    content = source.get('content', {})
    sources = content.get('sources') or {}
    return source.get('kind') == 'image' and (str(source.get('id','')).startswith('image:') or
        bool(sources.get('generated_image_run_id') or sources.get('full_image')))

def review_metadata(source, copy=None):
    content = source.get('content', {})
    sources = content.get('sources') or {}
    # Never use the edited caption itself as evidence of its own claims.
    original = context_text({'articles': sources.get('articles', [])})
    copy_text = context_text(copy or content)
    return {'imageSafetyRequired': image_review_required(source),
            'imageSafetyChecked': sources.get('image_safety_checked') is True,
            'imageSafety': classify(content.get('title',''), original),
            'claimWarnings': claim_warnings(copy_text, original) if original else
                (claim_warnings(copy_text, '') if source.get('kind') == 'image' else [])}
