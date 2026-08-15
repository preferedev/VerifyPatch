"""Environment keys for the pytest plugin.

Kept separate from ``pytest_plugin`` so coverage workers can configure the
plugin without importing it before pytest assertion-rewrites the module.
"""

PLUGIN_OUT_ENV = "VERIFYPATCH_PLUGIN_OUT"
PLUGIN_ACTIVE_ENV = "VERIFYPATCH_ACTIVE"
