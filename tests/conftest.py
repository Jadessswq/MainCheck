"""pytest configuration: добавляет Сервер/ в sys.path, чтобы работали `from shared...`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "Сервер"
# Сначала Сервер/ — именно там лежит пакет shared/
sys.path.insert(0, str(SERVER))
