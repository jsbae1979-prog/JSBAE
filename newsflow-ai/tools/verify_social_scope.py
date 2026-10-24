"""Reproducible scoped regression; Python 3.12/3.14, synthetic accounts only."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TESTS = [
    "test_social_platforms.py",
    "test_social_calendar_analytics.py",
    "test_social_ui.py",
    "test_social_transport.py",
    "test_publishing.py",
    "test_live_publishing.py",
    "test_unified_publishing.py",
    "test_unified_publishing_gui.py",
    "test_instagram_upload.py",
    "test_instagram_live.py",
    "test_instagram_gui.py",
    "test_instagram_connection.py",
    "test_youtube_upload.py",
    "test_youtube_gui.py",
    "test_youtube_connection.py",
    "test_database.py",
    "test_security.py",
    "test_phase1a_security.py",
    "test_scheduler.py",
    "test_scheduler_gui.py",
    "test_ai_video_settings.py",
    "test_oauth.py::test_additive_0005_migration_preserves_phase4a_forensic_records",
    "test_oauth_lifecycle.py::test_additive_migration_0007_preserves_prior_journal_and_account",
    "test_autopilot_state.py::test_migration_0008_is_additive_and_retains_legacy_data",
    "test_intelligence.py",
    "test_single_workspace.py",
    "test_creator_ui.py",
    "test_settings_simplification.py",
    "test_sources_gui.py",
    "test_studio_pages.py",
    "test_settings_streamlined_browser.py",
    "test_creator_scene_browser.py",
    "test_gui.py::test_add_toggle_collect_filters_detail",
    "test_blue_studio_browser.py",
    "test_workflow_card.py",
    "test_dashboard_view.py",
    "test_cloud_workspace_flow.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info[:2] not in {(3, 12), (3, 14)}:
        parser.error("Use Python 3.12 or 3.14.")
    target = args.junitxml.resolve()
    if target.exists():
        parser.error("Choose a new result filename to preserve previous evidence.")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rs",
        *("tests/" + name for name in TESTS),
        "--junitxml=" + str(target),
    ]
    return subprocess.run(command, cwd=Path(__file__).resolve().parents[1], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
