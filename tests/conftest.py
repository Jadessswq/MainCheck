"""pytest configuration: добавляет корень репо в sys.path, чтобы работали `from shared...`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
