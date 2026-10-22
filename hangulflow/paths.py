"""Filesystem locations used by HangulFlow.

User data (database, settings, logs) lives in %LOCALAPPDATA%\\HangulFlow.
Set the HANGULFLOW_DATA_DIR environment variable to use a different folder
(handy for testing with a throwaway database).
"""

import os
from pathlib import Path

APP_NAME = "HangulFlow"

_PACKAGE_DIR = Path(__file__).resolve().parent


def data_dir() -> Path:
    override = os.environ.get("HANGULFLOW_DATA_DIR")
    if override:
        base = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(local) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    return data_dir() / "hangulflow.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def lock_path() -> Path:
    return data_dir() / "hangulflow.lock"


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_vocabulary_path() -> Path:
    return _PACKAGE_DIR / "resources" / "seed_vocabulary.json"


def fonts_dir() -> Path:
    return _PACKAGE_DIR / "resources" / "fonts"
