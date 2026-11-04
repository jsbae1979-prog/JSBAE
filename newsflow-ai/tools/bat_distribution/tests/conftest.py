"""Only the BAT contract package and inert distribution modules are imported."""
import sys
from pathlib import Path

project = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project / 'src'))
sys.path.insert(0, str(project / 'tools'))

# These contracts reuse the same synthetic helpers as the main test suite.
sys.path.insert(0, str(project / 'tests'))

import pytest


@pytest.fixture(autouse=True)
def legacy_character_story_format(request, monkeypatch):
    """Existing BAT fixtures describe pre-format jobs, just like tests/conftest.py.

    New-format tests must opt in explicitly; product defaults are never changed.
    """
    if request.node.get_closest_marker('story_format'):
        return
    from newsflow.character import episode_service
    monkeypatch.setattr(episode_service, 'load_story_format', lambda: None)
