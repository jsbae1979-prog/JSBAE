# Original comedy sound effects

The eight effects in `config/sfx_map.yaml` are generated locally by
`newsflow.character.editing.synthesize_sfx`. They use mathematical oscillators
and deterministic pseudo-noise. No recording, voice, music, library sample,
online asset or provider API is used. These short non-melodic effects are not
recordings of the names used as their UI labels.

The original oscillator recipes and the PCM sound effects produced from them
are dedicated to the public domain under CC0 1.0 Universal
(https://creativecommons.org/publicdomain/zero/1.0/). This dedication does not
apply to FFmpeg, fonts, third-party material, user media or generated provider
clips. Their separate licenses and rights remain unchanged.

Generation is deterministic (48 kHz signed 16-bit mono PCM). Each composition
records the SHA-256 of the generated effects in its edit evidence. The map's
keys are the only permitted SFX identifiers; user input cannot supply an audio
file path or executable filter expression. The original map is versioned with
the source so its exact recipes can be reproduced.

NotoSansKR.ttf is reused without modification. Its existing SIL Open Font
License 1.1 and copyright notice are retained in character/assets/OFL.txt.
