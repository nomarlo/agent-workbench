"""Signature extraction over text.

Text, not AST, on purpose: the same functions read real source files and the fenced code
blocks of a plan, which are fragments that would not parse on their own.
"""

from __future__ import annotations

import re

MEMBER_CAP = 24


def sanitize_mermaid(text: str) -> str:
    text = re.sub(r"\s*\|\s*None", "?", text)
    return (
        text.replace("|", " or ")
        .replace("[", "~")
        .replace("]", "~")
        .replace('"', "")
        .replace("{", "")
        .replace("}", "")
    )


def _rank_and_render(entries: list[tuple[str, int, str]], priority: set[str]) -> list[str]:
    """entries: (name, kind, rendered), kind 0 = callable or class, 1 = constant or type.
    Branch-added symbols first, then callables, then constants; overflow collapses into
    one counter line instead of silently dropping members."""
    ranked = sorted(
        enumerate(entries),
        key=lambda pair: (pair[1][0] not in priority, pair[1][1], pair[0]),
    )
    rendered = [entry[2] for _, entry in ranked]
    if len(rendered) > MEMBER_CAP:
        rendered = rendered[:MEMBER_CAP] + [f".. {len(rendered) - MEMBER_CAP} more .."]
    return rendered


def python_members(lines: list[str], priority: set[str] | None = None) -> list[str]:
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]
        const = re.match(r"^([A-Z][A-Z0-9_]{2,})\s*[:=]", line)
        if const:
            entries.append((const.group(1), 1, f"+{const.group(1)}"))
        klass = re.match(r"^class (\w+)", line)
        if klass:
            entries.append((klass.group(1), 0, f"+class {klass.group(1)}"))
        func = re.match(r"^(?:    )?(?:async )?def (\w+)\(", line)
        if func:
            signature = line
            while (
                "):" not in signature
                and ") ->" not in signature
                and i + 1 < len(lines)
                and len(signature) < 400
            ):
                i += 1
                signature += " " + lines[i].strip()
            params = re.search(
                r"\((.*?)\)", signature.replace("(self, ", "(").replace("(self)", "()")
            )
            params_text = params.group(1) if params else ""
            # strip bracketed generics before splitting, or Mapping[str, str] sheds a
            # phantom "str]" parameter
            while re.search(r"\[[^\[\]]*\]", params_text):
                params_text = re.sub(r"\[[^\[\]]*\]", "", params_text)
            names = [
                part.split(":")[0].split("=")[0].strip().lstrip("*")
                for part in params_text.split(",")
            ]
            names = [name for name in names if name and name not in ("self", "cls")]
            returns = re.search(r"->\s*([^:#]+?)\s*(?::|#|$)", signature)
            visibility = "-" if func.group(1).startswith("_") else "+"
            member = f"{visibility}{func.group(1)}({', '.join(names[:5])})"
            if returns:
                member += " " + sanitize_mermaid(returns.group(1).strip())
            entries.append((func.group(1), 0, member))
        i += 1
    return _rank_and_render(entries, priority or set())


def typescript_members(lines: list[str], priority: set[str] | None = None) -> list[str]:
    entries = []
    for line in lines:
        exported_const = re.match(r"^export const (\w+)\s*(=.{0,20})?", line)
        exported_type = re.match(r"^export (?:type|interface) (\w+)", line)
        exported_class = re.match(r"^export (?:default )?class (\w+)", line)
        local = re.match(r"^const (\w+)\s*=\s*(async )?(\()?", line)
        func = re.match(r"^(export )?(?:default )?(async )?function (\w+)\(", line)
        if exported_const:
            is_function = "(" in (exported_const.group(2) or "") or "=>" in line
            entries.append(
                (
                    exported_const.group(1),
                    0 if is_function else 1,
                    f"+{exported_const.group(1)}" + ("()" if is_function else ""),
                )
            )
        elif exported_type:
            entries.append((exported_type.group(1), 1, f"+type {exported_type.group(1)}"))
        elif exported_class:
            entries.append((exported_class.group(1), 0, f"+class {exported_class.group(1)}"))
        elif func:
            visibility = "+" if func.group(1) else "-"
            entries.append((func.group(3), 0, f"{visibility}{func.group(3)}()"))
        elif local:
            is_function = "=>" in line or bool(local.group(3))
            entries.append(
                (
                    local.group(1),
                    0 if is_function else 1,
                    f"-{local.group(1)}" + ("()" if is_function else ""),
                )
            )
    return _rank_and_render(entries, priority or set())


def members_of(path: str, lines: list[str], priority: set[str] | None = None) -> list[str]:
    if path.endswith((".ts", ".tsx", ".js", ".jsx")):
        return typescript_members(lines, priority)
    return python_members(lines, priority)
