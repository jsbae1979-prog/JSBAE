"""Isolated design fixtures only. Existing preview boundary still denies external calls."""
from pathlib import Path
import importlib.util, hashlib, shutil, subprocess
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from newsflow.db.models import NewsArticle, RenderJob
repo=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('guarded_design_preview',repo/'tools/ui_preview.py')
demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
original_seed=demo.seed

def visual_seed(app,root):
 original_seed(app,root)
 atlas=repo/'src/newsflow/static/images/news-topic-atlas.png'
 font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
 shutil.copyfile(font,root/'demo-font.ttc')
 now=datetime.now(timezone.utc)
 with app.state.sessions.begin() as session:
  articles=list(session.scalars(select(NewsArticle).order_by(NewsArticle.id)))
  for index,article in enumerate(articles):
   article.collected_at=now-timedelta(days=2-index)
   article.category=['IT·과학','국제','문화'][index]
  session.add(NewsArticle(title='차세대 에너지 기술, 태양광의 가능성을 살펴봅니다',url='https://example.com/design-4',canonical_url='https://example.com/design-4',source_id=articles[0].source_id,publisher='UI 데모',summary='디자인 검토용 합성 기사',category='IT·과학',collected_at=now))
  for index,render in enumerate(session.scalars(select(RenderJob).order_by(RenderJob.id))):
   target=app.state.video.outputs/render.output_name
   assert target.resolve().is_relative_to(root.resolve())
   # Only synthetic demo MP4s in the newly created temporary directory.
   crop=['crop=iw/2:ih/2:0:ih/2','crop=iw/2:ih/2:iw/2:ih/2','crop=iw/2:ih/2:iw/2:0'][index]
   text=['새로운 에너지','우주를 향한 시선','도시의 내일을'][index]
   vf=crop+",scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,drawbox=x=0:y=1370:w=1080:h=550:color=black@0.5:t=fill,drawtext=fontfile=demo-font.ttc:text='"+text+"':fontsize=74:fontcolor=white:x=60:y=1450,drawtext=fontfile=demo-font.ttc:text='디자인 데모 · AI 주제 이미지':fontsize=32:fontcolor=white:x=60:y=120,drawtext=fontfile=demo-font.ttc:text='합성 자료 · 무음 · 실제 보도 아님':fontsize=28:fontcolor=white:x=60:y=1800"
   subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-framerate','10','-i',str(atlas),'-f','lavfi','-i','anullsrc=r=44100:cl=stereo','-vf',vf,'-t','30','-c:v','libx264','-threads','2','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(target)],check=True,cwd=root)
   render.metadata_json={**render.metadata_json,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
   render.finished_at=now-timedelta(days=2-index)

if __name__ == "__main__":
 demo.seed=visual_seed
 demo.main()
