# -*- coding: utf-8 -*-
import os
import re
import subprocess
from jinja2 import Environment, FileSystemLoader

from notes.config import NOTES_DIR, TEMPLATES_DIR


class XeLaTeXCompiler:
    def __init__(self):
        self.output_dir = NOTES_DIR
        self.template_dir = TEMPLATES_DIR

        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            block_start_string="[%", block_end_string="%]",
            variable_start_string="[[", variable_end_string="]]",
            comment_start_string="[#", comment_end_string="#]",
        )

    def sanitize_latex(self, text: str) -> str:
        """Escapes special LaTeX characters to prevent parser breakage."""
        chars_to_escape = {
            "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}",
        }
        regex = re.compile("|".join(re.escape(str(key)) for key in chars_to_escape.keys()))
        return regex.sub(lambda match: chars_to_escape[match.group(0)], text)

    def generate_standard_filename(self, subject: str, topic: str, file_type: str, ext: str) -> str:
        """Standardized naming convention enforcement."""
        clean_sub = "".join(c for c in subject if c.isalnum())
        clean_top = "".join(c for c in topic if c.isalnum())
        return f"{clean_sub}_{clean_top}_{file_type}.{ext}"

    def compile_note(self, subject: str, topic: str, date_str: str, raw_content: str, math_formula: str = ""):
        """Injects text into Jinja template and generates LaTeX file."""
        clean_content = self.sanitize_latex(raw_content)
        template = self.env.get_template("lecture_note.tex")

        rendered_tex = template.render(
            subject=subject,
            topic=topic,
            date=date_str,
            content=clean_content,
            math_formula=math_formula,
        )

        tex_filename = self.generate_standard_filename(subject, topic, "Note", "tex")
        tex_path = os.path.join(self.output_dir, tex_filename)

        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(rendered_tex)

        if subprocess.run(["which", "xelatex"], stdout=subprocess.PIPE).returncode == 0:
            cmd = ["xelatex", "-interaction=nonstopmode",
                   f"-output-directory={self.output_dir}", tex_path]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            pdf_path = tex_path.replace(".tex", ".pdf")
            return pdf_path, tex_path
        print("⚠️ Warning: 'xelatex' CLI not found on system path. .tex file generated successfully.")
        return None, tex_path

    def compile_arbitrary_tex(self, tex_path: str, runs: int = 2):
        """Compiles an existing .tex into a PDF with XeLaTeX, running from the
        file's own directory so relative \\input/\\include/image paths resolve.

        Returns:
            (success: bool, pdf_path: str | None, log: str)
        """
        if not tex_path or not os.path.exists(tex_path):
            return False, None, "File not found."

        if not tex_path.lower().endswith(".tex"):
            return False, None, "Selected file is not a .tex file."

        if subprocess.run(["which", "xelatex"], stdout=subprocess.PIPE).returncode != 0:
            return False, None, ("'xelatex' was not found on the system PATH. "
                                 "Install a TeX distribution (e.g. `sudo apt install texlive-xetex`) and try again.")

        work_dir = os.path.dirname(os.path.abspath(tex_path))
        filename = os.path.basename(tex_path)
        pdf_path = os.path.join(work_dir, os.path.splitext(filename)[0] + ".pdf")

        log_output = ""
        for _ in range(max(1, runs)):
            try:
                result = subprocess.run(
                    ["xelatex", "-interaction=nonstopmode", "-halt-on-error", filename],
                    cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=120,
                )
                log_output = result.stdout or ""
            except subprocess.TimeoutExpired:
                return False, None, ("XeLaTeX timed out after 120 seconds "
                                     "(possible infinite loop or missing package prompt).")

        if os.path.exists(pdf_path):
            return True, pdf_path, log_output
        return False, None, log_output


if __name__ == "__main__":
    compiler = XeLaTeXCompiler()
    pdf_path, tex_path = compiler.compile_note(
        subject="CSE1133",
        topic="Pointers_and_Memory",
        date_str="2026-07-31",
        raw_content="Pointer is a variable that stores memory address of another variable.",
        math_formula="x = &y",
    )
    print(f"✅ XeLaTeX Compiler module verified! TeX File: {tex_path}")
