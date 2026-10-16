from pathlib import Path
from types import SimpleNamespace

import pytest

from newsflow.video.tts import SpeechSettings, WindowsTTS
from newsflow.video.windows_sapi import culture, speak


def test_culture_preserves_korean_and_unknown():
    assert culture('412') == 'ko-KR'
    assert culture('invalid;409') == 'en-US'
    assert culture('ffff') == ''


def test_native_speech_forces_plain_text_and_adds_pcm_pauses(tmp_path):
    import wave

    class Stream:
        Format = SimpleNamespace(Type=None)

        def Open(self, path, mode, asynchronous):
            assert mode == 3 and asynchronous is False
            self.path = path

        def Close(self):
            with wave.open(self.path, 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b'\x10\x10' * 1600)

    token = SimpleNamespace(GetAttribute=lambda key: 'Microsoft Heami Desktop')
    speaker = SimpleNamespace(GetVoices=lambda: SimpleNamespace(Count=1, Item=lambda index: token))
    calls = []
    speaker.Speak = lambda text, flags: calls.append((text, flags))
    target = (tmp_path / 'speech.wav').resolve()
    spec = WindowsTTS.spec('<audio src="https://example.com"/>. 둘째 문장.',
                           'Microsoft Heami Desktop', target, SpeechSettings(2, 250))
    # Explicit sentences avoid punctuation splitting being the subject of this test.
    spec['sentences'] = ['<audio src="https://example.com"/>', '둘째 문장.']
    speak(speaker, lambda progid: Stream(), spec)
    assert calls == [(text, 16) for text in spec['sentences']]
    assert speaker.Rate == 2
    with wave.open(str(target)) as audio:
        frames = audio.readframes(audio.getnframes())
        assert audio.getnframes() == 1600 * 2 + 4000
    assert frames[3200:11200] == b'\0\0' * 4000
    assert not list(tmp_path.glob('sapi-*'))
    with pytest.raises(ValueError):
        speak(speaker, lambda progid: Stream(), spec)  # never overwrite an existing file


@pytest.mark.parametrize(('key', 'value'), [('rate', 6), ('pause_ms', 1001), ('sentences', [])])
def test_reject_invalid_native_spec_before_com(key, value, tmp_path):
    spec = WindowsTTS.spec('한국어 문장.', 'voice', (tmp_path / 'a.wav').resolve(), SpeechSettings())
    spec[key] = value
    with pytest.raises(ValueError):
        speak(None, None, spec)


def test_native_worker_has_no_powershell_or_policy_fallback():
    from newsflow.video import windows_sapi

    source = Path(windows_sapi.__file__).read_text(encoding='utf-8')
    assert "speaker.Speak(sentence, 16)" in source
    assert "stream.Format.Type = 18" in source
    for forbidden in ('subprocess', 'ExecutionPolicy', 'Invoke-Expression', 'eval(', 'exec('):
        assert forbidden not in source
