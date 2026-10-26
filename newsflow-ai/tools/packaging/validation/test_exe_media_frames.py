"""Read only synthetic MP4s from the frozen-engine probe."""
from pathlib import Path
import os,json,subprocess
from PIL import Image,ImageDraw
def test_frozen_news_and_character_actual_frames():
    root=Path(os.environ['STEP13_ROOT'])
    probe=root/'exe-probe6'
    news=list((probe/'AppData/Local/NewsFlowAI').rglob('*.mp4'))
    assert len(news)==1
    videos={'news':news[0],'character':probe/'character-media/final.mp4'}
    out=Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])/'frozen-media';out.mkdir(parents=True)
    evidence=[]
    sheet=Image.new('RGB',(810,960),'#101726')
    for row,(mode,video) in enumerate(videos.items()):
        for col,second in enumerate((5,15,25)):
            frame=out/f'{mode}-{second}.png'
            subprocess.run([os.environ['NEWSFLOW_FFMPEG'],'-nostdin','-v','error','-n','-ss',str(second),
                '-i',str(video),'-frames:v','1',str(frame)],check=True,timeout=40,capture_output=True)
            with Image.open(frame) as image:
                assert image.size==(1080,1920)
                if mode=='news':
                    pixel=image.convert('RGB').getpixel((540,900))
                    assert max(abs(x-y) for x,y in zip(pixel,(36,86,220)))<12,pixel
                tile=image.convert('RGB').resize((270,480));sheet.paste(tile,(col*270,row*480))
            evidence.append({'mode':mode,'second':second,'size':[1080,1920],'status':'PASS'})
    sheet.save(out/'contact-sheet.png')
    (out/'result-safe.json').write_text(json.dumps({'frames':evidence,'news_image_matches_all_three':True,'real_API':False},indent=2))
