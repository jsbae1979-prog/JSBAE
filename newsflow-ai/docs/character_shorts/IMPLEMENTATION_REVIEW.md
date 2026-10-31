# Character shorts automation implementation review

Baseline: 5a2c17d5565dc84d250e92dc8f32295a84e7f122. Specification branch commit: a3a7a856b1c358ffc011ff85afc83b616ed0a838.

## Before implementation

The supplied current-state table is substantially correct. The active studio path already exists; no new parallel product is required. The actual React view is frontend/src/studio/core/CharacterStudio.tsx and its read model is src/newsflow/studio/read_models.py; gui/studio_v3.py serves the shell. Additional five-scene assumptions exist in videoModelSettings.ts, read_models.py and the BAT operation media-route expression.

ImageStudio.save_character stores only an image and label. CharacterWriter removes character/recent_topics from the outgoing payload. Both settings validation and budget reservation select Claude only. Existing prompts can request Korean dialogue/lip sync; composition only concatenates clips. Model catalog files are JSON-compatible YAML with an existing standard-library loader; no YAML/SDK dependency is necessary.

New profile-backed jobs use a versioned episode contract. Old saved studio and legacy jobs retain their previous parsers, media and requests. The original character assets are compatibility data, never hardcoded into new prompts or automatically registered. No DB migration is needed for user-profile JSON state.

## Conflicts resolved

- Preserve the explicit user policy of per-execution/episode budgets; do not restore a global cumulative or daily execution block.
- AGENTS.md forbids automatic submit replay (including 408/429). Retry only a known failed scene after a new explicit quote/approval; unknown outcomes remain blocked. A timeout does not prove a refund or safe replay.
- New episode editing follows this latest specification (captions, original synthesized SFX, speed/hold/audio crossfade). Old jobs retain their prior no-added-caption/audio composition behavior.
- Supporting cast references remain text-only in v1; multiple registered protagonists in one episode are excluded.

## Implementation checklist findings

- Existing API transports and budget/key stores can be reused with a structured Claude/OpenAI adapter. Image input is separate from text script input.
- Official O3 reference API documents first_frame_url; Kling 3.0 uses image_url. Continuation mapping belongs in the catalog. No live provider calls are required for development.
- Official estimates remain distinct from actual billing; website credits are not API dollars. Existing authenticated estimate adapter is reused, only Fake adapters run here.
- Existing request polling is sufficient; no webhook/server exposure is added.
- NotoSansKR.ttf and OFL.txt are already present. Comedy SFX will use code-owned synthetic recipes with provenance, not downloaded music.
- Tests use existing Windows Python 3.12/3.14 and isolated FFmpeg binaries, never the running installation or its data.

## Official references reviewed (2026-10-30)

- https://open.higgsfield.ai/models/kling-video/o3/image-reference/api-reference
- https://open.higgsfield.ai/models/kling-video/v3.0/std/image-to-video/api-reference
- https://open.higgsfield.ai/quick-start
- https://developers.openai.com/api/docs/guides/images-vision

The original current checkout had unrelated uncommitted changes. The user explicitly approved continuing in the existing development checkout; no worktree was created. Its pre-existing untracked validation/ directory is preserved.
