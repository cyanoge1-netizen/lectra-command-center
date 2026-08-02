# -*- coding: utf-8 -*-
# Offline neural machine translation via HuggingFace MarianMT (transformers + torch).
#
# One engine covers every non-English language the app supports:
#     bengali -> monirbishal/en-bn-nmt   (fine-tuned MarianMT; the Helsinki
#                                         opus-mt-en-bn model was removed)
#     hindi   -> Helsinki-NLP/opus-mt-en-hi
#     arabic  -> Helsinki-NLP/opus-mt-en-ar
#     french  -> Helsinki-NLP/opus-mt-en-fr
#     german  -> Helsinki-NLP/opus-mt-en-de
#
# Models are downloaded once (~300 MB each) on first use and cached by
# huggingface_hub; afterwards translation is fully offline. Only the most
# recently used model stays loaded so memory stays bounded.

import gc
import os
import re
import threading

# MODEL_MAP: app language code -> HuggingFace model id.
MODEL_MAP = {
    "bengali": "monirbishal/en-bn-nmt",
    "hindi":   "Helsinki-NLP/opus-mt-en-hi",
    "arabic":  "Helsinki-NLP/opus-mt-en-ar",
    "french":  "Helsinki-NLP/opus-mt-en-fr",
    "german":  "Helsinki-NLP/opus-mt-en-de",
}

MAX_TOKENS = 480
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=\n)\s*")
# Markdown structure markers that must survive translation untouched.
_STRUCT_RE = re.compile(r"^(#{1,6}\s+|\s*[-*+]\s+|\s*\d+\.\s+)")
# Math spans protected from translation (the model would mangle them).
_MATH_RE = re.compile(r"(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|\$[^$]*\$)", re.S)


class OfflineTranslationError(Exception):
    """Raised when the offline engine cannot produce a translation."""


def _try_cached_model(model_id: str):
    try:
        from huggingface_hub import try_to_load_from_cache
        for fn in ("model.safetensors", "pytorch_model.bin"):
            res = try_to_load_from_cache(model_id, fn)
            if isinstance(res, str) and os.path.isfile(res):
                return True
    except Exception:
        pass
    return False


class OfflineTranslator:
    """Lazy-loading MarianMT translator. Safe to call from a worker thread."""

    def __init__(self):
        self._loaded = None      # (lang, tokenizer, model)
        self._lock = threading.Lock()
        self._import_ok = None   # cached availability of transformers/torch

    # ─────────────────────────── capability ───────────────────────────
    def _deps_present(self) -> bool:
        if self._import_ok is None:
            try:
                import transformers  # noqa: F401
                import torch         # noqa: F401
                self._import_ok = True
            except Exception:
                self._import_ok = False
        return self._import_ok

    def supported_language(self, lang: str) -> bool:
        return lang in MODEL_MAP

    def model_id(self, lang: str):
        return MODEL_MAP.get(lang)

    def is_available(self, lang: str) -> bool:
        """True when the target language is supported AND its model is
        already on disk, so translation works with no internet."""
        if lang == "english" or not self._deps_present():
            return False
        model_id = MODEL_MAP.get(lang)
        if not model_id:
            return False
        with self._lock:
            if self._loaded and self._loaded[0] == lang:
                return True
        return _try_cached_model(model_id)

    def describe(self) -> str:
        installed = [lang for lang in MODEL_MAP if _try_cached_model(MODEL_MAP[lang])]
        if not installed:
            return "offline translation: not installed (models download on first use)"
        return "offline translation: " + ", ".join(sorted(installed))

    # ─────────────────────────── translation ───────────────────────────
    def translate(self, text: str, lang: str) -> str:
        if lang == "english":
            return text
        model_id = MODEL_MAP.get(lang)
        if not model_id:
            raise OfflineTranslationError(f"No offline model for '{lang}'.")
        tokenizer, model = self._load(lang, model_id)

        # Line-aware translation: markdown headings/lists keep their markers
        # while the prose between them is translated in batches.
        lines = text.split("\n")
        out, prose = [], []

        def flush():
            if not prose:
                return
            out.extend(self._translate_text("\n".join(prose), tokenizer, model).split("\n"))
            prose.clear()

        for line in lines:
            m = _STRUCT_RE.match(line)
            if m is None:
                prose.append(line)
                continue
            flush()
            prefix, rest = m.group(1), line[m.end():]
            if rest.strip():
                tr = self._translate_text(rest, tokenizer, model).strip()
                out.append(prefix + tr)
            else:
                out.append(line)
        flush()
        return "\n".join(out).strip()

    def _translate_text(self, text: str, tokenizer, model) -> str:
        """Translates arbitrary prose, protecting math spans from the model."""
        if not text or not text.strip():
            return text
        placeholders = {}

        def protect(m):
            key = f"\x00m{len(placeholders)}\x00"
            placeholders[key] = m.group(0)
            return key

        protected = _MATH_RE.sub(protect, text)
        for chunk in self._chunk_text(protected, tokenizer):
            translated = self._translate_chunk(chunk, tokenizer, model)
            for key, value in placeholders.items():
                translated = translated.replace(key, value)
            protected = protected.replace(chunk, translated, 1)
        return protected

    def _load(self, lang: str, model_id: str):
        with self._lock:
            if self._loaded and self._loaded[0] == lang:
                return self._loaded[1], self._loaded[2]
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
        except Exception as e:
            raise OfflineTranslationError(
                f"Could not load offline model for '{lang}' ({model_id}). "
                f"First use needs internet to download it once. ({e})")
        with self._lock:
            if self._loaded and self._loaded[0] != lang:
                # keep memory bounded: drop the previous model
                self._loaded = None
                gc.collect()
            self._loaded = (lang, tokenizer, model)
        return tokenizer, model

    def _translate_chunk(self, chunk: str, tokenizer, model) -> str:
        import torch
        enc = tokenizer(chunk, return_tensors="pt", truncation=True,
                        max_length=MAX_TOKENS)
        with torch.no_grad():
            gen = model.generate(**enc, max_length=MAX_TOKENS, num_beams=4)
        return tokenizer.batch_decode(gen, skip_special_tokens=True)[0]

    def _chunk_text(self, text: str, tokenizer) -> list:
        """Splits the text into sub-500-token chunks without destroying the
        paragraph / heading line structure the markdown converter needs."""
        chunks, current, current_len = [], [], 0

        def flush():
            nonlocal current, current_len
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0

        for para in re.split(r"\n\s*\n", text):
            if not para.strip():
                continue
            n = len(tokenizer.encode(para, add_special_tokens=False))
            if current and current_len + n > MAX_TOKENS:
                flush()
            if n <= MAX_TOKENS:
                current.append(para)
                current_len += n
            else:
                # very long paragraph → cut on sentence boundaries
                for s in _SENT_SPLIT.split(para):
                    s = s.strip()
                    if not s:
                        continue
                    current.append(s)
                    current_len += len(tokenizer.encode(s, add_special_tokens=False))
                    if current_len > MAX_TOKENS:
                        flush()
        flush()
        return chunks or [text]
