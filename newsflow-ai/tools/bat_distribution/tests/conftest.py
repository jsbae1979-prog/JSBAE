"""Only the BAT contract package and inert distribution modules are imported."""
import sys
from pathlib import Path

project = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project / 'src'))
sys.path.insert(0, str(project / 'tools'))
