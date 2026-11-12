"""Compatibility command for the maintained desktop application."""
import importlib.util
from pathlib import Path
import sys

_package = Path(__file__).resolve().parents[0] / "apps"
if "apps" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("apps", _package / "__init__.py", submodule_search_locations=[str(_package)])
    _apps = importlib.util.module_from_spec(_spec)
    sys.modules["apps"] = _apps
    _spec.loader.exec_module(_apps)

from apps.desktop.bidmonitor_desktop.launcher import main

if __name__ == "__main__":
    main()
