"""Legacy composition uses only clip pixels/audio; commands are fully local fakes."""
from pathlib import Path
from array import array
import subprocess

import pytest

import newsflow.character.compose as module
from newsflow.character.schema import CharacterError, Storyboard
from test_character_shorts import story
from newsflow.video.tts import local_process_env


def fake_media(tmp_path, monkeypatch, audio, *, final_audio=None, source_seconds=10):
    clips=[]
    for index in range(3):
        clip=tmp_path/f'original-{index}.mp4'
        clip.write_bytes(f'original-{index}'.encode())
        clips.append(clip)
    original=[clip.read_bytes() for clip in clips]
    commands=[]
    def probe(path, *_):
        if Path(path).name=='final.mp4':
            return {'width':1080,'height':1920,'video_codec':'h264','duration':30,
                    'has_audio':any(audio) if final_audio is None else final_audio}
        return {'duration':source_seconds,'has_audio':audio[clips.index(Path(path))]}
    def run(args, cwd):
        commands.append(list(args))
        if str(args[-1]).endswith('.mp4'):
            Path(args[-1]).write_bytes(b'synthetic-output')
    monkeypatch.setattr(module,'probe_clip',probe)
    monkeypatch.setattr(module,'run',run)
    monkeypatch.setattr(module.FFmpegAdapter,'executable',lambda *_:Path('fake-ffmpeg'))
    def no_text(*_args,**_kwargs):raise AssertionError('Text/font work is forbidden')
    monkeypatch.setattr('newsflow.video.engine.write_ass',no_text)
    monkeypatch.setattr('PIL.ImageFont.truetype',no_text)
    return clips,original,commands


@pytest.mark.parametrize('audio',[(False,False,False),(True,True,True),(False,True,False)])
def test_legacy_compose_adds_no_text_or_audio_and_preserves_source_audio(tmp_path,monkeypatch,audio):
    clips,original,commands=fake_media(tmp_path,monkeypatch,audio)
    folder=tmp_path/'result';folder.mkdir()
    class UnreadableSfx:
        def __truediv__(self,_):raise AssertionError('SFX library must never be read')
    result=module.compose(folder,Storyboard.model_validate(story()),clips,sfx_root=UnreadableSfx())
    assert [clip.read_bytes() for clip in clips]==original
    assert not list(folder.rglob('*.ass')) and not (folder/'compose/fonts').exists()
    final=next(cmd for cmd in commands if cmd[-1]==str((folder/'final.mp4').resolve()))
    graph=final[final.index('-filter_complex')+1]
    assert graph.count('xfade=')==2 and '[x2]null[v]' in graph
    for token in ('ass=','subtitles=','drawtext=','anullsrc','fontsdir'):
        assert token not in graph
    assert final.count('-i')==len(clips) and final[final.index('-t')+1]=='30'
    assert '-an' not in final
    for index,has_audio in enumerate(audio):
        normalization=next(cmd for cmd in commands if cmd[-1].endswith(f'scene-{index}.mp4'))
        assert normalization.count('-i')==1 and '-an' not in normalization
        assert ('0:a:0' in normalization)==has_audio
        assert (f'[{index}:a]' in graph)==has_audio
        if has_audio:assert f'adelay={index*10000}|{index*10000}' in graph
    assert ('[a]' in final)==any(audio)
    assert result['media']['has_audio']==any(audio) and result['effects']==[]
    assert result['captions_added'] is False and result['voice_added'] is False
    assert result['ai_label_burned_in'] is False
    assert result['audio_source']==('model_output' if any(audio) else 'none')


def test_legacy_compose_rejects_output_that_drops_original_audio(tmp_path,monkeypatch):
    clips,_,_=fake_media(tmp_path,monkeypatch,(False,True,False),final_audio=False)
    folder=tmp_path/'result';folder.mkdir()
    with pytest.raises(CharacterError):module.compose(folder,Storyboard.model_validate(story()),clips)


def test_legacy_compose_still_blocks_too_short_clips_before_encoding(tmp_path,monkeypatch):
    clips,original,commands=fake_media(tmp_path,monkeypatch,(False,False,False),source_seconds=6)
    folder=tmp_path/'result';folder.mkdir()
    with pytest.raises(CharacterError):module.compose(folder,Storyboard.model_validate(story()),clips)
    assert not commands and [clip.read_bytes() for clip in clips]==original


def test_real_legacy_mixed_audio_stays_in_its_original_scene(tmp_path):
    binary=module.FFmpegAdapter.executable('ffmpeg',None)
    probe=module.FFmpegAdapter.executable('ffprobe',None)
    clips=[]
    for sound in (False,True):
        clip=tmp_path/('tone.mp4' if sound else 'silent.mp4')
        args=[str(binary),'-nostdin','-n','-v','error','-f','lavfi','-i','color=c=blue:s=144x256:r=30:d=10']
        if sound:args+=['-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=10','-c:a','aac']
        args+=['-t','10','-c:v','libx264','-preset','ultrafast','-threads','1',str(clip)]
        subprocess.run(args,check=True,capture_output=True,timeout=60,env=local_process_env())
        clips.append(clip)
    originals=[clip.read_bytes() for clip in clips]
    folder=tmp_path/'result';folder.mkdir()
    result=module.compose(folder,Storyboard.model_validate(story()),[clips[0],clips[1],clips[0]],
                          ffmpeg=binary,ffprobe=probe)
    assert result['media']['has_audio'] and result['media']['duration']==30
    assert [clip.read_bytes() for clip in clips]==originals
    levels=[]
    for seconds in (5,15,25):
        decoded=subprocess.run([str(binary),'-nostdin','-v','error','-i',str(folder/'final.mp4'),
                                '-ss',str(seconds),'-t','1','-vn','-f','s16le','-ac','1','-ar','8000','-'],
                               check=True,capture_output=True,timeout=60,env=local_process_env())
        samples=array('h');samples.frombytes(decoded.stdout)
        assert samples
        levels.append(sum(abs(value) for value in samples)/len(samples))
    assert levels[0]<2 and levels[1]>100 and levels[2]<2
