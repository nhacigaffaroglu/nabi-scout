from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_DASHBOARD_MODULE_NAME = "dashboard_page"
_DASHBOARD_MODULE = None
_DASHBOARD_PATH = Path("pages/1_Dashboard.py")


def load_dashboard_page():
    global _DASHBOARD_MODULE

    if _DASHBOARD_MODULE is not None:
        sys.modules[_DASHBOARD_MODULE_NAME] = _DASHBOARD_MODULE
        return _DASHBOARD_MODULE

    spec = importlib.util.spec_from_file_location(_DASHBOARD_MODULE_NAME, _DASHBOARD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_DASHBOARD_MODULE_NAME] = module
    spec.loader.exec_module(module)
    _DASHBOARD_MODULE = module
    return module
