"""Reading a plan written before the code exists.

The plan is plain markdown with three optional parts (see docs/plan-format.md):
  - a "Changes by layer" table whose backticked paths are the files the plan will touch;
  - a "Public interface" section whose fenced code blocks sketch the planned signatures,
    each block attributed to the last backticked file path written before it;
  - fenced ```mermaid sequenceDiagram blocks anywhere: the planned flows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from arch_lens.config import PlanConfig
from arch_lens.members import members_of

SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx")
PATH_TOKEN = re.compile(r"`([^`\s]+\.(?:py|tsx?|jsx?))`")
SEGMENT_COMMENT = re.compile(r"^\s*(?:#|//)\s*(\S+\.(?:py|tsx?|jsx?))\b")


@dataclass
class PlannedInterface:
    members: list[str] = field(default_factory=list)
    text: str = ""


@dataclass
class Plan:
    path: Path
    files: set[str]
    interface: dict[str, PlannedInterface]
    flows: list[dict]


def same_file(path: str, planned: str) -> bool:
    """A planned piece with a directory matches on a path-segment suffix; a bare filename
    matches on basename. `views/orders.py` and `serializers/orders.py` are two files."""
    if "/" in planned:
        return path == planned or path.endswith("/" + planned)
    return path.rsplit("/", 1)[-1] == planned


def _heading_is(line: str, heading: str) -> bool:
    return line.lstrip("#").strip().lower() == heading.lower()


def _qualify(piece: str, layer_cell: str, prefixes: dict[str, str]) -> str:
    """Plans often write paths relative to their deployable; the table's first column says
    which one. A configured prefix whose key appears in that cell places the piece."""
    for key, prefix in prefixes.items():
        if key.lower() in layer_cell and not piece.startswith(prefix):
            return prefix + piece
    return piece


def parse_files(text: str, config: PlanConfig) -> set[str]:
    planned, in_table = set(), False
    for line in text.splitlines():
        if line.startswith("#"):
            in_table = _heading_is(line, config.changes_heading)
            continue
        if not (in_table and line.startswith("|")):
            continue
        cells = line.split("|")
        layer_cell = cells[1].strip().lower() if len(cells) > 2 else ""
        for token in re.findall(r"`([^`]+)`", line):
            for piece in re.split(r"[\s,]+", token):
                piece = piece.strip("()+")
                if piece.endswith(SOURCE_SUFFIXES):
                    planned.add(_qualify(piece, layer_cell, config.prefixes))
    return planned


def parse_interface(text: str, config: PlanConfig, planned: set[str]) -> dict[str, PlannedInterface]:
    interface: dict[str, PlannedInterface] = {}
    in_section = in_fence = False
    fence_lang, fence_lines, current = "", [], None

    def attach(path_key: str | None, lang: str, lines: list[str]):
        if not path_key or not lines:
            return
        as_path = path_key if path_key.endswith(SOURCE_SUFFIXES) else f"x.{'ts' if lang.startswith(('ts', 'js')) else 'py'}"
        entry = interface.setdefault(path_key, PlannedInterface())
        entry.members += [m for m in members_of(as_path, lines) if m not in entry.members]
        entry.text += "\n" + "\n".join(lines)

    def flush(lang: str, lines: list[str]):
        segment_key, segment = current, []
        for line in lines:
            switch = SEGMENT_COMMENT.match(line)
            if switch:
                attach(segment_key, lang, segment)
                segment_key, segment = switch.group(1), []
                continue
            segment.append(line)
        attach(segment_key, lang, segment)

    for line in text.splitlines():
        if line.startswith("#") and not in_fence:
            in_section = _heading_is(line, config.interface_heading)
            continue
        if not in_section:
            continue
        if line.startswith("```"):
            if in_fence:
                flush(fence_lang, fence_lines)
                in_fence, fence_lines = False, []
            else:
                in_fence, fence_lang, fence_lines = True, line[3:].strip().lower(), []
            continue
        if in_fence:
            fence_lines.append(line)
            continue
        tokens = PATH_TOKEN.findall(line)
        if planned:
            tokens = [
                token for token in tokens
                if any(same_file(path, token) or path.endswith(token) for path in planned)
            ]
        if tokens:
            current = tokens[-1]
    return interface


def parse_flows(text: str) -> list[dict]:
    flows, in_fence, fence_lines, heading = [], False, [], "flow"
    for line in text.splitlines():
        if line.startswith("#") and not in_fence:
            heading = line.lstrip("# ").strip()
        if line.startswith("```"):
            if in_fence:
                body = "\n".join(fence_lines).strip()
                if body.startswith("sequenceDiagram"):
                    flows.append({"label": heading[:60], "mermaid": body, "source": "plan"})
                in_fence, fence_lines = False, []
            elif line[3:].strip().lower().startswith("mermaid"):
                in_fence, fence_lines = True, []
            continue
        if in_fence:
            fence_lines.append(line)
    return flows


def load_plan(path: Path, config: PlanConfig) -> Plan:
    text = path.read_text(encoding="utf-8", errors="replace")
    files = parse_files(text, config)
    return Plan(
        path=path,
        files=files,
        interface=parse_interface(text, config, files),
        flows=parse_flows(text),
    )
