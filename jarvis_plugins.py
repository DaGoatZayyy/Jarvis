"""Local extension loader for J.A.R.V.I.S.

Plugins are trusted Python code. Only install plugins you have reviewed.
Each .py file in ./plugins must expose register() returning a list of
{"definition": OpenAI-style tool schema, "handler": callable} entries.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = ROOT / "plugins"
_loaded = {}
_definitions = []
_errors = {}
_initialized = False


def load_plugins(logger=None, force=False):
    global _initialized
    logger = logger or (lambda message: None)
    if _initialized and not force:
        return plugin_status()
    _loaded.clear()
    _definitions.clear()
    _errors.clear()
    PLUGIN_DIR.mkdir(exist_ok=True)
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.stem}", path)
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
            pending = []
            for entry in entries:
                definition = entry.get("definition")
                handler = entry.get("handler")
                if not isinstance(definition, dict) or not callable(handler):
                    raise ValueError("Each plugin entry needs a definition and callable handler.")
                function = definition.get("function", {})
                name = function.get("name", "")
                if not name or not name.replace("_", "").isalnum():
                    raise ValueError("Tool names must contain only letters, numbers and underscores.")
                if name in _loaded or any(item[0] == name for item in pending):
                    raise ValueError(f"Duplicate plugin tool name: {name}")
                pending.append((name, definition, handler))
            for name, definition, handler in pending:
                _definitions.append(definition)
                _loaded[name] = handler
            logger(f"Loaded plugin {path.name}: {len(pending)} tool(s)")
        except Exception as exc:
            _errors[path.name] = str(exc)
            logger(f"Plugin load failed ({path.name}): {exc}")
    _initialized = True
    return plugin_status()


def plugin_tools():
    if not _initialized:
        load_plugins()
    return list(_definitions)


def execute_plugin(name, arguments):
    if not _initialized:
        load_plugins()
    handler = _loaded.get(name)
    if handler is None:
        return None
    try:
        return str(handler(arguments if isinstance(arguments, dict) else {}))[:5000]
    except Exception as exc:
        return f"Plugin {name} failed: {exc}"


def plugin_status():
    return {
        "directory": str(PLUGIN_DIR),
        "loaded_tools": sorted(_loaded),
        "errors": dict(_errors),
    }
