"""How VerifyPatch invokes pytest inside subject repositories.

Subject suites that set ``filterwarnings = error`` treat pytest's
"module already imported so cannot be rewritten" warning as a hard error.

``python -m verifypatch.coverage_worker`` imports the ``verifypatch`` package
before pytest starts. Pytest then walks every pytest11 distribution and
tries to assertion-rewrite the already-imported ``verifypatch`` package.

Coverage collection therefore:

- sets ``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` so pytest does not rewrite the
  already-imported VerifyPatch package
- unloads in-process ``verifypatch*`` modules before ``pytest.main``
- marks the package ``PYTEST_DONT_REWRITE`` so a remaining import is not a warning
- loads ``verifypatch.pytest_plugin`` explicitly
- reloads other pytest11 entry points so subject plugins still run
- never imports ``verifypatch.pytest_plugin`` in the worker before pytest starts

Mutation and generated-test runs start a fresh interpreter, disable the
VerifyPatch entry point, and do not load the plugin.
"""

from __future__ import annotations

import sys

from verifypatch.plugin_env import PLUGIN_ACTIVE_ENV, PLUGIN_OUT_ENV

VERIFYPATCH_PLUGIN_ENTRY = "verifypatch"
VERIFYPATCH_PLUGIN_MODULE = "verifypatch.pytest_plugin"
DISABLE_AUTOLOAD_ENV = "PYTEST_DISABLE_PLUGIN_AUTOLOAD"


def unload_verifypatch_modules() -> None:
    """Drop in-process VerifyPatch modules so pytest can load the plugin fresh.

    ``python -m verifypatch.coverage_worker`` imports the ``verifypatch`` package
    before pytest starts. Pytest then calls ``mark_rewrite("verifypatch")`` for
    the pytest11 distribution. Repositories with ``filterwarnings = error``
    turn that into a collection failure. Unloading the package avoids the
    warning; ``PYTEST_DONT_REWRITE`` on the package docstring is the fallback
    when unload is not possible.
    """
    for name in list(sys.modules):
        if name == "verifypatch" or name.startswith("verifypatch."):
            sys.modules.pop(name, None)


def disable_entry_point_args() -> list[str]:
    return ["-p", "no:verifypatch"]


def explicit_plugin_args() -> list[str]:
    return [*disable_entry_point_args(), "-p", VERIFYPATCH_PLUGIN_MODULE]


def third_party_plugin_args() -> list[str]:
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        return []
    discovered = entry_points()
    if hasattr(discovered, "select"):
        selected = list(discovered.select(group="pytest11"))
    else:  # pragma: no cover
        selected = list(discovered.get("pytest11", []))  # type: ignore[attr-defined]
    args: list[str] = []
    seen: set[str] = set()
    for ep in selected:
        name = getattr(ep, "name", "")
        value = getattr(ep, "value", "") or ""
        if name == VERIFYPATCH_PLUGIN_ENTRY or value.startswith("verifypatch."):
            continue
        module = value.split(":", 1)[0]
        if not module or module in seen or module == VERIFYPATCH_PLUGIN_MODULE:
            continue
        seen.add(module)
        args.extend(["-p", module])
    return args


def coverage_pytest_main_args(pytest_args: list[str]) -> list[str]:
    return [*explicit_plugin_args(), *third_party_plugin_args(), "-q", *list(pytest_args)]


def coverage_pytest_env(env: dict[str, str]) -> dict[str, str]:
    updated = dict(env)
    updated[DISABLE_AUTOLOAD_ENV] = "1"
    return updated


def scrub_plugin_env(env: dict[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    cleaned.pop(PLUGIN_OUT_ENV, None)
    cleaned.pop(PLUGIN_ACTIVE_ENV, None)
    return cleaned
