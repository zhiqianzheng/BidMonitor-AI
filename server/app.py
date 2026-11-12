"""Historical Web server compatibility entry; new workbench uses run_workbench.py."""
import importlib.util
from pathlib import Path
import sys

_package = Path(__file__).resolve().parents[1] / "apps"
if "apps" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("apps", _package / "__init__.py", submodule_search_locations=[str(_package)])
    _apps = importlib.util.module_from_spec(_spec)
    sys.modules["apps"] = _apps
    _spec.loader.exec_module(_apps)

import apps.legacy_web.bidmonitor_legacy_web.app as _application

app = _application.app


def __getattr__(name):
    return getattr(_application, name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
