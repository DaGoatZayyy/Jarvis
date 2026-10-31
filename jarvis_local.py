"""Ollama local AI provider for J.A.R.V.I.S."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


class OllamaError(RuntimeError):
    pass


class OllamaProvider:
    def __init__(self, base_url: str, model: str, keep_alive: str = "5m", logger=None):
        self.base_url = (base_url or "http://localhost:11434").strip().rstrip("/")
        self.model = (model or "").strip()
        self.keep_alive = (keep_alive or "5m").strip()
        self.logger = logger or (lambda message: None)
        if not self.base_url.startswith(("http://", "https://")):
            raise OllamaError("Ollama URL must start with http:// or https://.")
        if not self.model:
            raise OllamaError("No local model is selected. Open Local AI Settings.")

    def _request(self, path: str, payload=None, timeout=30):
        url = self.base_url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method="GET" if payload is None else "POST",
            headers={"Content-Type": "application/json"} if payload is not None else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as err:
            detail = err.read(1200).decode("utf-8", "replace")
            self.logger(f"Local AI HTTP error {err.code}: {detail[:300]}")
            raise OllamaError(f"Ollama returned HTTP {err.code}: {detail[:700]}") from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            self.logger(f"Local AI connection error: {err}")
            raise OllamaError(
                f"Cannot connect to Ollama at {self.base_url}. Make sure Ollama is running. Details: {err}"
            ) from err
        except json.JSONDecodeError as err:
            raise OllamaError("Ollama returned invalid JSON.") from err

    def list_models(self):
        data = self._request("/api/tags", timeout=5)
        models = []
        for item in data.get("models", []):
            name = item.get("name") or item.get("model")
            if name:
                models.append(name)
        return sorted(set(models), key=str.casefold)

    def check_connection(self):
        return self.list_models()

    @staticmethod
    def _convert_messages(messages):
        converted = []
        for original in messages:
            message = {"role": original.get("role", "user")}
            content = original.get("content", "")
            images = []
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                    elif part.get("type") == "image_url":
                        image_data = (part.get("image_url") or {}).get("url", "")
                        match = re.match(r"^data:[^;]+;base64,(.+)$", image_data, re.DOTALL)
                        if match:
                            images.append(match.group(1))
                content = "\n".join(text_parts)
            message["content"] = str(content or "")
            if images:
                message["images"] = images
            if original.get("tool_calls"):
                message["tool_calls"] = original["tool_calls"]
            if message["role"] == "tool" and original.get("name"):
                message["name"] = original["name"]
            converted.append(message)
        return converted

    def chat(self, payload: dict):
        request_payload = {
            "model": self.model,
            "messages": self._convert_messages(payload.get("messages", [])),
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_predict": int(payload.get("max_tokens", 1200))},
        }
        if payload.get("tools"):
            request_payload["tools"] = payload["tools"]

        self.logger(f"Local AI request started: {self.model}")
        data = self._request("/api/chat", request_payload, timeout=180)
        message = data.get("message") or {}
        if not message or not (message.get("content") or message.get("tool_calls")):
            raise OllamaError("Ollama returned an empty response.")
        self.logger(f"Local AI response received: {self.model}")
        return {"message": message, "model": self.model}
