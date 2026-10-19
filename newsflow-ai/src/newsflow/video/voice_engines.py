"""One voice selector shared by manual video rendering; external voices require explicit consent."""

from .tts import OfflineTTS, TTSError, WindowsTTS


def provider_for(voice, sessions, root, *, external_consent=False, elevenlabs_config=None):
    if voice == "offline-silence":
        return OfflineTTS()
    if voice.startswith("supertonic:"):
        from .supertonic_tts import SupertonicTTS

        return SupertonicTTS()
    if voice == "elevenlabs":
        from .elevenlabs_tts import ElevenLabsTTS, settings

        if not external_consent:
            raise TTSError("ElevenLabs는 이번 제작의 외부 전송·크레딧 사용 동의가 필요합니다.")
        current = settings(sessions)
        if not current["enabled"]:
            raise TTSError("ElevenLabs 사용 설정이 해제되었습니다.")
        return ElevenLabsTTS(root, elevenlabs_config or current, consent=True)
    return WindowsTTS()


def provider_name(voice):
    if voice == "offline-silence":
        return "offline"
    if voice.startswith("supertonic:"):
        return "supertonic"
    return "elevenlabs" if voice == "elevenlabs" else "windows"
