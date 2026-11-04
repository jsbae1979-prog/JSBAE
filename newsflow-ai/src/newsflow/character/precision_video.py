"""Bridge confirmed still images into the existing episode video/composition path."""
from copy import deepcopy
from decimal import Decimal
from .episode_story import EpisodeScript
from .precision_contract import motion_rows, CONTINUITY_POLICY, validate_connections
from .kling import check, normalize_reference
from .service import fingerprint, now
from .compose import digest
from .schema import CharacterError

def validate(job,value):
    from newsflow.video_models.catalog import CATALOG, duration_values
    story=EpisodeScript.model_validate(value)
    selected=check(job['studio_selection'])
    model=CATALOG.model(selected['video_model'])
    if not model or sum(s.seconds for s in story.scenes)!=job['duration']:
        raise CharacterError('media')
    connected = job.get('continuity_policy') == CONTINUITY_POLICY
    if connected:
        plans = job['precision']['plans']
        validate_connections(plans, model)
        expected = motion_rows(job['precision']['common'],job['precision']['cast'],plans,selected,CONTINUITY_POLICY)
        if len(story.scenes)!=len(plans) or job['prompts'] != expected or any((s.no,s.seconds,s.continuity,s.from_scene,s.action,s.camera)!=(p['no'],p['seconds'],p['connection'],p['no']-1 if p['connection']=='continue' else None,p['motion'],p['motion_camera']) for s,p in zip(story.scenes,plans)):
            raise CharacterError('media')
    if any(s.seconds not in duration_values(model) or (not connected and s.continuity!='cut') for s in story.scenes):
        raise CharacterError('media')
    if len(job['precision']['images'])!=len(story.scenes): raise CharacterError('media')
    return story

def handoff(service,w):
    owner=service.characters
    scenes=w['scenes']
    if not scenes or any(s['state']!='confirmed' or not s['confirmed'] for s in scenes):
        raise ValueError('모든 장면 이미지를 먼저 확정하세요.')
    selected=check(w['video_settings'])
    plan=motion_rows(w['common'],w['cast'],[s['plan'] for s in scenes],selected,w.get('continuity_policy'))
    script={'schema_version':3,'plan':{'situation':w['common']['topic'],
        'escalation':'장면별 상황 전개','reaction':'캐릭터의 시각적 반응','punchline':'마지막 장면의 반전'},
        'title':w['common']['title'][:60],'hook_caption':'','end_caption':'',
        'upload':{'title':w['common']['title'][:60],'description':w['common']['topic'],
                  'hashtags':['#캐릭터','#쇼츠','#애니메이션']},
        'scenes':[{'no':s['plan']['no'],'seconds':s['plan']['seconds'],'continuity':s['plan']['connection'] if w.get('continuity_policy')==CONTINUITY_POLICY else 'cut',
                   'from':s['plan']['no']-1 if w.get('continuity_policy')==CONTINUITY_POLICY and s['plan']['connection']=='continue' else None,
                   'action':s['plan']['motion'],'camera':s['plan']['motion_camera'],
                   'sound':s['plan']['sound'],'caption':s['plan']['caption'],'sfx':s['plan'].get('sfx',[])} for s in scenes]}
    script=EpisodeScript.model_validate(script).model_dump(by_alias=True)
    evidence=[];raws=[]
    for s in scenes:
        v=next(v for v in s['versions'] if v['version']==s['confirmed']['version'])
        if v['state']!='success' or v['plan_hash']!=fingerprint(s['plan']): raise ValueError('장면 내용이 변경됐습니다.')
        raw=service.images.asset(v['asset']).read_bytes()
        import hashlib
        if hashlib.sha256(raw).hexdigest()!=s['confirmed']['sha256']: raise ValueError('확정 이미지가 변경됐습니다.')
        raw=normalize_reference(raw);raws.append(raw)
        evidence.append({'no':s['plan']['no'],'version':v['version'],'asset':v['asset'],
                         'sha256':hashlib.sha256(raw).hexdigest(),'confirmed_at':s['confirmed']['at'],
                         'filename':f"precision-scene-{s['plan']['no']}.png"})
    with owner.lock():
        # Deterministic target makes interruption before linking recoverable without a second job.
        folder=owner.folder(w['id'])
        if (folder/'jobs.json').exists():
            old=owner.read(w['id'])
            if old.get('precision',{}).get('source_hash')!=fingerprint([w['scenario'],evidence]):
                raise ValueError('기존 영상 전달 기록을 확인하세요.')
            return old['id']
        folder.mkdir(exist_ok=True)
        for e,raw in zip(evidence,raws):
            path=folder/e['filename']
            if path.is_symlink() or path.is_junction(): raise ValueError('이미지 경로를 확인하세요.')
            if path.exists() and digest(path)!=e['sha256']: raise ValueError('기존 이미지가 달라 덮어쓰지 않습니다.')
            if not path.exists(): path.write_bytes(raw)
        ref=folder/'reference.png'
        if ref.is_symlink() or ref.is_junction(): raise ValueError('참조 경로를 확인하세요.')
        if ref.exists() and digest(ref)!=evidence[0]['sha256']: raise ValueError('참조 이미지 충돌')
        if not ref.exists(): ref.write_bytes(raws[0])
        job={'id':w['id'],'automation_version':1,'created_at':now().isoformat(),'state':'script_review',
            'topic':w['common']['topic'],'character':deepcopy(next(iter(w['cast'].values()))),
            'character_id':next(iter(w['cast'])),'model':selected['video_model'],
            'claude_model':selected['script_model'],'script_provider':'precision_existing_story',
            'script':script,'prompts':plan,'reference_sha256':digest(ref),'episode_limit':w['video_limit'],
            'day_limit':w['video_limit'],'duration':w['common']['duration'],'events':[], 'scenes':[],
            'reported_billed_usd':None,'made_for_kids':False,'studio_selection':w['video_settings'],
            'precision':{'work_id':w['id'],'images':evidence,'cast':deepcopy(w['cast']),
                'common':deepcopy(w['common']),'source_hash':fingerprint([w['scenario'],evidence])},
            'text_costs':[], 'script_hash':fingerprint(script)}
        # Keep text budget reservations visible to the existing video budget guard.
        job['text_reservations']=[{'attempt':i+1,'usd':a.get('reserved_usd','0'),'basis':'reserved_ceiling_not_actual_bill'} for i,a in enumerate(w['story_attempts'])]
        if w.get('continuity_policy')==CONTINUITY_POLICY:
            job['continuity_policy']=CONTINUITY_POLICY
            job['precision']['plans']=[deepcopy(s['plan']) for s in scenes]
        job['plan_hash']=owner.plan_hash(job)
        validate(job,script);owner.save(job)
        return job['id']

def reference_path(owner,job,position):
    item=next((x for x in job['precision']['images'] if x['no']==position),None)
    if not item: raise CharacterError('reference')
    # No persisted arbitrary path is followed.
    path=owner.folder(job['id'])/f'precision-scene-{position}.png'
    if path.is_symlink() or path.is_junction() or digest(path)!=item['sha256']:
        raise CharacterError('reference')
    return path
