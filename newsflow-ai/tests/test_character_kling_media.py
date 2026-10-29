"""Only local FFmpeg synthetic clips; no application, operating media or vendor API."""
import subprocess
import pytest
from newsflow.character.compose_studio import compose_studio
from newsflow.character.kling import DEFAULTS,dimensions
from newsflow.character.studio_story import StudioStoryboard
from newsflow.video.engine import FFmpegAdapter
from newsflow.video.tts import local_process_env
from newsflow.character.schema import CharacterError
from test_character_kling_studio import story

@pytest.mark.parametrize('sound,ratio',[('on','9:16'),('off','9:16')])
def test_selected_ratio_output_and_audio_survive_real_local_composition(tmp_path,sound,ratio):
    binary=str(FFmpegAdapter.executable('ffmpeg',None))
    clip=tmp_path/'synthetic.mp4'
    args=[binary,'-nostdin','-n','-v','error','-f','lavfi','-i','color=c=blue:s=144x256:r=30']
    if sound=='on':args+=['-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-c:a','aac']
    else:args+=['-an']
    args+=['-t','6','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(clip)]
    subprocess.run(args,check=True,capture_output=True,timeout=60,env=local_process_env())
    folder=tmp_path/'result';folder.mkdir()
    settings={**DEFAULTS,'duration':30,'clip_seconds':6,'output_quality':'720p','sound':sound,'aspect_ratio':ratio}
    result=compose_studio(folder,StudioStoryboard.model_validate(story(30,sound)),[clip]*5,settings=settings)
    info=result['media']
    assert (info['width'],info['height'])==dimensions(settings)
    assert info['has_audio']==(sound=='on') and abs(info['duration']-30)<.1
    assert result['human_quality']=='NOT VERIFIED'
    assert result['captions_added'] is False and result['voice_added'] is False
    assert result['ai_label_burned_in'] is False and not list(folder.rglob('*.ass'))

def test_voice_request_is_not_silently_replaced_with_silence(tmp_path,monkeypatch):
    import newsflow.character.compose_studio as module
    monkeypatch.setattr(module,'probe_clip',lambda *a:{'duration':6,'has_audio':False})
    folder=tmp_path/'result';folder.mkdir()
    with pytest.raises(CharacterError):
        compose_studio(folder,StudioStoryboard.model_validate(story(30,'on')),[tmp_path/'fake.mp4']*5,
                       settings={**DEFAULTS,'duration':30,'clip_seconds':6,'sound':'on'})
    assert not (folder/'final.mp4').exists()
