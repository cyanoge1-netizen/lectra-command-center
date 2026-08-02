# -*- coding: utf-8 -*-
# Offline-first AI Notes Studio pipeline (ported from the ERP project).
#
# Flow:  input files (.md/.txt/.png/.jpg/.pdf)  ->  text extraction
#        (OCR for images + scanned PDFs, text layer for digital PDFs)
#        ->  optional AI enhancement  ->  Jinja render against a template
#        ->  xelatex compile  ->  structured Vault entry.
#
# Works end-to-end with NO network/API key. When a provider is configured
# (notes/ai_client.py) the same flow asks the model to write the LaTeX body
# instead of the built-in markdown-to-LaTeX converter.

import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime

from jinja2 import Environment, FileSystemLoader

from notes.config import TEMPLATES_DIR
from notes.vault import VaultEngine
from notes.ai_client import AIClient, AIClientError
from notes.settings import LANGUAGES
from notes.xelatex_compiler import XeLaTeXCompiler
from notes.ocr_engine import OCREngine
from notes.offline_translator import OfflineTranslator, OfflineTranslationError

# Tesseract language code per app language (falls back to eng if missing).
LANG_TO_TESSERACT = {
    "english": "eng", "bengali": "ben", "arabic": "ara",
    "hindi": "hin", "french": "fra", "german": "deu",
}
# Fontconfig language code per app language (used to auto-pick a font).
LANG_TO_FONTCONFIG = {
    "english": "en", "bengali": "bn", "arabic": "ar",
    "hindi": "hi", "french": "fr", "german": "de",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".heic"}
TEXT_EXTS = {".md", ".txt", ".markdown", ".text"}
PDF_EXT = {".pdf"}


class PipelineError(Exception):
    pass


