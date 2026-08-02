# -*- coding: utf-8 -*-
# Provider-agnostic LLM client for the AI Notes Studio.
#
# Design: the app works fully offline (template + OCR + compile). When an
# API provider + key are configured, the same pipeline can ask a model to
# write the LaTeX body. This module centralizes every provider's wire
# format behind one tiny interface so the GUI never touches API details.
#
# No third-party HTTP dependency: uses urllib from the standard library.

import json
import urllib.request
import urllib.error

PROVIDERS = {
    "offline": {
        "label": "Offline (no AI)",
        "default_model": "",
        "base_url": "",
        "auth": "none",
    },
    "deepseek": {
        "label": "DeepSeek",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "auth": "bearer",
    },
    "openai": {
        "label": "OpenAI",
        "default_model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "auth": "bearer",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "default_model": "claude-sonnet-4-20250514",
        "base_url": "https://api.anthropic.com/v1/messages",
        "auth": "anthropic",
    },
    "ollama": {
        "label": "Local Ollama",
        "default_model": "llama3.2",
        "base_url": "http://localhost:11434/v1/chat/completions",
        "auth": "none",
    },
}


class AIClient:
    def __init__(self, provider: str = "offline", api_key: str = "",
                 model: str = "", base_url: str = ""):
        self.provider = provider if provider in PROVIDERS else "offline"
        info = PROVIDERS[self.provider]
        self.api_key = (api_key or "").strip()
        self.model = model.strip() or info["default_model"]
        self.base_url = (base_url.strip() or info["base_url"]).rstrip("/")

    # ── capability ──
    @property
    def available(self) -> bool:
        if self.provider == "offline":
            return False
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def describe(self) -> str:
        if not self.available:
            return "Offline — no AI provider configured."
        return f"{PROVIDERS[self.provider]['label']} ({self.model or 'default model'})"

    # ── call ──
    def complete(self, system: str, user: str, temperature: float = 0.3,
                 timeout: int = 120) -> str:
        """Returns the model's text reply. Raises AIClientError with a
        readable message on any failure (bad key, quota, network, timeout)."""
        if not self.available:
            raise AIClientError("No AI provider is configured. Open the AI Settings section "
                                "or use Offline mode.")

        if self.provider == "anthropic":
            payload = {
                "model": self.model,
                "max_tokens": 4096,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            headers = {
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            data_key = "content"
        else:
            payload = {
                "model": self.model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            headers = {"content-type": "application/json"}
            if self.api_key:
                headers["authorization"] = f"Bearer {self.api_key}"
            data_key = "choices"

        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            raise AIClientError(self._friendly_http_error(e.code, detail))
        except urllib.error.URLError as e:
            raise AIClientError(f"Network error: {e.reason}")
        except TimeoutError:
            raise AIClientError("The AI request timed out.")
        except json.JSONDecodeError:
            raise AIClientError("The AI returned an unreadable response.")

        if self.provider == "anthropic":
            try:
                parts = body.get("content", [])
                return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            except Exception:
                raise AIClientError("Unexpected response shape from Anthropic API.")
        else:
            try:
                return body["choices"][0]["message"]["content"].strip()
            except Exception:
                raise AIClientError("Unexpected response shape from the API.")

    @staticmethod
    def _friendly_http_error(code: int, detail: str) -> str:
        if code == 401:
            return "Authentication failed — check your API key."
        if code == 403:
            return "Access denied — your key may not have permission for this model."
        if code == 404:
            return "Endpoint not found — check the base URL/model."
        if code == 429:
            return "Rate limit or quota exceeded — slow down or top up credits."
        return f"API error (HTTP {code}). {detail}".strip()


class AIClientError(Exception):
    pass
