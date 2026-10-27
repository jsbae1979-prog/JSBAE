"""Reconcile documentation shorthand against real router decorators; no app import."""
import ast
import csv
import json
import re
from pathlib import Path

P=Path(__file__).resolve().parents[2]
D=P/'docs/design/studio-v3.0';S=P/'src/newsflow';O=D/'implementation'
all_routes={}
for file in (S/'gui').glob('*.py'):
    routes=[]
    for node in ast.walk(ast.parse(file.read_text(encoding='utf-8-sig'))):
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
        for decorator in node.decorator_list:
            if isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute) and decorator.func.attr in {'get','post'} and decorator.args and isinstance(decorator.args[0],ast.Constant):routes.append((decorator.func.attr.upper(),decorator.args[0].value))
    all_routes['gui/'+file.name]=routes
rows=list(csv.DictReader((D/'Feature_Trace_56_v3.0.csv').open(encoding='utf-8-sig')))
notes={('NF-06','/news/{article_id}'):('SOURCE_REFERENCE_MISMATCH',['GET /news/{article_id}'],'gui/routes.py','기사 상세는 routes.py, 대표 이미지는 news_thumbnail_routes.py의 별도 라우트입니다.'),('NF-11','.../cancel'):('DOCUMENT_SHORTHAND',['POST /ai/codex/cancel','POST /ai/claude/cancel'],'gui/intelligence_routes.py','생략 기호를 두 실제 취소 라우트로 전개합니다.'),('CR-03','/autopilot/jobs/{job_id}/{cancel|resume|retry}'):('ALTERNATIVE_NOTATION',[f'POST /autopilot/jobs/{{job_id}}/{a}' for a in ['cancel','resume','retry']],'gui/autopilot_routes.py','문서의 대안 표기를 실제 독립 라우트로 전개합니다.'),('CR-10','/video/ai/plans/{plan_id}/scenes/{position}/{cancel|resolve|refetch}'):('ALTERNATIVE_NOTATION',[f'POST /video/ai/plans/{{plan_id}}/scenes/{{position}}/{a}' for a in ['cancel','resolve','refetch']],'gui/video_ai_routes.py','장면별 취소·결과 확인·재조회는 서로 다른 보호 동작입니다.'),('OP-05','/video/jobs/{job_id}/file'):('SOURCE_REFERENCE_MISMATCH',['GET /video/jobs/{job_id}/file'],'gui/video_routes.py','목록은 setup_routes.py, 검증된 영상 파일은 video_routes.py입니다.'),('CR-21','/image-studio/drafts'):('SERVICE_ROUTER_SPLIT',['POST /image-studio/drafts'],'gui/creation_routes.py','서비스 구현과 HTTP 어댑터 파일을 구분합니다.'),('CR-21','/image-studio/{identifier}/reuse'):('SERVICE_ROUTER_SPLIT',['POST /image-studio/{identifier}/reuse'],'gui/creation_routes.py','로컬 참조 저장·소재 재사용이며 참조 기반 유료 편집은 미구현입니다.')}
exceptions=[];mapped=[];exact=0;expected_total=0
for row in rows:
    files=[x.strip() for x in re.split('[;|]',row['source_file']) if x.strip()]
    found=[f for f in files if (P/f if f.startswith('tools/') else S/f).is_file()]
    routes=[r for f in files for r in all_routes.get(f,[])]
    expected=re.findall(r'(GET|POST|PUT|PATCH|DELETE)\s+([^;\s]+)',row['source_entry'])
    matches=0
    for verb,url in expected:
        expected_total+=1
        if (verb,url) in routes:matches+=1;exact+=1;continue
        category,actual,file,note=notes[(row['id'],url)]
        verified=all(tuple(x.split(' ',1)) in all_routes[file] for x in actual)
        assert verified,(row['id'],actual,file)
        exceptions.append({'id':row['id'],'expected':verb+' '+url,'classification':category,'actual':actual,'source':file,'route_existence_verified':verified,'product_defect_confirmed':False,'note':note})
    path=row['studio_route'];canonical='/studio/'+('shorts' if path.startswith('/studio/create/news') else 'characters' if path.startswith('/studio/create/character') else 'images' if path.startswith('/studio/create/image') else path.split('/')[2].split('?')[0])
    mapped.append({**row,'current_source_files':';'.join(found),'source_present':len(found)==len(files),'expected_literal_routes':len(expected),'exact_literal_matches':matches,'react_module':canonical,'react_state':'REACT_COMPONENT_AND_ORIGINAL_FORM_ADAPTER','runtime_acceptance':'FOCUSED_SYNTHETIC_EVIDENCE_ONLY','actual_provider_acceptance':'NOT VERIFIED'})
assert len(rows)==56 and len(exceptions)==7
with (O/'Feature_Trace_current.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(mapped[0]));writer.writeheader();writer.writerows(mapped)
(O/'literal-mapping-seven.json').write_text(json.dumps(exceptions,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'groups':56,'source_present':sum(x['source_present'] for x in mapped),'route_expectations':expected_total,'exact_literal_matches':exact,'nonliteral_expectations':len(exceptions),'affected_groups':len({x['id'] for x in exceptions}),'resolved_documentation_differences':7,'confirmed_product_defects_in_seven':0,'react_screen_modules':12,'original_form_commands':len(json.loads((P/'src/newsflow/studio/actions.json').read_text(encoding='utf-8'))),'all_groups_runtime_pass':False,'paid_reference_image_edit':'NOT IMPLEMENTED','operating_apply':'NOT AUTHORIZED'}
(O/'feature-map-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
