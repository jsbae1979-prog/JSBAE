# Character continuity: actual frame review and official guidance — 2026-11-03

Status: implementation and offline checks PASS; newly generated artistic quality NOT VERIFIED. No paid regeneration or automatic replay was performed. Existing user video, script, quotations and reservations remain intact.

## What was actually inspected

Read the stored five-clip job and its saved scene prompts. Decoded start / midpoint / near-end images from each clip (15 frames) to a local contact sheet. Original clip SHA-256 values were checked before and after extraction. The user media/contact sheet and private identifiers are kept locally, not committed. This is visual sample review, not an audio listening test or a claim to have assessed every frame.

Observed continuity defects:

- Scene 1 ends on the rainy window with the character partly out of frame; scene 2 starts with the character standing in a different office composition and additional people.
- Scene 3 introduces moving papers/background people and a changed viewpoint. A hand-held orange appears in addition to the character's head orange.
- Scene 3 → 4 is the strongest connection: this is the only stored boundary marked `continue` and supplied a predecessor frame. Object duplication is still visible.
- Scene 5 resets the pose, introduces a phone and changes the outside/light appearance. The motion connecting the previous seated reaction to this pose is absent.
- The saved story's other boundaries were independent cuts. Concatenating already inconsistent clips cannot repair these visual transitions. FFmpeg itself is not the cause of the observed changed poses/objects/background.

## Official research and implementation decision

Accessed 2026-11-03:

- [Higgsfield — How do I use Kling?](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-kling): plan connected narrative beats, feed the prior clip's final frame into the next, and keep identities/objects consistent.
- [Higgsfield — Kling prompt guide](https://higgsfield.ai/blog/Kling-3.0-is-on-Higgsfield-User-Guide-AI-Video-Generation): one main action and one camera move per shot; specify references, light, audio and what must remain consistent. Avoid packing conflicting events into a shot.

These are creative workflow recommendations, not proof that every website option is present in the selected REST endpoint. No new model, price, duration, Elements parameter or unverified API feature was introduced. Existing catalog continuation mappings are reused.

## Minimal versioned change

Only eligible newly created story jobs freeze `single_incident_v2`. Existing unversioned/v1 jobs retain their instructions, prompts, review/quote hashes and frame handling.

1. Story planning prioritizes one continuous incident, one protagonist, visible changes in body pose and movable objects, and consistent location/weather/light. One main action and a gradual camera move per beat. No flashbacks, offscreen resets or teleports. A loop ending must be reached by visible motion. The hook remains immediate.
2. The new single-protagonist writing payload omits optional supporting-cast context; the stored character profile is unchanged. Conflicting quick-cut/energetic-camera/supporting-cast directions are removed only for this new policy.
3. All subsequent video scenes depend on the immediately preceding downloaded clip. Prompt instructions distinguish identity/style from current observed frame state. A conflicting planned action must not reset visible state. No dialogue, voices, music or generated on-screen text; native environmental effects follow the selected sound option.
4. Decode/reverse only the last second and select its first frame, giving the true last decoded frame. Legacy near-end behavior remains frozen. Existing dependency hashes, quote checks and unknown-result stop behavior remain intact.
5. Full appearance/style/action/camera/sound fields still fit the existing 2,000-character video prompt limit at their allowed maxima. Optional duplicated *prior planned action* context is omitted only when it would overflow; user fields and the mandatory predecessor-frame rule are never truncated. No automatic paid rewrite is added.

Changed code:

- `src/newsflow/character/scene_continuity.py`
- `src/newsflow/character/episode_story.py`
- `src/newsflow/character/episode_service.py`

Tests: new `tests/test_continuity_research.py`; update new-job policy assertions in `tests/test_single_incident_captions.py` and `tests/test_character_story_format.py`. Existing legacy assertions remain.

## Focused validation

Windows 11 / existing Python 3.14.7 / existing FFmpeg; Fake providers and isolated temporary profiles, no production credentials or external generation. Effective command (the wrapper also isolates environment/temp paths and writes JUnit):

```text
python -m pytest -q -rs tests/test_continuity_research.py tests/test_single_incident_captions.py tests/test_character_story_format.py tests/test_character_direct_continuity.py tests/test_character_episode_automation.py tests/test_character_episode_recovery.py tests/test_character_episode_regeneration.py tests/test_episode_saved_candidate.py
```

Final: **75 PASS / 0 FAIL / 0 ERROR / 0 SKIP**, including 10 new cases. One existing Starlette/httpx deprecation warning; no runtime test error. Initial focused run was 35 PASS / 1 FAIL: an old new-job assertion expected the pre-versioned writer instruction. It was changed to assert the stored new policy and its matching instruction, keeping duration constraints and the end-to-end MP4 check; no assertion was dropped or skipped.

Coverage: 15/20/30/35/60-second plan duration/count preservation; two profiles stay distinct; maximum valid prompt fields; sound-on/off; actual-final-frame color sentinel; parent clip/frame hash linkage; unchanged reference identity and remaining payload; one paid-submit equivalent per ready scene; failed/unknown parent blocks children without replay; Fake complete MP4 plus existing free recovery/regeneration tests. Existing direct-video O3/K3 mapping checks pass. Real AI compatibility and visual quality are not established by Fake tests.

Frontend, API route lists and schemas are unchanged. Reuse prior accepted build/route results; no full unrelated regression, paid generation, news collection or SNS posting.

## Operating application and limits

Exact three-file operating application is prepared, with no overlays and no active generation at preparation. Operating evidence will be appended after the normal Stop/Start and preservation comparison. No existing job is rewritten to v2. To see the new visual behavior, a newly created, explicitly approved generation is required later; an existing MP4 cannot acquire new motion through a code update.

The final frame improves geometric continuity but cannot guarantee physical correctness, emotional pacing, identical character identity or popularity. Review the first scene and each transition before final composition; a bad parent frame can propagate its defects. No claim of improved actual generated output is made without that user-approved visual review.
