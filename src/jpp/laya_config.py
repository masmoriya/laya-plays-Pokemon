"""Machine-local Laya setup, with explicit environment overrides."""

import json
import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config" / "laya.local.json"


def setting(name, default=None):
    value = os.environ.get(f"LAYA_{name.upper()}")
    if value:
        return value
    if CONFIG.is_file():
        settings = json.loads(CONFIG.read_text())
        value = settings.get(name)
        if value:
            return str(value)
    return default
