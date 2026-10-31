"""Provider abstraction for OpenRouter and local Ollama."""
from __future__ import annotations

from jarvis_local import OllamaProvider


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, post_function):
        self.post_function = post_function

    def chat(self, payload, candidates=None):
        return self.post_function(payload, candidates)


class LocalAIProvider:
    name = "ollama"

    def __init__(self, cfg, logger=None):
        self.provider = OllamaProvider(
            cfg.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            cfg.get("OLLAMA_MODEL", "qwen2.5:7b"),
            cfg.get("OLLAMA_KEEP_ALIVE", "5m"),
            logger=logger,
        )

    def chat(self, payload, candidates=None):
        return self.provider.chat(payload)

    def list_models(self):
        return self.provider.list_models()


def create_provider(cfg, openrouter_post, logger=None):
    """Create exactly the selected backend; deliberately never cross-fallback."""
    selected = str(cfg.get("JARVIS_PROVIDER", "openrouter")).strip().casefold()
    if selected in ("ollama", "local", "local_ai"):
        return LocalAIProvider(cfg, logger=logger), "ollama"
    return OpenRouterProvider(openrouter_post), "openrouter"
