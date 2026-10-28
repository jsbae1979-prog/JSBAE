"""Windows CI only. Uses the unchanged, previously approved disposable-app fixture."""
import base64,json,os,re,sys,time,traceback
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace as NS
HERE=Path(__file__).resolve().parent
if os.name!="nt" or os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Windows CI only")
ROOT=Path(sys.argv[1]).resolve();RUNNER=Path(os.environ["RUNNER_TEMP"]).resolve()
assert ROOT.is_relative_to(RUNNER) and ROOT.name.startswith("newsflow-gui-")
ROOT.mkdir(exist_ok=True);(ROOT/"requests").mkdir(exist_ok=True);(ROOT/"responses").mkdir(exist_ok=True)
sys.path.insert(0,str(HERE))
import pytest
from test_full_app_forms import client,token
# Preserve a class-shaped deny boundary: asyncio subclasses Popen on Windows.
# No dependency is preimported and no child process can be constructed.
import subprocess
class DeniedPopen(subprocess.Popen):
    def __new__(cls,*args,**kwargs):
        raise AssertionError("Actual process access forbidden in synthetic app integration")
class GUIMonkeyPatch(pytest.MonkeyPatch):
    def setattr(self,*args,**kwargs):
        if len(args)>=3 and args[0] is subprocess and args[1]=="Popen":
            args=(args[0],args[1],DeniedPopen)+args[3:]
        return super().setattr(*args,**kwargs)
mp=GUIMonkeyPatch();fixture=None;events=[];errors=[]
try:
    fixture=client.__wrapped__(ROOT/"profile",mp);c,app=next(fixture)
    from management_seed import seed_management
    meta=seed_management(c,app,ROOT,mp)
    (ROOT/"ready.json").write_text(json.dumps(meta),encoding="utf-8")
    deadline=time.monotonic()+600
    allowed_post=re.compile(r"^/(?:api/samples/[a-z0-9-]+/(?:copy|visibility)|schedules(?:/[a-f0-9]{32}/state)?|publishing/drafts/[0-9]+(?:/validate)?|publishing/accounts|workspace/videos/[0-9]+/remove|workspace/trash/restore|image-studio/defaults)$")
    while not (ROOT/"STOP").exists():
        if time.monotonic()>deadline:raise TimeoutError("GUI protocol session expired")
        pending=sorted((ROOT/"requests").glob("*.json"))
        if not pending:time.sleep(.015);continue
        for f in pending:
            data=json.loads(f.read_text(encoding="utf-8"))
            try:
                if data.get("kind")=="control":
                    from sqlalchemy import select,func
                    from newsflow.db.models import APIRequestReservation,PublishAttempt,PublishDraft,ProductionSchedule
                    action=data["action"]
                    with app.state.sessions.begin() as session:
                        if action=="conflict":
                            draft=session.get(PublishDraft,meta["draft"]);draft.revision+=1
                            answer={"ok":True}
                        elif action=="trash-fixture":
                            from management_seed import seed_trash_fixture
                            answer=seed_trash_fixture(c,app,session)
                        elif action=="stats":
                            answer={"reservations":[{"id":x.id,"status":x.status} for x in session.scalars(select(APIRequestReservation))],
                                "publishAttempts":session.scalar(select(func.count()).select_from(PublishAttempt)),
                                "schedules":[{"name":x.name,"status":x.status,"revision":x.revision} for x in session.scalars(select(ProductionSchedule))]}
                        else:raise ValueError("Unapproved synthetic control")
                else:
                    method=data["method"];url=data["url"]
                    assert url.startswith("/") and not url.startswith("//") and len(url)<2048
                    assert method in {"GET","HEAD"} or (method=="POST" and allowed_post.fullmatch(url.split("?")[0]))
                    body=base64.b64decode(data.get("body",""),validate=True);assert len(body)<=11*1024*1024
                    headers={k:v for k,v in data.get("headers",{}).items() if k.lower() in {"content-type","origin","cookie","range","sec-fetch-site"}}
                    response=c.request(method,url,content=body,headers=headers,follow_redirects=False)
                    answer={"status":response.status_code,"headers":dict(response.headers),"body":base64.b64encode(response.content).decode("ascii")}
                    events.append({"method":method,"path":url.split("?")[0],"status":response.status_code})
                temp=ROOT/"responses"/(f.name+".tmp")
                temp.write_text(json.dumps(answer),encoding="utf-8");temp.replace(ROOT/"responses"/f.name)
            except Exception as error:
                errors.append({"type":type(error).__name__,"reason":str(error)})
                (ROOT/"responses"/f.name).write_text(json.dumps({"error":str(error)}),encoding="utf-8")
            f.unlink()
    summary={"events":events,"errors":errors,"actual_create_app":True,"approved_fixture":"test_full_app_forms.client with class-shaped Popen denial (no permission expansion)",
             "transport":"Playwright -> synthetic file IPC -> real TestClient ASGI, no TCP app server",
             "paid_API_SNS_calls":0,"operating_data_used":False,"synthetic":True}
except Exception as error:
    errors.append({"type":type(error).__name__,"reason":str(error),"traceback":traceback.format_exc()})
    summary={"errors":errors,"events":events,"startup_failed":True}
finally:
    if fixture is not None:
        try:next(fixture)
        except StopIteration:pass
        except Exception as error:errors.append({"cleanup":str(error)})
    mp.undo()
    summary["errors"]=errors;summary["app_context_closed"]=True
    (ROOT/"backend-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print("GUI_BACKEND_SUMMARY="+json.dumps(summary))
if errors:raise SystemExit(1)