class AINotesPipeline:
    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        self.vault = VaultEngine(user_id)
        self.compiler = XeLaTeXCompiler()
        self.ocr = OCREngine()
        self.translator = OfflineTranslator()
        self.template_dir = TEMPLATES_DIR
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            block_start_string="[%", block_end_string="%]",
            variable_start_string="[[", variable_end_string="]]",
            comment_start_string="[#", comment_end_string="#]",
        )

    # ─────────────────────────── templates ───────────────────────────
    def available_templates(self) -> list:
        """Lists every usable template: flat ``name.tex`` files and
        spec-compliant ``<name>/template.tex`` folders. Display names."""
        if not os.path.isdir(self.template_dir):
            return []
        names = []
        for entry in sorted(os.listdir(self.template_dir)):
            full = os.path.join(self.template_dir, entry)
            if os.path.isfile(full) and entry.endswith(".tex"):
                names.append(entry)
            elif os.path.isdir(full) and os.path.isfile(os.path.join(full, "template.tex")):
                names.append(entry)
        return names

    def _template_ref(self, template: str) -> str:
        """Jinja loader reference for a display name (folder templates
        live one level deeper as ``<name>/template.tex``)."""
        if os.path.isfile(os.path.join(self.template_dir, template)):
            return template
        if os.path.isfile(os.path.join(self.template_dir, template, "template.tex")):
            return os.path.join(template, "template.tex")
        return template

    def template_source(self, template: str) -> str:
        path = os.path.join(self.template_dir, self._template_ref(template))
        if not os.path.isfile(path):
            raise PipelineError(f"Template not found: {template}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def template_meta(self, template: str) -> dict:
        """Reads ``meta.json`` next to a template, if present."""
        path = os.path.join(self.template_dir, template, "meta.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def template_preview(self, template: str) -> str:
        """Absolute path to ``preview.png`` for a folder template, or ''."""
        path = os.path.join(self.template_dir, template, "preview.png")
        return path if os.path.isfile(path) else ""

    # ─────────────────────────── text extraction ───────────────────────────
    def extract_text_from_file(self, path: str, ocr_lang: str = "eng") -> str:
        """Extracts text from a markdown/text/image/PDF file. Raises
        PipelineError with a readable message when a step cannot run."""
        if not os.path.isfile(path):
            raise PipelineError(f"File not found: {path}")

        ext = os.path.splitext(path)[1].lower()

        if ext in TEXT_EXTS:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read().strip()
            except OSError as e:
                raise PipelineError(f"Could not read {path}: {e}")

        if ext in IMAGE_EXTS:
            if not self.ocr.is_available():
                raise PipelineError(
                    "OCR is not installed. Run this once in a terminal:\n\n"
                    "    sudo apt install -y tesseract-ocr\n"
                    "    pip3 install --user --break-system-packages pytesseract\n\n"
                    "Then restart the app."
                )
            try:
                return self.ocr.extract_text(path, lang=ocr_lang)
            except Exception as e:
                raise PipelineError(f"OCR failed on {path}: {e}")

        if ext in PDF_EXT:
            return self._extract_pdf_text(path, ocr_lang)

        raise PipelineError(f"Unsupported file type: {ext}")

    def _extract_pdf_text(self, pdf_path: str, ocr_lang: str) -> str:
        try:
            import fitz  # pymupdf
        except ImportError:
            raise PipelineError("PDF support needs 'pymupdf'. Run:\n"
                                "    pip3 install --user --break-system-packages pymupdf")

        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            raise PipelineError(f"Could not open PDF {pdf_path}: {e}")

        text = ""
        try:
            for page in doc:
                text += page.get_text("text")
        finally:
            doc.close()

        # A real text layer -> use it directly (digital PDF).
        if len(text.strip()) >= 40:
            return text.strip()

        # Otherwise it is a scanned PDF: OCR every page.
        if not self.ocr.is_available():
            raise PipelineError(
                "This PDF has no text layer (it's scanned). OCR is not installed.\n"
                "Run:  sudo apt install -y tesseract-ocr"
            )

        tmp_dir = os.path.join(self.vault.root, ".tmp_ocr")
        os.makedirs(tmp_dir, exist_ok=True)
        chunks = []
        try:
            doc = fitz.open(pdf_path)
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=150)
                img_path = os.path.join(tmp_dir, f"page_{i:03d}.png")
                pix.save(img_path)
                try:
                    chunks.append(self.ocr.extract_text(img_path, lang=ocr_lang))
                except Exception as e:
                    chunks.append(f"[OCR error on page {i + 1}: {e}]")
            doc.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        combined = "\n\n".join(c for c in chunks if c and c.strip())
        if not combined.strip():
            raise PipelineError("No readable text could be extracted from the PDF.")
        return combined.strip()

    # ─────────────────────────── markdown → LaTeX ───────────────────────────
    @staticmethod
    def markdown_to_latex(text: str) -> str:
        """Lightweight markdown-to-LaTeX conversion good enough for lecture
        notes: headings, lists, code blocks, bold/italic, links, math."""

        protected = []  # math + code blocks kept verbatim

        def protect_math(m):
            protected.append(m.group(0))
            return f"@@MATH{len(protected) - 1}@@"

        def protect_code(m):
            protected.append(m.group(1))
            return f"@@CODE{len(protected) - 1}@@"

        text = re.sub(r"```[^\n]*\n(.*?)```", protect_code, text, flags=re.S)
        text = re.sub(r"\$\$.*?\$\$|\$.*?\$|\\\[.*?\\\]|\\\(.*?\\\)",
                      protect_math, text, flags=re.S)

        lines = []
        in_list = None  # None | "itemize" | "enumerate"

        def close_list():
            nonlocal in_list
            if in_list == "itemize":
                lines.append("\\end{itemize}")
            elif in_list == "enumerate":
                lines.append("\\end{enumerate}")
            in_list = None

        for raw in text.split("\n"):
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                close_list()
                lines.append("")
                continue

            m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if m:
                close_list()
                lines.append("")
                level = len(m.group(1))
                section = {1: "section", 2: "subsection", 3: "subsubsection"}.get(level, "paragraph")
                lines.append(f"\\{section}{{{AINotesPipeline._inline(m.group(2))}}}")
                continue

            m = re.match(r"^[-*•]\s+(.*)$", stripped)
            if m:
                if in_list != "itemize":
                    if in_list == "enumerate":
                        lines.append("\\end{enumerate}")
                    lines.append("\\begin{itemize}")
                    in_list = "itemize"
                lines.append(f"  \\item {AINotesPipeline._inline(m.group(1))}")
                continue

            m = re.match(r"^\d+[.)]\s+(.*)$", stripped)
            if m:
                if in_list != "enumerate":
                    if in_list == "itemize":
                        lines.append("\\end{itemize}")
                    lines.append("\\begin{enumerate}")
                    in_list = "enumerate"
                lines.append(f"  \\item {AINotesPipeline._inline(m.group(1))}")
                continue

            if in_list == "itemize":
                lines.append("\\end{itemize}")
            elif in_list == "enumerate":
                lines.append("\\end{enumerate}")
            in_list = None
            lines.append(AINotesPipeline._inline(stripped))

        close_list()

        result = "\n".join(lines)

        for i, piece in enumerate(protected):
            if piece.startswith("@@CODE"):
                result = result.replace(f"@@CODE{i}@@",
                                        "\\begin{verbatim}\n" + piece + "\n\\end{verbatim}")
            else:
                result = result.replace(f"@@MATH{i}@@", piece)
        return result

    @staticmethod
    def _inline(text: str) -> str:
        """Inline markdown (bold/italic/code/links) then LaTeX-escaping."""
        text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
        text = re.sub(r"__(.+?)__", r"\\textbf{\1}", text)
        text = re.sub(r"\*(.+?)\*", r"\\emph{\1}", text)
        text = re.sub(r"`([^`]+)`", r"\\texttt{\1}", text)
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                      lambda m: f"\\includegraphics{{{m.group(2)}}}" if os.path.isfile(m.group(2)) else f"[image: {m.group(1)}]",
                      text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\\href{\2}{\1}", text)
        return AINotesPipeline.escape_latex(text)

    @staticmethod
    def escape_latex(text: str) -> str:
        """Escapes LaTeX specials in plain text."""
        if not text:
            return text
        text = text.replace("\\", "\\textbackslash{}")
        text = text.replace("&", "\\&").replace("%", "\\%").replace("#", "\\#")
        text = text.replace("_", "\\_").replace("{", "\\{").replace("}", "\\}")
        text = text.replace("$", "\\$")
        text = text.replace("~", "\\textasciitilde{}")
        text = text.replace("^", "\\textasciicircum{}")
        return text

    # ─────────────────────────── fonts ───────────────────────────
    def resolve_fonts(self, language: str, font_folder: str) -> tuple:
        """Returns (font_path, font_file). Uses the user-selected folder
        first; falls back to auto-detecting a system font for non-Latin
        languages so Bengali etc. work without any setup."""
        if font_folder and os.path.isdir(font_folder):
            fonts = sorted(f for f in os.listdir(font_folder)
                           if f.lower().endswith((".ttf", ".otf")))
            if fonts:
                return font_folder, os.path.splitext(fonts[0])[0]

        fc_lang = LANG_TO_FONTCONFIG.get(language)
        if not fc_lang or fc_lang == "en":
            return "", ""
        try:
            out = subprocess.run(
                ["fc-list", "-f", "%{file}\n", f":lang={fc_lang}"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip().splitlines()
        except (subprocess.SubprocessError, FileNotFoundError):
            return "", ""
        for path in out:
            path = path.strip()
            if path.lower().endswith((".ttf", ".otf")):
                return os.path.dirname(path), os.path.splitext(os.path.basename(path))[0]
        return "", ""

    # ─────────────────────────── rendering ───────────────────────────
    def render_document(self, template: str, subject: str, lecture_index: int,
                        topic: str, content: str, language: str,
                        font_path: str, font_file: str) -> str:
        try:
            tpl = self.env.get_template(self._template_ref(template))
        except Exception as e:
            raise PipelineError(f"Could not load template '{template}': {e}")
        try:
            return tpl.render(
                subject=subject,
                lecture_index=lecture_index,
                topic=topic,
                date=date.today().strftime("%Y-%m-%d"),
                language=language,
                font_path=font_path,
                font_file=font_file,
                content=content,
            )
        except Exception as e:
            raise PipelineError(f"Template rendering failed: {e}")

    # ─────────────────────────── AI prompt ───────────────────────────
    # Fixed standing instructions — injected on every AI job.
    SYSTEM_PROMPT = (
        "You are an expert LaTeX note-typesetter. Convert raw/handwritten/scanned "
        "lecture material into a polished, professional XeLaTeX note using ONLY the "
        "box environments, colors, and header/footer already defined in the selected "
        "template's preamble — do not redesign the visual system.\n\n"
        "WORKFLOW:\n"
        "1. Transcribe the input faithfully (all formulas, tables, diagram content). "
        "Never invent facts that contradict the source.\n"
        "2. Silently correct grammar/spelling into clean academic prose in the target "
        "language, unless \"Preserve style\" is active — then only fix outright "
        "errors, keep phrasing/order intact.\n"
        "3. Reorganize into: Definition → Rules/Conditions → Worked Example(s) → "
        "Table/Diagram → Homework — unless \"Preserve style\" is active.\n"
        "4. If a topic is under-explained and \"Add explanatory detail\" is active, "
        "fill gaps with standard, correct, level-appropriate content, written to "
        "blend in seamlessly.\n"
        "5. If \"Add TikZ diagrams\" is active, illustrate real-world examples with "
        "simple flat pictograms in the template's existing color palette — reuse "
        "existing icon commands from the template if present, else define new ones "
        "in the same visual style.\n"
        "6. If \"Add graphs\" is active and the content implies plotted data or "
        "functions, generate accurate pgfplots/tikz graphs — verify axis values and "
        "function shapes before finalizing.\n"
        "7. Apply any additional free-text instruction from the user verbatim, as a "
        "soft constraint on top of the rules above.\n"
        "8. Verify every formula, derivation, and table for correctness before "
        "finalizing — do not guess on math.\n"
        "9. Output ONLY the completed .tex body. Do not invent the template's "
        "preamble, package list, or color/box definitions."
    )

    # Box environments the active templates provide — the model should use them.
    BOX_ENVIRONMENTS = (
        "defbox (Definition), examplebox (Example), theorembox (Solution), "
        "hwbox (H.W.), rulebox (Rules), notebox (Note)"
    )

    def build_ai_prompt(self, extracted_text: str, options: dict, custom_prompt: str,
                        language_label: str = "", translate: bool = False) -> str:
        requested = []
        if options.get("fix_grammar"):
            requested.append("Fix grammatical and typographical errors")
        if options.get("add_graphs"):
            requested.append("Add relevant charts/graphs using pgfplots where helpful")
        if options.get("add_explanations"):
            requested.append("Add clear, concise explanations for key concepts")
        if options.get("preserve_style"):
            requested.append("Preserve the author's original style and structure exactly")
        if options.get("add_tikz"):
            requested.append("Add relevant TikZ diagrams where they clarify the content")
        if translate and language_label:
            requested.append(f"Translate the final note into {language_label}")
        if custom_prompt and custom_prompt.strip():
            requested.append(custom_prompt.strip())

        asks = "\n".join(f"- {r}" for r in requested) if requested else "- None requested"
        return (
            "Write the LaTeX BODY for a lecture note (content that goes between "
            "\\begin{document} and \\end{document}). Use the template's box "
            f"environments where they fit ({AINotesPipeline.BOX_ENVIRONMENTS}), "
            "\\section/\\subsection for headings, \\begin{itemize} lists, math with "
            "$...$ / \\[...\\], and pgfplots/tikz as needed. Preserve the student's "
            "actual content; do not invent facts that are not present. If the source "
            "is handwriting OCR with noise, clean it up.\n\n"
            "Requested transformations:\n" + asks + "\n\n"
            "Source material:\n" + extracted_text[:12000]
        )

    # ─────────────────────────── main flow ───────────────────────────
    def extract_preview(self, input_paths: list, pasted_text: str, language: str) -> list:
        """Extracts text from the current inputs WITHOUT generating, so the
        user can sanity-check OCR before compiling. Returns [(name, text)]."""
        ocr_lang = LANG_TO_TESSERACT.get(language, "eng")
        out = []
        for path in (input_paths or []):
            out.append((os.path.basename(path), self.extract_text_from_file(path, ocr_lang)))
        if pasted_text and pasted_text.strip():
            out.append(("pasted text", pasted_text.strip()))
        return out

    def generate(self, subject: str, template: str, language: str,
                 font_folder: str, topic: str, input_paths: list,
                 pasted_text: str, options: dict, custom_prompt: str,
                 lecture_index_mode: str, lecture_index_manual: int,
                 ai_client: AIClient = None,
                 progress=None) -> dict:
        """Runs the full pipeline. Returns a dict describing the vault entry."""
        def log(msg):
            if progress:
                progress(msg)

        if not subject or not subject.strip():
            raise PipelineError("Choose a subject first.")
        subject = subject.strip()

        template = template or "ai_notes.tex"

        # 1. Extract text
        log("1/6 Extracting text from sources…")
        ocr_lang = LANG_TO_TESSERACT.get(language, "eng")
        sources = []
        for path in (input_paths or []):
            log(f"   • {os.path.basename(path)}")
            sources.append((os.path.basename(path), self.extract_text_from_file(path, ocr_lang)))
        if pasted_text and pasted_text.strip():
            sources.append(("pasted text", pasted_text.strip()))
        if not sources:
            raise PipelineError("Add some input first (files or pasted text).")

        combined = "\n\n".join(
            f"--- {name} ---\n{text}" if len(sources) > 1 else text
            for name, text in sources
        )
        if not combined.strip():
            raise PipelineError("No readable content to work with.")

        # 2. Lecture index
        log("2/6 Resolving lecture index…")
        if lecture_index_mode == "manual" and lecture_index_manual and lecture_index_manual > 0:
            lecture_index = int(lecture_index_manual)
        else:
            lecture_index = self.vault.next_index(subject)

        topic = (topic or f"Lecture {lecture_index}").strip()

        # 3. Fonts
        log("3/6 Resolving fonts…")
        font_folder, font_file = self.resolve_fonts(language, font_folder)
        if language != "english" and not font_file:
            log("   ⚠ No font selected for non-Latin text — glyphs may not render.")

        # 4. Content (AI or offline converter) + optional offline translation
        log("4/6 Building LaTeX content…")
        use_ai = ai_client is not None and ai_client.available
        wants_translate = bool(options.get("translate")) or bool(options.get("translate_offline"))
        # "translate offline" always uses the local engine; otherwise the offline
        # engine is the fallback when translation was requested but no AI is set up.
        force_offline = bool(options.get("translate_offline"))
        if force_offline or (not use_ai and wants_translate):
            if language != "english" and self.translator.supported_language(language):
                try:
                    combined = self.translator.translate(combined, language)
                    label = LANGUAGES.get(language, {}).get("label", language)
                    log(f"   ✓ Offline translation → {label}")
                except OfflineTranslationError as e:
                    if force_offline:
                        raise PipelineError(str(e))
                    log(f"   ⚠ Offline translation skipped: {e}")
            elif force_offline and language != "english":
                log(f"   ⚠ No offline model for '{language}'.")

        if use_ai:
            lang_label = LANGUAGES.get(language, {}).get("label", language)
            ai_prompt = self.build_ai_prompt(combined, options, custom_prompt,
                                             language_label=lang_label,
                                             translate=wants_translate and not force_offline)
            content = ai_client.complete(self.SYSTEM_PROMPT, ai_prompt)
        else:
            content = self.markdown_to_latex(combined)

        # 5. Assemble the per-note bundle
        log("5/6 Writing note bundle…")
        bundle = self.vault.bundle_dir(subject, lecture_index)
        fonts_dir = os.path.join(bundle, "fonts")
        assets_dir = os.path.join(bundle, "assets")
        os.makedirs(fonts_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)

        content = self._collect_assets(content, assets_dir)

        font_path, font_file = self._bundle_fonts(font_folder, font_file, fonts_dir)
        if font_path:
            font_path = "./fonts"  # relative → the bundle stays portable

        rendered = self.render_document(template, subject, lecture_index, topic,
                                        content, language, font_path, font_file)

        filename = self.vault.build_filename(subject, lecture_index, topic, "tex")
        tex_path = os.path.join(bundle, filename)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(rendered)

        transcript_path = os.path.join(bundle, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(combined)

        # 6. Compile + error recovery (cap 3 patch attempts)
        log("6/6 Compiling with XeLaTeX…")
        ok, pdf_path, compile_log = self.compiler.compile_arbitrary_tex(tex_path, runs=2)
        attempt = 0
        while not ok and use_ai and attempt < 3:
            attempt += 1
            log(f"   ✖ compile failed — asking the AI to patch the .tex ({attempt}/3)…")
            fixed = self._request_tex_fix(ai_client, tex_path, compile_log)
            if not fixed:
                log("   ✖ AI did not return a usable fix.")
                break
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(fixed)
            ok, pdf_path, compile_log = self.compiler.compile_arbitrary_tex(tex_path, runs=2)
        if not ok:
            raise PipelineError(
                "XeLaTeX compilation failed. Check the template/content.\n"
                f"Last log lines:\n{compile_log.strip()[-1200:]}"
            )

        pages = 0
        try:
            import fitz
            with fitz.open(pdf_path) as doc:
                pages = doc.page_count
        except Exception:
            pass

        meta = {
            "subject": subject,
            "lecture_index": lecture_index,
            "title": topic,
            "template": template,
            "language": language,
            "created": datetime.now().isoformat(timespec="seconds"),
            "input_files": [os.path.basename(p) for p in (input_paths or [])],
            "request_options": dict(options or {}),
            "custom_prompt": custom_prompt or "",
            "font_folder": font_folder or "",
            "pages": pages,
        }
        with open(os.path.join(bundle, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        entry = self.vault.add_entry(
            subject, lecture_index, topic, pdf_path, tex_path, pages,
            folder=bundle, template=template, language=language,
            options=options or {}, input_files=meta["input_files"],
            transcript_path=transcript_path, fonts_dir=fonts_dir,
            assets_dir=assets_dir,
        )
        log(f"✅ Saved: {os.path.basename(pdf_path)} ({pages} pages)")
        return {"entry": entry, "pdf_path": pdf_path, "tex_path": tex_path,
                "bundle": bundle}

    # ─────────────────────────── bundle helpers ───────────────────────────
    def _collect_assets(self, content: str, assets_dir: str) -> str:
        """Copies any local images referenced via \\includegraphics into the
        note bundle's assets/ folder and rewrites paths to be relative, so
        the bundle stays portable."""
        seen = {}

        def repl(m):
            opts = m.group(1) or ""
            path = m.group(2).strip()
            if not os.path.isfile(path):
                return m.group(0)
            if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
                return m.group(0)
            if path not in seen:
                dest = os.path.join(assets_dir, os.path.basename(path))
                try:
                    shutil.copy2(path, dest)
                except OSError:
                    return m.group(0)
                seen[path] = os.path.basename(path)
            return "\\includegraphics" + (f"[{opts}]" if opts else "") + \
                   "{assets/" + seen[path] + "}"

        pattern = re.compile(r"\\includegraphics(?:\[([^\]]*)\])?\{([^}]+)\}")
        return pattern.sub(repl, content)

    @staticmethod
    def _bundle_fonts(font_folder: str, font_file: str, dest_dir: str) -> tuple:
        """Copies the selected font family into the bundle's fonts/ dir so
        the note compiles without system-wide font installs. Returns the
        (dest_dir, font_file) to pass to the template ('' if none copied)."""
        if not font_folder or not font_file or not os.path.isdir(font_folder):
            return "", ""
        stem = font_file.lower()
        copied = 0
        for name in sorted(os.listdir(font_folder)):
            if name.lower().endswith((".ttf", ".otf")) and name.lower().startswith(stem):
                try:
                    shutil.copy2(os.path.join(font_folder, name),
                                 os.path.join(dest_dir, name))
                    copied += 1
                except OSError:
                    continue
        if copied == 0:  # single-file family: copy whatever's in the folder
            for name in sorted(os.listdir(font_folder)):
                if name.lower().endswith((".ttf", ".otf")):
                    try:
                        shutil.copy2(os.path.join(font_folder, name),
                                     os.path.join(dest_dir, name))
                        copied += 1
                    except OSError:
                        continue
        return (dest_dir if copied else ""), font_file

    @staticmethod
    def _request_tex_fix(ai_client: AIClient, tex_path: str, compile_log: str) -> str:
        """Feeds the compile log back to the model so it can patch the .tex.
        Returns the corrected source (code fences stripped) or None."""
        try:
            with open(tex_path, "r", encoding="utf-8") as f:
                tex = f.read()
        except OSError:
            return None
        prompt = (
            "The XeLaTeX file below failed to compile. Fix the error and return "
            "the COMPLETE corrected .tex file — keep the preamble, box "
            "definitions, and colors exactly as they are.\n\n"
            f"Compile log tail:\n{compile_log.strip()[-2000:]}\n\n"
            f"LaTeX source:\n{tex}"
        )
        try:
            fixed = ai_client.complete(AINotesPipeline.SYSTEM_PROMPT, prompt)
        except AIClientError:
            return None
        fixed = re.sub(r"^```(?:latex|tex)?\s*", "", fixed.strip())
        fixed = re.sub(r"\s*```$", "", fixed)
        return fixed or None
