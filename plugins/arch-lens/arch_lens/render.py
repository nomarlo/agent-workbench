"""Model → one self-contained HTML page."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import resources

from arch_lens.members import sanitize_mermaid


def class_diagram(model: dict) -> str:
    lines = ["classDiagram", "direction TB"]
    class_names: dict[str, str] = {}
    plan_only = model["plan_only"]
    for lane in model["lanes"]:
        lane_nodes = [
            n for n in model["nodes"]
            if n["layer"] == lane
            and n["build"] != "external"
            and (n["build"] != "missing" or plan_only or n.get("planned_members"))
        ]
        if not lane_nodes:
            continue
        lines.append(f"namespace {re.sub(r'[^A-Za-z0-9_]', '_', lane).title()} {{")
        for node in lane_nodes:
            name = re.sub(r"\W", "_", node["label"].rsplit(".", 1)[0]) + "_" + node["id"]
            class_names[node["id"]] = name
            lines.append(f'    class {name}["{sanitize_mermaid(node["label"])}"] {{')
            stereotype = f"planned · {node['group']}" if node["build"] == "missing" else node["group"]
            lines.append(f"        <<{sanitize_mermaid(stereotype)}>>")
            members = (node.get("planned_members") or node["members"]) if plan_only or node["build"] == "missing" else node["members"]
            for member in members:
                lines.append(f"        {sanitize_mermaid(member)}")
            lines.append("    }")
        lines.append("}")
    for edge in model["edges"]:
        if edge["f"] in class_names and edge["t"] in class_names:
            label = sanitize_mermaid(edge["label"])[:40].replace(":", " ") if edge["label"] else ""
            lines.append(
                f"{class_names[edge['f']]} ..> {class_names[edge['t']]}" + (f" : {label}" if label else "")
            )
    return "\n".join(lines)


def _json_for_script(value) -> str:
    return json.dumps(value).replace("<", "\\u003c")


def check_inline_scripts(html: str):
    """One bad escape in the page's single script kills every button; fail loudly when
    node is available rather than publish a dead page."""
    node = shutil.which("node")
    if not node:
        return
    for script in re.findall(r"<script>(.*?)</script>", html, re.S):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(script)
        result = subprocess.run([node, "--check", handle.name], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[arch-lens] the emitted script has a syntax error:\n{result.stderr}", file=sys.stderr)
            raise SystemExit(2)


def render_html(model: dict) -> str:
    template = resources.files("arch_lens").joinpath("templates/viewer.html").read_text(encoding="utf-8")
    html = (
        template.replace("__TITLE__", f"Arch Lens · {model['slug']}".replace("<", "&lt;"))
        .replace("__CLASS_MERMAID__", _json_for_script(class_diagram(model)))
        .replace("__DATA__", _json_for_script(model))
    )
    check_inline_scripts(html)
    return html
