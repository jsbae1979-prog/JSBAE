"""Real create_app initialization and read-only ASGI, Windows CI only."""
from pathlib import Path
import asyncio
import re
import threading
APP=None

def initialize(data,policy):
    global APP
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter
    APP=create_app(Settings(data_dir=data,port=18765,secret_key="synthetic-app-policy-secret-000000000000"),
                   FakeRSSAdapter({}),automatic_start=True)
    assert APP.state.config.data_dir==data and APP.state.config.port==18765
    # Lifespan is deliberately not entered: no Scheduler.start / Calendar.start.
    assert APP.state.scheduler.thread is None
    assert APP.state.video_ai.thread is None
    return {"create_app":"PASS","automatic_start":True,"lifespan_entered":False,
            "scheduler_started":False,"publishing_started":False,"data_dir_in_runner_temp":True}

async def read_models(policy):
    import httpx
    results=[];assets=set()
    transport=httpx.ASGITransport(app=APP)
    with policy.read_only_asgi():
        async with httpx.AsyncClient(transport=transport,base_url="http://127.0.0.1:18765",follow_redirects=False) as client:
            for url in ("/studio/shorts","/studio/characters","/studio/images","/studio/images?mode=top3","/studio/news"):
                response=await client.get(url)
                assert response.status_code==200,(url,response.status_code)
                assert '<div id="root">' in response.text
                csp=response.headers["content-security-policy"]
                assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
                assets.update(re.findall(r'(?:src|href)="(/studio/assets/[^"<>]+\.(?:js|css))"',response.text))
                results.append({"path":url,"status":200,"CSP":"preserved"})
            assert any(x.endswith(".js") for x in assets) and any(x.endswith(".css") for x in assets)
            for url in sorted(assets):
                response=await client.get(url);assert response.status_code==200 and len(response.content)>100
                results.append({"path":url,"status":200,"bytes":len(response.content)})
            for module in ("news","shorts","characters","images"):
                url="/api/studio/modules/"+module;response=await client.get(url)
                assert response.status_code==200,(url,response.status_code,response.text[:100])
                payload=response.json();assert payload["module"]==module and payload["schemaVersion"]==1
                results.append({"path":url,"status":200,"synthetic_empty_state":True})
    return results

def cleanup():
    if APP is None:return []
    errors=[]
    for name in ("youtube","tiktok","instagram","publishing_calendar","scheduler",
                 "video_ai","autopilot","autopilot_backend","coordinator","video"):
        item=getattr(APP.state,name,None)
        if item is not None:
            try:item.close()
            except Exception as error:errors.append({"resource":name,"type":type(error).__name__,"reason":str(error)})
    try:APP.state.engine.dispose()
    except Exception as error:errors.append({"resource":"engine","type":type(error).__name__,"reason":str(error)})
    return errors
