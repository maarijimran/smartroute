"""Makes `app` importable when a script is run as `python scripts/<name>.py` from backend/."""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def data_path(*parts: str) -> str:
    path = os.path.join(BACKEND_DIR, "data", *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path
