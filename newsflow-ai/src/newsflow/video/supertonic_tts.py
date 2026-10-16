"""Optional free local ONNX voice; no API or automatic asset downloads."""

import importlib.util
import threading
import wave
from functools import lru_cache

from .supertonic_assets import model_dir, verify_models
from .tts import SpeechSettings, TTSError, WindowsTTS, wav_has_signal

VOICES = [f"supertonic:{gender}{index}" for gender in ("F", "M") for index in range(1, 6)]
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def engine():
    import onnxruntime
    from supertonic import TTS

    root = model_dir()
    verify_models(root)
    onnxruntime.disable_telemetry_events()
    return TTS(model="supertonic-3", model_dir=root, auto_download=False,
               intra_op_num_threads=4, inter_op_num_threads=1)


class SupertonicTTS(WindowsTTS):
    # Reuse measured sentence joining and preview; no Windows COM method is invoked.
    def voices(self):
        ready = (model_dir() / "onnx/vocoder.onnx").is_file() and importlib.util.find_spec("supertonic") is not None
        return list(VOICES) if ready else []

    def _speak(self, text, target, voice, speech: SpeechSettings):
        if voice not in VOICES or not 0 < len(text) <= 400:
            raise TTSError("Supertonic 음성 또는 문장 길이를 확인하세요.")
        try:
            import numpy as np

            with _LOCK:
                tts = engine()
                # User speed only; the audio-fit renderer never accelerates speech to fit.
                samples, _estimated = tts.synthesize(
                    text=text, lang="ko", voice_style=tts.get_voice_style(voice.split(":")[1]),
                    total_steps=8, speed=1.0 + speech.rate * .03, verbose=False,
                )
                samples = np.asarray(samples).reshape(-1)
                if not 0 < samples.size <= tts.sample_rate * 120 or not np.isfinite(samples).all():
                    raise TTSError("Supertonic 음성 샘플 검증 실패")
                peak = float(np.max(np.abs(samples)))
                samples = samples * min(1.0, .97 / peak) if peak > 0 else samples
                pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2")
                with wave.open(str(target), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(tts.sample_rate)
                    output.writeframes(pcm.tobytes())
            if not wav_has_signal(target):
                raise TTSError("Supertonic 음성 신호가 없습니다.")
        except TTSError:
            raise
        except Exception:  # noqa: BLE001 - never expose model/runtime errors or input text
            raise TTSError("Supertonic 로컬 실행 실패. 선택적 의존성과 고정 모델을 확인하세요.") from None
