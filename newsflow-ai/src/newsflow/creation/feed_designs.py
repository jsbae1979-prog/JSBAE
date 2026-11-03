"""Per-news local design drafts and immutable versions, isolated from paid batch bindings."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import re
from filelock import Timeout
from newsflow.db.models import AppSetting, NewsArticle
from newsflow.publishing.service import PublishingError
from newsflow.publishing.photo_feed import DEFAULT, STYLE, clean_image, render, validate
from newsflow.publishing.sensitive_topics import claim_warnings

class FeedDesigns:
    def __init__(self, feeds):
        self.feeds=feeds;self.sessions=feeds.sessions;self.root=feeds.root/'designs'
    def source(self,batch,rank):
        row=self.feeds.get(batch)
        source=next((i for i in row.evidence['sources'] if i['rank']==rank),None)
        item=next((i for i in row.result['items'] if i['rank']==rank),None)
        if not source or not item:raise PublishingError('선택 뉴스 연결을 확인하세요.')
        return row,source,item
    def key(self,batch,rank):return f'feed-design:{batch}:{rank}'
    def state(self,batch,rank):
        row,source,item=self.source(batch,rank)
        with self.sessions() as s:
            stored=s.get(AppSetting,self.key(batch,rank))
            if stored:return json.loads(stored.value)
        # Exact saved text; never invent or truncate a short fact. Long copy remains editable.
        short=source['body'] if len(source['body'])<=60 else ''
        return {'revision':0,'draft':{**deepcopy(DEFAULT),'title':item['content']['title'],'description':short,
            'caption':item['content']['body'],'hashtags':item['content']['hashtags'],
            'source':' · '.join(r['publisher'] for r in source['references'])},
            'background':'','assets':[],'versions':[],'posts':{}}
    def path(self,name,digest):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg)',name):raise PublishingError('편집 파일 경로를 확인하세요.')
        p=self.feeds.safe_paths.safe(self.root/name,self.root)
        if not p.is_file() or sha256(p.read_bytes()).hexdigest()!=digest:raise PublishingError('편집 이미지가 없거나 변경됐습니다.')
        return p
    def candidates(self,batch,rank,state=None):
        row,source,item=self.source(batch,rank);result=[]
        if item.get('status')=='success':
            try:
                # The original generated image is a separate background, not the local title derivative.
                p=self.feeds.generation.path(item['generation_id'],article_id=source['article_id'],analysis_id=row.evidence['analysis_id'],rank=rank)
                result.append({'id':'generated','label':'기존 생성 원본','kind':'ai','credit':'AI 생성','path':p,'sha256':sha256(p.read_bytes()).hexdigest()})
            except (AttributeError,PublishingError,OSError,ValueError):
                pass
            try:
                p=self.feeds.path(batch,rank)
                result.append({'id':'result','label':'기존 완성 이미지 (문구 포함 가능)','kind':'ai','credit':'AI 생성','path':p,'sha256':sha256(p.read_bytes()).hexdigest()})
            except (PublishingError,OSError,ValueError):pass
        with self.sessions() as s:
            article=s.get(NewsArticle,source['article_id'])
            for c in self.feeds.safe_paths.candidates(article) if article else []:
                result.append({'id':'article:'+c['sha256'],'label':'기사 대표 이미지 · 보관본','kind':'stock',
                    'credit':'', 'provenance':{'articleId':article.id,'sourceUrl':c['source_url'],'rightsBasis':c['rights_basis']}, 'path':self.feeds.safe_paths.asset(c['name']),'sha256':c['sha256']})
        for asset in (state or self.state(batch,rank))['assets']:
            try:result.append({**asset,'path':self.path(asset['filename'],asset['sha256'])})
            except (PublishingError,OSError,ValueError):pass
        for version in (state or self.state(batch,rank))['versions']:
            frozen=version['background']
            try:
                result.append({**frozen,'id':f"version:{version['version']}",
                    'label':f"편집 버전 {version['version']}의 원본 배경",'path':self.path(frozen['filename'],frozen['sha256'])})
            except (PublishingError,OSError,ValueError):pass
        return result
    def resolve(self,batch,rank,identifier,state):
        result=next((c for c in self.candidates(batch,rank,state) if c['id']==identifier),None)
        if not result:raise PublishingError('배경 이미지를 선택하세요. 연결된 로컬 보관본 또는 업로드만 사용할 수 있습니다.')
        return result
    def view(self,batch,rank):
        state=self.state(batch,rank);_,source,item=self.source(batch,rank)
        from .feed_growth import copy_options
        candidates=[];groups={}
        for c in self.candidates(batch,rank,state):
            key=(c['sha256'],c['kind'],c['credit'])
            if key not in groups:groups[key]={**c,'aliases':[c['id']]}
            else:
                aliases=groups[key]['aliases']+[c['id']]
                if c['id']==state['background']:groups[key]={**c,'aliases':aliases}
                else:groups[key]['aliases']=aliases
        candidates=[{k:v for k,v in c.items() if k!='path'} for c in groups.values()]
        generated=next((c for c in candidates if 'generated' in c.get('aliases',[])),None)
        selected=next((c for c in candidates if state['background'] in c.get('aliases',[])),None)
        fresh=bool(generated and item.get('attempt',1)>1 and item.get('generation_id') and
                   state.get('generation_id')!=item['generation_id'] and
                   (not selected or selected['sha256']!=generated['sha256']))
        return {**state,'newGeneratedBackground':generated['id'] if fresh else None,
            'batch':batch,'rank':rank,'articleId':source['article_id'],'sourceTitle':source['title'],
            'originalSummary':source['body'],'candidates':candidates,
            'copyOptions':copy_options(source,item,state['draft']),
            'needsCopy':not bool(state['draft']['description']),
            'warnings':self.copy_warnings(state['draft'],source)}
    @staticmethod
    def copy_warnings(draft,source):
        original=source['title']+' '+source['body'];text=draft['title']+' '+draft['description']
        warnings=claim_warnings(text,original)
        for before,after in [('검토','확정'),('예정','시행'),('공개','최초 발견')]:
            if before in original and after in text and after not in original:
                warnings.append(f'진행 상태 확인: 원문의 ‘{before}’를 ‘{after}’로 바꾸지 마세요.')
        for number in dict.fromkeys(re.findall(r'\d+(?:[.,]\d+)*(?:%|km|㎞|초|년|월|일|명|억|만)?',text)):
            if number not in original:warnings.append(f'원문에서 수치 ‘{number}’를 확인하지 못했습니다. 단위·날짜를 확인하세요.')
        return warnings
    def write(self,batch,rank,state):
        with self.sessions.begin() as s:
            row=s.get(AppSetting,self.key(batch,rank));value=json.dumps(state,ensure_ascii=False)
            if row:row.value=value
            else:s.add(AppSetting(key=self.key(batch,rank),value=value))
    def checked(self,batch,rank,revision):
        state=self.state(batch,rank)
        if type(revision) is not int or state['revision']!=revision:raise PublishingError('다른 화면에서 편집됐습니다. 다시 열어 확인하세요.')
        return state
    def file(self,raw,suffix):
        self.feeds.safe_paths.safe(self.root,self.root).mkdir(parents=True,exist_ok=True)
        name=uuid4().hex+'.'+suffix;p=self.root/name
        with p.open('xb') as f:f.write(raw)
        return {'filename':name,'sha256':sha256(raw).hexdigest()}
    def upload(self,batch,rank,revision,raw,kind,credit):
        if kind not in {'photo','stock','ai'} or not isinstance(credit,str) or not 1<=len(credit.strip())<=160:
            raise PublishingError('이미지 구분과 크레딧을 입력하세요.')
        clean=clean_image(raw)
        try:
            with self.feeds.lock:
                state=self.checked(batch,rank,revision);stored=self.file(clean,'png')
                asset={**stored,'id':'upload:'+stored['filename'],'label':'선택한 이미지','kind':kind,'credit':credit.strip()}
                state['assets'].append(asset);state['background']=asset['id'];state['draft']['credit']=asset['credit']
                state['revision']+=1;self.write(batch,rank,state)
        except Timeout:raise PublishingError('작업이 진행 중입니다. 잠시 후 확인하세요.') from None
        return self.view(batch,rank)
    def prepare(self,batch,rank,state,background,design):
        c=self.resolve(batch,rank,background,state);v=validate(design)
        if background!=state['background'] and v['credit']==state['draft']['credit']:v['credit']=c['credit']
        if c['kind']=='ai' and not v['credit'].strip():v['credit']='AI 생성'
        return c,v
    def preview(self,batch,rank,revision,background,design):
        state=self.checked(batch,rank,revision);c,v=self.prepare(batch,rank,state,background,design)
        return render(c['path'].read_bytes(),v,c['kind'])
    def save(self,batch,rank,revision,background,design,*,export=False):
        try:
            with self.feeds.lock:
                state=self.checked(batch,rank,revision);c,v=self.prepare(batch,rank,state,background,design)
                if export:
                    if not v['description'].strip():raise PublishingError('핵심 설명을 입력하세요. 자료가 부족하면 확인 필요로 남겨 주세요.')
                    raw=render(c['path'].read_bytes(),v,c['kind'])
                    # Freeze background as well: later replacement of a source cannot change a saved version.
                    frozen=self.file(clean_image(c['path'].read_bytes()),'png')
                    version={'version':len(state['versions'])+1,'design':v,'background':{**frozen,'kind':c['kind'],'credit':v['credit'],'sourceId':background,'provenance':deepcopy(c.get('provenance',{}))},**self.file(raw,'jpg')}
                    state['versions'].append(version)
                    background=f"version:{version['version']}"
                _,_,item=self.source(batch,rank)
                state.update(draft=v,background=background,generation_id=item.get('generation_id'),revision=state['revision']+1);self.write(batch,rank,state)
        except Timeout:raise PublishingError('작업이 진행 중입니다. 잠시 후 확인하세요.') from None
        return self.view(batch,rank)
    def version(self,batch,rank,number):
        version=next((v for v in self.state(batch,rank)['versions'] if v['version']==number),None)
        if not version:raise PublishingError('저장된 편집 버전을 확인하세요.')
        self.path(version['filename'],version['sha256']);return version

    def review(self,batch,rank,number,posts,*,reviewed=False,image_safety_checked=False):
        if reviewed is not True or image_safety_checked is not True:raise PublishingError('내용·권리·출처와 이미지 안전을 확인하세요.')
        try:
            with self.feeds.lock:
                row,source,_=self.source(batch,rank);state=self.state(batch,rank);v=self.version(batch,rank,number)
                if row.options['simulation']:raise PublishingError('합성 검증 이미지는 게시용으로 저장할 수 없습니다.')
                previous=state['posts'].get(str(number))
                if previous:return previous
                d=v['design']
                identifier=posts.create(source['article_id'],title=d['title'],body=d['caption'],hashtags=d['hashtags'],
                    reviewed=True,rights=True,sources_confirmed=True,ai_disclosure='disclose' if v['background']['kind']=='ai' else 'not_required',
                    draft_id=source['draft_id'],analysis_id=row.evidence['analysis_id'],rank=rank,feed_batch_id=batch,
                    feed_design_version=number,image_safety_checked=True)
                state['posts'][str(number)]=identifier;state['revision']+=1;self.write(batch,rank,state);return identifier
        except Timeout:raise PublishingError('저장 중입니다. 잠시 후 확인하세요.') from None
