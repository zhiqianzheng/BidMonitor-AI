"""Stable workbench data paths, independent of the current working directory."""
import os
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def runtime_home() -> Path:
    override = os.environ.get("BIDMONITOR_WORKBENCH_HOME")
    if override:
        return Path(override).expanduser().resolve()
    root = project_root()
    if (root / "data" / "bids.db").is_file():
        return root
    return root / "runtime" / "workbench"


def database_path() -> Path:
    override = os.environ.get("BIDMONITOR_DB")
    if override:
        return Path(override).expanduser().resolve()
    return runtime_home() / "data" / "bids.db"
