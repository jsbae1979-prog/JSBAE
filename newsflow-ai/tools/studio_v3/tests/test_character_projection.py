"""Character display projection only: no application imports, keys, or network."""

import ast
import os
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

SOURCE = Path(
    os.environ.get(
        "NEWSFLOW_CHARACTER_PROJECTION_SOURCE",
        Path(__file__).resolve().parents[3] / "src/newsflow/studio/read_models.py",
    )
)


def projection():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "character_rows")
    # The projection now reads library visibility from the character store's database.
    from sqlalchemy import select

    from newsflow.db import models

    namespace = {"sha256": sha256, "select": select, "m": models}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)  # noqa: S102 - audited pure function only; no module imports
    return namespace["character_rows"]


def synthetic_sessions():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from newsflow.db.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


class CharacterProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="nf-character-projection-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.identifier = "a" * 32
        self.job = {
            "id": self.identifier,
            "topic": "Synthetic workplace story",
            "state": "quoted",
            "script": {
                "title": "Synthetic",
                "scenes": [
                    {"caption": f"Caption {i}", "action": f"Action {i}", "seconds": 10} for i in range(1, 4)
                ],
            },
            "scenes": [
                {
                    "position": i,
                    "state": "not_submitted",
                    "quote_usd": "0.20",
                    "payload": {
                        "prompt": "PRIVATE-PAYLOAD",
                        "image_urls": ["https://private.invalid/reference"],
                    },
                    "idempotency_key": "PRIVATE-IDEMPOTENCY",
                }
                for i in range(1, 4)
            ],
            "quote_total_usd": "0.60",
            "quote_hash": "old-approval",
            "retry_hash": "new-approval",
            "retry": {
                "position": 2,
                "quote_usd": "0.25",
                "at": "2026-10-27T00:00:00+00:00",
                "key_id": "PRIVATE-KEY-ID",
                "original": "PRIVATE-ORIGINAL",
            },
        }

    def read(self):
        character = SimpleNamespace(
            listing=lambda: [{"id": self.identifier}], read=lambda _: self.job, folder=lambda _: self.folder,
            sessions=synthetic_sessions(), composition_retry_available=lambda _: False,
        )
        return projection()(SimpleNamespace(character=character))[0]

    def test_quoted_scenes_keep_story_description_timing_and_official_cost(self):
        result = self.read()
        for i, scene in enumerate(result["scenes"], 1):
            self.assertEqual(
                (scene["caption"], scene["action"], scene["seconds"], scene["cost"]),
                (f"Caption {i}", f"Action {i}", 10, "0.20"),
            )

    def test_sparse_scene_positions_map_to_original_story_not_list_order(self):
        self.job["scenes"] = [self.job["scenes"][2], self.job["scenes"][0]]
        self.assertEqual([x["caption"] for x in self.read()["scenes"]], ["Caption 3", "Caption 1"])

    def test_existing_display_fields_are_preserved(self):
        self.job["scenes"][0].update(caption="Stored caption", seconds=9, cost="0.19")
        scene = self.read()["scenes"][0]
        self.assertEqual((scene["caption"], scene["seconds"], scene["cost"]), ("Stored caption", 9, "0.19"))

    def test_prequote_story_is_not_replaced_by_a_fake_scene(self):
        self.job["state"] = "script_review"
        self.job["scenes"] = []
        self.assertEqual(self.read()["story"], self.job["script"])
        self.assertEqual(self.read()["scenes"], [])

    def test_missing_or_out_of_range_story_does_not_guess_fields(self):
        self.job["script"] = None
        self.assertNotIn("seconds", self.read()["scenes"][0])
        self.job["script"] = {"scenes": []}
        self.assertNotIn("action", self.read()["scenes"][0])

    def test_legacy_text_or_malformed_story_keeps_existing_display_without_guessing(self):
        for stored in ("Saved legacy story", {"scenes": None}, {"scenes": "legacy"}, {"scenes": ["legacy"]}):
            self.job["script"] = stored
            row = self.read()
            self.assertEqual(row["story"], stored)
            self.assertNotIn("seconds", row["scenes"][0])

    def test_projection_never_mutates_saved_job_or_model_snapshot(self):
        self.job["selection"] = {"script_model": "claude-sonnet-4-6", "video_model": "fixed-model"}
        before = deepcopy(self.job)
        self.read()
        self.assertEqual(self.job, before)

    def test_provider_payload_and_credentials_are_not_projected(self):
        import json

        self.job["state"] = "retry_quoted"
        value = json.dumps(self.read())
        for forbidden in (
            "PRIVATE-PAYLOAD",
            "private.invalid",
            "PRIVATE-IDEMPOTENCY",
            "PRIVATE-KEY-ID",
            "PRIVATE-ORIGINAL",
        ):
            self.assertNotIn(forbidden, value)

    def test_retry_quote_only_contains_safe_current_approval_evidence(self):
        self.job["state"] = "retry_quoted"
        self.assertEqual(
            self.read()["retryQuote"], {"position": 2, "quote_usd": "0.25", "at": "2026-10-27T00:00:00+00:00"}
        )

    def test_old_retry_evidence_is_not_presented_as_active_quote(self):
        for status in ("quoted", "generating", "submission_unknown", "completed"):
            self.job["state"] = status
            self.assertNotIn("retryQuote", self.read())

    def test_clip_url_requires_matching_local_file_hash(self):
        scene = self.job["scenes"][0]
        scene["state"] = "downloaded"
        clip = self.folder / "scene-1.mp4"
        clip.write_bytes(b"SERIALIZATION-ONLY-NOT-A-PLAYABLE-MP4")
        scene["sha256"] = sha256(clip.read_bytes()).hexdigest()
        self.assertEqual(self.read()["scenes"][0]["mediaUrl"], f"/character/{self.identifier}/clips/1")
        scene["sha256"] = "wrong"
        self.assertIsNone(self.read()["scenes"][0]["mediaUrl"])
        clip.unlink()
        self.assertIsNone(self.read()["scenes"][0]["mediaUrl"])

    def test_final_preview_requires_completed_state_and_matching_hash(self):
        output = self.folder / "final.mp4"
        output.write_bytes(b"SERIALIZATION-ONLY-NOT-A-PLAYABLE-MP4")
        self.job["output"] = {"sha256": sha256(output.read_bytes()).hexdigest()}
        self.assertIsNone(self.read()["mediaUrl"])
        self.job["state"] = "completed"
        self.assertEqual(self.read()["mediaUrl"], f"/character/{self.identifier}/file")
        self.job["output"]["sha256"] = "wrong"
        self.assertIsNone(self.read()["mediaUrl"])

    def test_empty_listing_returns_no_invented_job(self):
        state = SimpleNamespace(character=SimpleNamespace(listing=list, sessions=synthetic_sessions()))
        self.assertEqual(projection()(state), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

