"""Retired bundled starter content. Read-only compatibility for user-owned copies only.

No package sample file is read, copied, registered or shown. Existing user-created
projects, media and sample-copies/v1 files/settings remain untouched.
"""
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy import select
from newsflow.db.models import AppSetting

ROOT=Path(__file__).resolve().parents[1]/'assets'/'samples'
PREFIX='sample_content:v1:'
class SampleError(ValueError):pass

def safe_path(base,relative):
    base=Path(base);rel=Path(relative)
    if rel.is_absolute() or any(p in {'..','.'} or ':' in p for p in rel.parts):raise SampleError('참조 파일 경로를 확인하세요.')
    path=base/rel
    if not path.resolve().is_relative_to(base.resolve()):raise SampleError('참조 파일 경로를 확인하세요.')
    for current in [path,*path.parents]:
        if current.is_symlink() or current.is_junction():raise SampleError('연결된 참조 경로는 사용할 수 없습니다.')
        if current==base:break
    return path

class Samples:
    def __init__(self,sessions,data_dir,image_studio,root=ROOT):
        self.sessions=sessions;self.data_dir=Path(data_dir);self.root=Path(root);self.image_studio=image_studio
    def catalog(self):return [],''
    def listing(self):return {'schemaVersion':1,'sample':False,'removed':True,'assets':[],'warning':''}
    def get(self,identifier):raise SampleError('기본 콘텐츠 제공이 종료되었습니다.')
    def checked(self,*args,**kwargs):raise SampleError('기본 콘텐츠 제공이 종료되었습니다.')
    def copy(self,*args,**kwargs):raise SampleError('새 기본 콘텐츠 복사는 지원하지 않습니다.')
    def hide(self,*args,**kwargs):raise SampleError('기본 콘텐츠 표시 기능이 제거되었습니다.')

    def copied_file(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-z0-9-]{1,48}',identifier):raise SampleError('보관한 참조 파일을 확인하세요.')
        with self.sessions() as session:
            row=session.get(AppSetting,PREFIX+'copy:'+identifier)
            if row is None:raise SampleError('보관한 참조 파일을 확인하세요.')
            try:record=json.loads(row.value)
            except (ValueError,TypeError):raise SampleError('보관 기록을 확인하세요.') from None
        if (not isinstance(record,dict) or record.get('id')!=identifier or record.get('version')!=1
                or not isinstance(record.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',record['sha256'])):
            raise SampleError('보관 기록을 확인하세요.')
        matches=[]
        for ext,mime in [('.png','image/png'),('.jpg','image/jpeg'),('.mp4','video/mp4')]:
            path=safe_path(self.data_dir,f'sample-copies/v1/{identifier}/{record["sha256"]}{ext}')
            if path.is_file():matches.append((path,mime))
        if len(matches)!=1:raise SampleError('보관한 참조 파일을 확인하세요.')
        path,mime=matches[0]
        if not 0<path.stat().st_size<=512*1024*1024:raise SampleError('참조 파일 크기를 확인하세요.')
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        if digest.hexdigest()!=record['sha256']:raise SampleError('보관한 참조 파일의 무결성을 확인하세요.')
        return {'id':identifier,'mime':mime,'sha256':record['sha256']},path

    def owned_references(self):
        with self.sessions() as session:
            identifiers=[r.key.removeprefix(PREFIX+'copy:') for r in session.scalars(
                select(AppSetting).where(AppSetting.key.startswith(PREFIX+'copy:')))]
        result=[]
        for identifier in identifiers:
            try:row,path=self.copied_file(identifier)
            except (OSError,ValueError):continue
            image=row['mime'].startswith('image/')
            result.append({'id':'reference:'+identifier,'title':'보관한 참조 파일 · '+identifier,
                'kind':'image' if image else 'reference','referenceOnly':True,'technicalStatus':'stored',
                'sourceLabel':'사용자가 보관한 참조 파일','mediaUrl':f'/api/samples/{identifier}/copy-file',
                'updatedAt':datetime.fromtimestamp(path.stat().st_mtime,UTC).isoformat(),
                'contentReviewStatus':'review_required','publishApprovalStatus':'separate_approval_required'})
        return result
