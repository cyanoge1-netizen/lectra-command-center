# -*- coding: utf-8 -*-
# Per-user persisted settings for the AI Notes Studio.
# Stored as a small JSON file in data/ (settings_<user_id>.json) with 0600
# perms because a configured AI API key lives here too. Secrets are never
# written to logs or the repository.

import json
import os

from notes.config import ROOT_DIR

DEFAULT_SETTINGS = {
    # Input pipeline defaults
    "subject": "",
    "template": "ai_notes.tex",
    "font_folder": "",
    "language": "english",
    "lecture_index_mode": "auto",      # auto | manual
    "lecture_index_manual": 1,
    # AI request options (offline: recorded + used when a provider is set)
    "request_options": {
        "fix_grammar": False,
        "add_graphs": False,
        "add_explanations": False,
        "preserve_style": True,
        "add_tikz": False,
        "translate": False,
        "translate_offline": False,
    },
    "custom_prompts": [],              # [{"name": "...", "text": "..."}]
    "custom_prompt": "",
    # AI provider (offline = no network calls)
    "ai_provider": "offline",          # offline | deepseek | openai | anthropic | ollama
    "ai_model": "",
    "ai_api_key": "",                  # stored locally only; never logged
    "ai_base_url": "",
    # Per-subject default template override: {"Subject": "template.tex"}
    "subject_templates": {},
    "merge_template": "ai_notes.tex",
    "last_vault_filter": "",
}

LANGUAGES = {
    "english": {"code": "english", "label": "English"},
    "bengali": {"code": "bengali", "label": "বাংলা (Bengali)"},
    "arabic": {"code": "arabic", "label": "العربية (Arabic)"},
    "hindi": {"code": "hindi", "label": "हिन्दी (Hindi)"},
    "french": {"code": "french", "label": "Français (French)"},
    "german": {"code": "german", "label": "Deutsch (German)"},
}


class AppSettings:
    """Loads and saves the AI Notes Studio preferences."""

    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        self.settings_dir = os.path.join(ROOT_DIR, "data")
        os.makedirs(self.settings_dir, exist_ok=True)
        self.file_path = os.path.join(self.settings_dir, f"settings_{user_id}.json")
        self._data = dict(DEFAULT_SETTINGS)
        self._data["request_options"] = dict(DEFAULT_SETTINGS["request_options"])
        self.load()

    # ── persistence ──
    def load(self):
        if not os.path.exists(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for key, value in loaded.items():
            if key in self._data:
                if isinstance(self._data[key], dict) and isinstance(value, dict):
                    self._data[key].update(value)
                else:
                    self._data[key] = value

    def save(self):
        tmp = self.file_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.file_path)
        try:
            os.chmod(self.file_path, 0o600)
        except OSError:
            pass

    # ── access ──
    def get(self, key, default=None):
        if key in self._data:
            return self._data[key]
        if key.startswith("request_options."):
            opt = key.split(".", 1)[1]
            return self._data["request_options"].get(opt, default)
        return default

    def set(self, key, value):
        if key.startswith("request_options."):
            opt = key.split(".", 1)[1]
            self._data["request_options"][opt] = value
        else:
            self._data[key] = value

    def has_api_key(self) -> bool:
        return bool(self.get("ai_api_key"))

    def api_key_masked(self) -> str:
        key = self.get("ai_api_key", "")
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return key[:4] + "…" + key[-4:]
