"""Re-export seeded_app_cap1 for backward compatibility.

The fixture is defined in conftest.py (auto-discovered by pytest). This module
exists for any code that explicitly imports it.
"""
from __future__ import annotations

# pytest auto-discovers seeded_app_cap1 from conftest.py; nothing to export.
# This file is kept so that any import of the symbol doesn't cause ModuleNotFoundError
# if the test ever does `from tests.integration.conftest_cap import seeded_app_cap1`.
