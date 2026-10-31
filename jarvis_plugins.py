"""Local extension loader for J.A.R.V.I.S.

Plugins are trusted Python code. Only install plugins you have reviewed.
Each plugin is a .py file in ./plugins and must expose register() returning
a list of {"definition": OpenAI-style tool schema, "handler": callable}.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = ROOT / "plugins"
_loaded = {}
_errors = {}


def load_plugins(logger=None):
    logger = logger or (lambda message: None)
    PLUGIN_DIR.mkdir(exist_ok=True)
    _loaded.clear()
    _errors.clear()
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"jarvis_plugin_{path.stem}", path
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("Could not create a Python module loader.")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise ValueError("Plugin must define register().")
            entries = register()
            if not isinstance(entries, list):
                raise ValueError("register() must return a list.")
            for entry in entries:
                definition = entry.get("definition")
                handler = entry.get("handler")
                if not isinstance(definition, dict) or not callable(handler):
                    raise ValueError("Each plugin entry needs a definition and callable handler.")
                function = definition.get("function", {})
                name = function.get("name", "")
                if not name or not name.replace("_", "").isalnum():
                    raise ValueError("Tool names must contain only letters, numbers and underscores.")
                if name in _loaded:
                    raise ValueError(f"Duplicate plugin tool name: {name}")
                _loaded[name] = handler
            logger(f"Loaded plugin {path.name}: {len(entries)} tool(s)")
        except Exception as exc:
            _errors[path.name] = str(exc)
            logger(f"Plugin load failed ({path.name}): {exc}")
    return plugin_status()


def plugin_tools():
    definitions = []
    for path in sorted(PLUGIN_DIR.glob("*.py")) if PLUGIN_DIR.exists() else []:
        if path.name.startswith("_"):
            continue
        # Reload once per process startup so tool definitions stay in sync.
        if not _loaded and not _errors:
            load_plugins()
        try:
            spec = importlib.util.spec_from_file_location(f"jarvis_plugin_schema_{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for entry in module.register():
                definition = entry.get("definition")
                if isinstance(definition, dict) and isinstance(entry.get("handler"), object):
                    definitions.append(definition)
        except Exception:
            continue
    return definitions


def execute_plugin(name, arguments):
    handler = _loaded.get(name)
    if handler is None:
        return "Plugin tool is not loaded."
    try:
        result = handler(arguments if isinstance(arguments, dict) else {})
        return str(result)[:5000]
    except Exception as exc:
        return f"Plugin {name} failed: {exc}"


def plugin_status():
    return {
        "directory": str(PLUGIN_DIR),
        "loaded_tools": sorted(_loaded),
        "errors": dict(_errors),
    }
