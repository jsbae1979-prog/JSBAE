"""Bounded local SAPI COM worker; no PowerShell, policy changes or shell text."""
from __future__ import annotations

import json
import locale
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from .speech_audio import prepare_pcm
from .speech_text import MAX_SPOKEN_CHARS


def culture(language: str) -> str:
    for item in language.split(';'):
        try:
            name = locale.windows_locale.get(int(item, 16))
        except ValueError:
            continue
        if name:
            return name.replace('_', '-')
    return ''


def registry_voices() -> list[dict[str, str]]:
    import winreg

    result = []
    for hive, key, path, view in (
        ('sapi', winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Speech\Voices\Tokens', winreg.KEY_WOW64_64KEY),
        ('sapi_wow', winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Speech\Voices\Tokens', winreg.KEY_WOW64_32KEY),
        ('sapi_user', winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\Speech\Voices\Tokens', 0),
        ('onecore', winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens', winreg.KEY_WOW64_64KEY),
    ):
        try:
            with winreg.OpenKey(key, path, 0, winreg.KEY_READ | view) as parent:
                for index in range(min(winreg.QueryInfoKey(parent)[0], 200 - len(result))):
                    token = winreg.EnumKey(parent, index)
                    with winreg.OpenKey(parent, token) as entry:
                        def value(handle, name):
                            try:
                                return str(winreg.QueryValueEx(handle, name)[0])[:200]
                            except OSError:
                                return ''
                        name = value(entry, '')
                        language = gender = ''
                        try:
                            with winreg.OpenKey(entry, 'Attributes') as attributes:
                                language, gender = value(attributes, 'Language'), value(attributes, 'Gender')
                        except OSError:
                            pass
                    result.append({'hive': hive, 'token': token, 'name': name, 'language': language, 'gender': gender})
        except OSError:
            continue
    return result


def speak(speaker, dispatch, spec: dict) -> list[dict]:
    voice, target = spec['voice'], Path(spec['target'])
    rate, pause = spec.get('rate', 0), spec.get('pause_ms', 0)
    sentences = spec['sentences']
    if (not target.is_absolute() or target.exists() or not target.parent.is_dir()
            or type(rate) is not int or not -5 <= rate <= 5
            or type(pause) is not int or not 0 <= pause <= 1000
            or not isinstance(sentences, list) or not sentences
            or any(not isinstance(s, str) or not s for s in sentences)
            or sum(map(len, sentences)) > MAX_SPOKEN_CHARS):
        raise ValueError('invalid speech specification')
    tokens = speaker.GetVoices()
    selected = next((tokens.Item(i) for i in range(tokens.Count)
                     if tokens.Item(i).GetAttribute('Name') == voice), None)
    if selected is None:
        raise ValueError('voice unavailable')
    speaker.Voice, speaker.Rate = selected, rate
    pcm = bytearray()
    cues = []
    with TemporaryDirectory(prefix='sapi-', dir=target.parent) as directory:
        for index, sentence in enumerate(sentences):
            part = Path(directory) / f'{index}.wav'
            stream = dispatch('SAPI.SpFileStream')
            stream.Format.Type = 18  # SAFT16kHz16BitMono (Microsoft SAPI enum).
            stream.Open(str(part), 3, False)  # SSFMCreateForWrite; owned temporary file.
            try:
                speaker.AudioOutputStream = stream
                speaker.Speak(sentence, 16)  # SVSFIsNotXML: user text is never XML/SSML.
            finally:
                stream.Close()
            with wave.open(str(part), 'rb') as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                    raise ValueError('unexpected PCM format')
                part_pcm = prepare_pcm(audio.readframes(16000 * 61))
                start = len(pcm) / 32000
                pcm.extend(part_pcm)
                cues.append({'start': start, 'end': len(pcm) / 32000})
            if index < len(sentences) - 1:
                pcm.extend(b'\0\0' * (16000 * pause // 1000))
            if len(pcm) > 16000 * 2 * 60:
                raise ValueError('speech exceeds duration limit')
    with target.open('xb') as raw, wave.open(raw, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    return cues


def main() -> int:
    try:
        if sys.platform != 'win32':
            raise ValueError('Windows required')
        args = sys.argv[1:]
        if args == ['-RegistryVoices']:
            result = registry_voices()
        else:
            import pythoncom
            from win32com.client.dynamic import Dispatch

            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            speaker = tokens = None
            failed = False
            try:
                speaker = Dispatch('SAPI.SpVoice')
                tokens = speaker.GetVoices()
                if args in (['-ListVoices'], ['-VoiceDetails']):
                    details = [{'name': tokens.Item(i).GetAttribute('Name'),
                                'culture': culture(tokens.Item(i).GetAttribute('Language'))}
                               for i in range(min(tokens.Count, 100))]
                    result = [entry['name'] for entry in details] if args == ['-ListVoices'] else details
                elif len(args) == 2 and args[0] == '-Spec':
                    with Path(args[1]).open("rb") as source:
                        raw = source.read(32769)
                    if len(raw) > 32768:
                        raise ValueError('speech specification too large')
                    result = speak(speaker, Dispatch, json.loads(raw))
                else:
                    raise ValueError('unsupported operation')
            except Exception:  # noqa: BLE001 -- release exception-held COM objects before uninitializing
                failed = True
            finally:
                tokens = speaker = None
                pythoncom.CoUninitialize()
            if failed:
                raise ValueError("SAPI operation failed")
        if result is not None:
            payload = json.dumps(result, ensure_ascii=False).encode('utf-8')
            if len(payload) > 32768:
                raise ValueError('voice inventory too large')
            sys.stdout.buffer.write(payload)
        return 0
    except Exception:  # noqa: BLE001 -- never expose text, paths or COM error internals
        sys.stderr.write('Windows native SAPI failed.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
