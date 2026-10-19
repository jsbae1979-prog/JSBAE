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
        expected = (elevenlabs_config or {}).get("credential_fingerprint")
        keys = None
        if expected:
            import hashlib

            from newsflow.intelligence.credentials import CredentialError

            from .elevenlabs_tts import ElevenLabsKeys

            store = ElevenLabsKeys(root)
            class BoundKeys:
                def key(self):
                    if not settings(sessions)["enabled"]:
                        raise TTSError("ElevenLabs 사용 설정이 해제되어 추가 음성 요청을 중단했습니다.")
                    try:
                        value = store.key()
                    except CredentialError:
                        raise TTSError("이 작업의 음성 계정 키를 읽을 수 없습니다.") from None
                    if hashlib.sha256(value.encode()).hexdigest() != expected:
                        raise TTSError("ElevenLabs 계정 키가 바뀌었습니다. 이전 작업을 새 계정으로 자동 전송하지 않습니다. 새 제작 동의가 필요합니다.")
                    return value
            keys = BoundKeys()
            keys.key()
        return ElevenLabsTTS(root, elevenlabs_config or current, consent=True, **({"keys": keys} if keys else {}))
    return WindowsTTS()


def provider_name(voice):
    if voice == "offline-silence":
        return "offline"
    if voice.startswith("supertonic:"):
        return "supertonic"
    return "elevenlabs" if voice == "elevenlabs" else "windows"
