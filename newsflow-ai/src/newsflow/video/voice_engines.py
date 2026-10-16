"""One voice selector shared by manual video rendering; external voices require explicit consent."""

from .tts import OfflineTTS, TTSError, WindowsTTS


def provider_for(voice, sessions, root, *, external_consent=False):
    if voice == "offline-silence":
        return OfflineTTS()
    if voice.startswith("supertonic:"):
        from .supertonic_tts import SupertonicTTS

        return SupertonicTTS()
    if voice == "elevenlabs":
        from .elevenlabs_tts import ElevenLabsTTS, settings

        if not external_consent:
            raise TTSError("ElevenLabs는 이번 제작의 외부 전송·크레딧 사용 동의가 필요합니다.")
        return ElevenLabsTTS(root, settings(sessions), consent=True)
    return WindowsTTS()


def provider_name(voice):
    if voice == "offline-silence":
        return "offline"
    if voice.startswith("supertonic:"):
        return "supertonic"
    return "elevenlabs" if voice == "elevenlabs" else "windows"
