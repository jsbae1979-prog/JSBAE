"""Synthetic command contracts: no operating media, provider or voice calls."""
from pathlib import Path
import pytest
import newsflow.character.compose_studio as module
from newsflow.character.kling import DEFAULTS
from newsflow.character.studio_story import StudioStoryboard
from test_character_kling_studio import story


@pytest.mark.parametrize('sound', ['on', 'off'])
@pytest.mark.parametrize('count', [1, 5])
def test_reviewed_clips_join_without_text_or_added_voice(tmp_path, monkeypatch, sound, count):
    folder = tmp_path / 'result'
    folder.mkdir()
    source = tmp_path / 'clip.mp4'
    source.write_bytes(b'synthetic input bytes')
    commands = []
    monkeypatch.setattr(module.FFmpegAdapter, 'executable', lambda *_: Path('ffmpeg'))

    def probe(path, _=None):
        return {'duration': 15 if Path(path).name == 'final.mp4' or count == 1 else 3,
                'has_audio': sound == 'on', 'width': 720, 'height': 1280}

    def run(args, cwd):
        commands.append(args)
        if args[-1] != '-':
            Path(args[-1]).write_bytes(b'synthetic output bytes')

    monkeypatch.setattr(module, 'probe_clip', probe)
    monkeypatch.setattr(module, 'run', run)
    settings = {**DEFAULTS, 'duration': 15, 'clip_seconds': 3,
                'output_quality': '720p', 'sound': sound}
    result = module.compose_studio(folder, StudioStoryboard.model_validate(story(15, sound)),
                                   [source] * count, settings=settings)
    assert result['captions_added'] is False and result['voice_added'] is False
    assert result['ai_label_burned_in'] is False
    assert result['audio_source'] == ('model_output' if sound == 'on' else 'none')
    assert source.read_bytes() == b'synthetic input bytes'
    assert not list(folder.rglob('*.ass')) and not (folder / 'compose/fonts').exists()
    wire = ' '.join(str(value) for command in commands for value in command)
    assert all(x not in wire for x in ('ass=', 'subtitles=', 'drawtext=', 'anullsrc', '.wav', 'tts'))
    output_command = next(command for command in commands if command[-1] == str((folder/'final.mp4').resolve()))
    assert output_command[output_command.index('-c:v')+1] == 'copy'
    assert '-vf' not in output_command and '-filter_complex' not in output_command
    if sound == 'on':
        assert output_command[output_command.index('-c:a')+1] == 'copy'
        assert '0:a:0' in output_command and '-an' not in output_command
    else:
        assert '-an' in output_command and '-c:a' not in output_command
