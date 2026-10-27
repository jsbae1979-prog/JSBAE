"""Synthetic inputs only, exercising the bundled product classes and real FFmpeg."""
import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


def picture():
    buf=BytesIO();Image.new("RGB",(1080,1920),"#2456dc").save(buf,"PNG");return buf.getvalue()

class ImageFake:
    def __init__(self):self.calls=0
    def generate(self,prompt,key,*,selection):
        assert key=="synthetic-only-image-key"
        self.calls+=1
        buf=BytesIO();Image.new("RGB",tuple(map(int,selection["size"].split("x"))),"teal").save(buf,"JPEG")
        return buf.getvalue(),{"input_tokens":10,"output_tokens":20,"total_tokens":30}

def make_app(settings):
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter
    from newsflow.publishing.calendar import PublishingCalendar
    from newsflow.scheduler.service import Scheduler
    from newsflow.video.ai.service import AIVideoCoordinator
    Scheduler.start=lambda self:None
    PublishingCalendar.start=lambda self:None
    AIVideoCoordinator.start=lambda self:None
    feed="https://example.com/synthetic/rss"
    image="https://example.com/synthetic/image.png"
    rss=b'<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>Synthetic</title><item><title>Synthetic news</title><link>https://example.com/synthetic/article</link><description>Test-only news facts</description><media:thumbnail url="https://example.com/synthetic/image.png"/></item></channel></rss>'
    app=create_app(settings,FakeRSSAdapter({feed:rss,image:picture()}))
    app.state.image_generation.keys=SimpleNamespace(key=lambda:"synthetic-only-image-key",status=lambda:{"configured":True})
    app.state.image_generation.adapter=ImageFake()
    return app

