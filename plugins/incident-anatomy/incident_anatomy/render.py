"""Viewer data → one self-contained HTML page."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
from importlib import resources

from incident_anatomy.errors import AnatomyError

MERMAID = '<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'


def check_inline_scripts(page: str):
    """One bad escape in the page's single script kills every button: fail loudly when node
    is available rather than publish a dead page."""
    node = shutil.which("node")
    if not node:
        return
    for script in re.findall(r"<script>(.*?)</script>", page, re.S):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(script)
        result = subprocess.run([node, "--check", handle.name], capture_output=True, text=True)
        if result.returncode != 0:
            raise AnatomyError(f"the emitted script has a syntax error:\n{result.stderr}")


def render_html(data: dict) -> str:
    template = resources.files("incident_anatomy").joinpath("templates/viewer.html").read_text(encoding="utf-8")
    page = (
        template.replace("__LANG__", data["lang"])
        .replace("__TITLE__", html.escape(data["title"]))
        .replace("__DESCRIPTION__", html.escape(re.sub(r"[`*^]", "", data["lede"])[:300]))
        .replace("__MERMAID__", MERMAID if data["uses_mermaid"] else "")
        .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
    )
    check_inline_scripts(page)
    return page
