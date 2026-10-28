"""Export a NON-ACTIVE catalog using existing schema1 and unique new asset IDs."""
import hashlib,json,sys
from pathlib import Path
from PIL import Image

root=Path(sys.argv[1]);old_path=Path(sys.argv[2])
provenance=json.loads((root/'manifest.json').read_text(encoding='utf8'))
if provenance.get('version')!=2:raise ValueError('Fresh provenance catalog-v2 required')
(root/'PROVENANCE_MANIFEST.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf8')
old=json.loads(old_path.read_text(encoding='utf8'))
old_rows={r['id']:r for r in old['assets']};rows=[]
for r in provenance['assets']:
    base=dict(old_rows[r['id'][:-3]])
    # Retain only the public schema/UI hints, not old source or archive claims.
    base={k:v for k,v in base.items() if k in {'title','description','type','target','mime','format','promptExample'}}
    base.update(id=r['id'],path=r['path'],bytes=r['bytes'],sha256=r['sha256'],
        width=r['dimensions'][0],height=r['dimensions'][1],sample=True,version=1,contentRevision=2,
        rightsVerified=False,providerGenerated=False,productProviderGenerated=False,
        originAiGenerated=not r['path'].endswith('.mp4'),editableProject=False,
        source='현재 승인된 Codex 세션의 신규 image_gen 원본 및 로컬 FFmpeg 파생. GENERATION_RECORDS.json 참조.',
        license='공식 출력물 약관/생성 이력 확보. 배포 주체의 적용 계약·재배포 권한 최종 확인 전 상업 배포 보류.',
        activeInProduct=False)
    if r['path'].endswith('.mp4'):
        base.update(duration=r['duration'],audio=False,videoCodec='h264',pixelFormat='yuv420p',
            description='새 이미지로 만든 12초 무음 샘플 미리보기. 움직이는 AI 장면/음성/편집 원본 프로젝트가 아닙니다.')
        poster=root/(r['id']+'-preview.png')
        with Image.open(poster) as image:width,height=image.size
        base['poster']={'path':poster.name,'bytes':poster.stat().st_size,
            'sha256':hashlib.sha256(poster.read_bytes()).hexdigest(),'width':width,'height':height}
        if r['id'].startswith('character-short'):
            base['referenceId']='character-'+('robot' if 'robot' in r['id'] else 'cat')+'-v2'
    else:
        base['promptExample']=r['source']['prompt']
        base['mode']='RGBA' if base['type']=='character' else 'RGB'
    rows.append(base)
catalog={'version':1,'schemaVersion':1,'contentRevision':2,'sample':True,'candidateOnly':True,
    'activeInProduct':False,'assets':rows,'notice':'version1 is the unchanged loader schema; contentRevision2 and new -v2 IDs identify new content. Existing product catalog is untouched.'}
(root/'manifest.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
print('Prepared compatible inactive sample catalog:',len(rows))
