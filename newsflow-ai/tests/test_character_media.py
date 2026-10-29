"""Three 30s local MP4s from synthetic clips; no real mascot, supplier or TTS generation."""
import json
import os
import shutil
import subprocess

import pytest
from test_character_shorts import prepared, sessions, setup, store, story

from newsflow.character.compose import compose
from newsflow.character.schema import Storyboard
from newsflow.video.ai.clips import probe_clip
from newsflow.video.ai.contracts import ClipStatus
from newsflow.video.engine import FFmpegAdapter
from newsflow.video.tts import local_process_env

__all__=['sessions','setup','store']


@pytest.fixture(scope='module')
def synthetic_clip(tmp_path_factory):
    folder=tmp_path_factory.mktemp('synthetic-character-media')
    ffmpeg=FFmpegAdapter.executable('ffmpeg',None)
    FFmpegAdapter.executable('ffprobe',None)
    path=folder/'synthetic.mp4'
    command=[str(ffmpeg),'-nostdin','-n','-v','error','-f','lavfi','-i',
             'testsrc2=size=144x256:rate=30','-t','10','-an','-c:v','libx264','-pix_fmt','yuv420p',
             '-preset','ultrafast',str(path)]
    subprocess.run(command,check=True,capture_output=True,timeout=60,env=local_process_env())
    with pytest.MonkeyPatch.context() as patch:
        if os.environ.get('CHARACTER_CI_FONT'):
            patch.setenv('NEWSFLOW_FONT_PATH',os.environ['CHARACTER_CI_FONT'])
        yield path


@pytest.mark.parametrize('topic',['월요일 아침 9시 1분 지각','소란스러운 팀 회의','서버 장애와 느긋한 대리'])
def test_three_synthetic_episodes_are_1080x1920_30s_without_speech(setup,synthetic_clip,topic):
    s=setup.service
    i=prepared(setup,topic=topic)
    job=s.read(i)
    s.submit(i,consent=True,quote_hash=job['quote_hash'])
    setup.video.check=lambda _:ClipStatus('completed','https://example.com/synthetic.mp4')
    def fetch(status,target,cancel):
        shutil.copy2(synthetic_clip,target)
    setup.video.fetch=fetch
    s.check(i,consent=True)
    assert s.read(i)['state']=='clips_review'
    calls=setup.video.calls
    s.composer=compose
    output=s.render(i,reviewed=True)
    info=probe_clip(output)
    assert (info['width'],info['height'],info['duration'],info['video_codec'])==(1080,1920,30.0,'h264')
    review=json.loads((output.parent/'review.json').read_text(encoding='utf8'))
    assert review['human_review']=='NOT VERIFIED' and review['made_for_kids'] is False
    assert review['output']['dialogue'] is False and review['reported_billed_usd'] is None
    assert s.render(i,reviewed=True)==output
    assert setup.video.calls==calls==3 and setup.writer.calls==1
    # Reading the existing job through a new service never triggers another submission.
    restarted=type(s)(s.root.parent,s.sessions,s.keys,writer=setup.writer,video=setup.video,budget=s.budget)
    assert restarted.read(i)['state']=='completed'
    # The topic label is test metadata, not proof of generated mascot or real AI output quality.
    (output.parent/'synthetic-test-topic.txt').write_text(topic,encoding='utf8')


def test_unused_noncommercial_sfx_is_never_added_to_plain_composition(tmp_path,synthetic_clip):
    script=Storyboard.model_validate(story())
    folder=tmp_path/'output';folder.mkdir()
    sfx=tmp_path/'sfx';sfx.mkdir()
    (sfx/'sfx_map.json').write_text(json.dumps({'한숨':{'file':'sigh.wav','license':'unverified',
                                                       'commercial_use_confirmed':False}}),encoding='utf8')
    result=compose(folder,script,[synthetic_clip]*3,sfx_root=sfx)
    assert result['effects']==[] and not result['media']['has_audio']
    assert (folder/'final.mp4').is_file() and not list((folder/'compose').glob('*.ass'))
