"""Desktop resource and private runtime locations, independent of process CWD."""
import os
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def runtime_home() -> Path:
    override = os.environ.get('BIDMONITOR_DESKTOP_HOME')
    if override:
        return Path(override).expanduser().resolve()
    root = project_root()
    legacy = root / 'original_desktop'
    if any((legacy / name).is_file() for name in ('user_config.json', 'config/config.yaml', 'data/bids.db', 'output_log.txt')):
        return legacy
    return root / 'runtime' / 'desktop'


def database_path() -> Path:
    return runtime_home() / 'data' / 'bids.db'


def config_path() -> Path:
    return runtime_home() / 'user_config.json'