def probe(root,bundle):
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from newsflow.character.compose import compose
    from newsflow.character.schema import Storyboard
    from newsflow.config import Settings
    from newsflow.creation.catalog import DEFAULTS, read_defaults, save_defaults
    from newsflow.db.models import NewsArticle, NewsSource, RenderJob, VideoProject
    from newsflow.intelligence.service import IntelligenceService
    from newsflow.video.ai.clips import probe_clip
    from newsflow.video.engine import FFmpegAdapter
    from newsflow.video.tts import FakeTTS, local_process_env
    settings=Settings.from_env()
    assert settings.data_dir==root/"AppData/Local/NewsFlowAI"
    app=make_app(settings)
    result={"scope":"Synthetic bundled engine probe; no live providers","pages":{}}
    import socket

    import technical_media
    blocked=[]
    checks=[
        ("outside-read",lambda:(root.parent/"not-an-operating-file.txt").read_bytes()),
        ("bundle-write",lambda:(bundle/"forbidden-write.txt").write_text("denied")),
        ("shell",lambda:subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/cmd.exe"),"/c","exit"],check=True)),
        ("media-traversal",lambda:technical_media.validate_process(None,[str(bundle/"media/ffmpeg.exe"),"-i","../outside.mp4",str(root/"never.mp4")],root,{})),
        ("media-filter",lambda:technical_media.validate_filter("movie=../outside.mp4")),
    ]
    for name,call in checks:
        try:call()
        except PermissionError:blocked.append(name)
        else:raise AssertionError("Boundary did not deny "+name)
    with socket.socket() as network:
        try:network.connect(("203.0.113.1",443))
        except PermissionError:blocked.append("external-connect-before-send")
        else:raise AssertionError("External boundary failed")
    result["boundary_denial_checks"]=blocked
    with TestClient(app,base_url="http://127.0.0.1:18765") as client:
        for route in ("/","/news","/ai","/video","/image-studio","/character","/publishing","/settings"):
            response=client.get(route);assert response.status_code==200,(route,response.status_code)
            result["pages"][route]=response.status_code
        with app.state.sessions.begin() as session:
            for source in session.scalars(select(NewsSource)):source.enabled=False
            session.add(NewsSource(name="Synthetic feed",url="https://example.com/synthetic/rss",enabled=True))
        app.state.coordinator.start();app.state.coordinator.future.result(30)
        with app.state.sessions() as session:
            article=session.scalar(select(NewsArticle));assert article
            article_id=article.id
            asset=app.state.video.assets/"synthetic-news.png";asset.write_bytes(picture())
            app.state.video.news_images.remember(article,asset.name,source_url="https://example.com/synthetic/image.png",rights_basis="Locally generated synthetic fixture",origin="representative")
        ai=IntelligenceService(app.state.sessions)
        analysis=ai.analyze([article_id]);draft=ai.generate(analysis,30)
        class ObservedFFmpeg(FFmpegAdapter):
            def render(self,*args,**kwargs):
                try:return super().render(*args,**kwargs)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    raise
        app.state.video.engine=ObservedFFmpeg();app.state.video.tts=FakeTTS()
        render=app.state.video.start(draft,30,reviewed=True,asset_permission=True)
        app.state.video.future.result(240)
        with app.state.sessions() as session:
            job=session.get(RenderJob,render);assert job.status=="success",job.message
            assert (job.metadata_json["width"],job.metadata_json["height"])==(1080,1920)
            project=session.get(VideoProject,job.project_id)
            assert any(x["mode"]=="automatic" for x in project.snapshot["news_images"])
            result["news"]={"render_id":render,"MP4":[1080,1920,30],"image_automatic":True,"voice":"FakeTTS silent PCM"}
        chosen={**DEFAULTS["image"],"size":"1024x1024","quality":"high"}
        char_before=read_defaults(app.state.sessions,"character")
        save_defaults(app.state.sessions,"image",chosen)
        studio=app.state.image_studio;i=studio.create("Synthetic geometry",chosen)
        _run=studio.execute(i,consent=True,reviewed=True);name=studio.export(i,reviewed=True)
        assert studio.asset(name).is_file() and read_defaults(app.state.sessions,"character")==char_before
        result["image"]={"draft":i,"Fake_calls":app.state.image_generation.adapter.calls,"reviewed_asset":True}
        c=app.state.character
        char_selection={**DEFAULTS["character"],"script_model":"claude-opus-4-6"}
        identifier=c.create("Synthetic office","5","20",reference=picture(),selection=char_selection)
        assert c.read(identifier)["claude_model"]=="claude-opus-4-6"
        clip=root/"synthetic-clip.mp4"
        subprocess.run([str(FFmpegAdapter.executable("ffmpeg",None)),"-nostdin","-n","-v","error","-f","lavfi","-i","testsrc2=size=144x256:rate=30","-t","10","-an","-c:v","libx264","-pix_fmt","yuv420p","-preset","ultrafast",str(clip)],check=True,capture_output=True,timeout=60,env=local_process_env())
        story=Storyboard.model_validate({"plan":{"situation":"합성 직장 예시","contrast":"분주함과 여유","punchline":"귤의 평온"},"title":"합성 캐릭터","hook_caption":"테스트 장면","scenes":[{"seconds":10,"role":role,"action":"A calm capybara waits in a synthetic office.","caption":"합성 장면 "+str(n),"sfx":""} for n,role in enumerate(("setup","contrast","punchline"))],"end_caption":"합성 검증 종료"})
        outputfolder=root/"character-media";outputfolder.mkdir()
        output=compose(outputfolder,story,[clip]*3)
        info=probe_clip(outputfolder/output["file"]);assert(info["width"],info["height"],info["duration"])==(1080,1920,30.0)
        result["character"]={"selection_frozen":True,"MP4":[1080,1920,30],"live_generation":False}
        result["real_API_OAuth_SNS_calls"]=0
        result["data_outside_installation"]=not settings.data_dir.is_relative_to(bundle)
        result["status"]="PASS"
    (root/"probe-safe.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")

def serve(root,bundle):
    from newsflow import main
    original=main.create_app
    # Capture before replacing factory to avoid recursion.
    from newsflow.news.rss_adapter import FakeRSSAdapter
    def factory(settings,**kwargs):
        from newsflow.publishing.calendar import PublishingCalendar
        from newsflow.scheduler.service import Scheduler
        from newsflow.video.ai.service import AIVideoCoordinator
        Scheduler.start=lambda self:None;PublishingCalendar.start=lambda self:None;AIVideoCoordinator.start=lambda self:None
        app=original(settings,FakeRSSAdapter({}),**kwargs)
        app.state.image_generation.keys=SimpleNamespace(key=lambda:"synthetic-only-image-key",status=lambda:{"configured":True})
        app.state.image_generation.adapter=ImageFake()
        return app
    main.create_app=factory
    try:
        main.run()
    except KeyboardInterrupt:
        # Uvicorn re-raises SIGBREAK after its normal cleanup. Do not convert an
        # interrupt before confirmed server cleanup to a successful technical exit.
        log=root/"AppData/Local/NewsFlowAI/logs/execution.log"
        if not log.is_file() or not log.read_text(encoding="utf-8").rstrip().endswith("server_stop"):
            raise
