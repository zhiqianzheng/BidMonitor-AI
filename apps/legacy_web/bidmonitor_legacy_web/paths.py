"""Paths for the historical Web service; existing data stays in place."""
import os
from pathlib import Path
import sys


def project_root():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]


def runtime_home():
    override = os.environ.get("BIDMONITOR_LEGACY_HOME")
    if override:
        return Path(override).expanduser().resolve()
    root = project_root()
    if (root / "server/server_config.json").is_file() or (root / "data/bids.db").is_file():
        return root
    return root / "runtime/legacy_web"


def database_path():
    override = os.environ.get("BIDMONITOR_LEGACY_DB")
    return Path(override).expanduser().resolve() if override else runtime_home() / "data/bids.db"


def config_file():
    home = runtime_home()
    if not os.environ.get("BIDMONITOR_LEGACY_HOME") and home == project_root():
        return home / "server/server_config.json"
    return home / "server_config.json"
