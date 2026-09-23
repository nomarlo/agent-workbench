"""Anatomy file → the data the viewer renders. Everything the page states about code or
numbers is resolved here from git and from data files, and fails loudly when it cannot be."""

from __future__ import annotations

import csv
import itertools
import re
from datetime import datetime
from pathlib import Path

from incident_anatomy.errors import AnatomyError
from incident_anatomy.excerpts import Source, annotate, diff_rows, excerpt, parse_patch, parse_ranges
from incident_anatomy.ui import strings

_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")
_UNSAFE_SVG = re.compile(r"<script|\son\w+\s*=|javascript:|<foreignObject", re.I)


def _fix_key(ids) -> str:
    return "+".join(sorted(ids))


def _file_lines(entry: dict, source: Source, base_dir: Path, where: str) -> list[str]:
    if entry.get("source", "git") == "git":
        if not source.has(entry["path"]):
            raise AnatomyError(f"{where}: {entry['path']} does not exist at {source.sha[:10]}")
        return source.lines(entry["path"])
    path = base_dir / entry["path"]
    if not path.is_file():
        raise AnatomyError(f"{where}: {path} does not exist")
    return path.read_text(encoding="utf-8").splitlines()


def _resolve_fixes(spec: dict, source: Source, base_dir: Path) -> list[dict]:
    fixes = []
    for index, fix in enumerate(spec.get("fixes", [])):
        where = f"fixes[{index}] ({fix['id']})"
        patch_path = base_dir / fix["patch"]
        if not patch_path.is_file():
            raise AnatomyError(f"{where}: patch {patch_path} does not exist")
        patches = parse_patch(patch_path.read_text(encoding="utf-8"), f"{where} {fix['patch']}")
        for patch in patches:
            if patch.creates:
                if source.has(patch.path):
                    raise AnatomyError(f"{where}: creates {patch.path}, which already exists at {source.sha[:10]}")
                continue
            if not source.has(patch.path):
                raise AnatomyError(f"{where}: changes {patch.path}, which does not exist at {source.sha[:10]}")
            annotate(source.lines(patch.path), patch.hunks, f"{where} on {patch.path}")
        fixes.append({**fix, "patches": patches})
    return fixes


def _resolve_files(spec: dict, source: Source, base_dir: Path, fixes: list[dict]) -> tuple[dict, dict]:
    toggles = [fix for fix in fixes if fix.get("toggle")]
    files, numbers_by_key = {}, {}
    for key, entry in spec["files"].items():
        where = f"files.{key}"
        lines = _file_lines(entry, source, base_dir, where)
        numbers = parse_ranges(entry["ranges"], where, len(lines))
        touching = [
            fix for fix in toggles
            if entry.get("source", "git") == "git" and any(p.path == entry["path"] for p in fix["patches"])
        ]
        variants = {}
        for size in range(len(touching) + 1):
            for subset in itertools.combinations(touching, size):
                hunks = [h for fix in subset for p in fix["patches"] if p.path == entry["path"] for h in p.hunks]
                rows = annotate(lines, hunks, f"{where} with {_fix_key(f['id'] for f in subset) or 'no fixes'}")
                variants[_fix_key(f["id"] for f in subset)] = excerpt(rows, numbers)
        files[key] = {
            "label": entry.get("label", entry["path"].rsplit("/", 1)[-1]),
            "path": entry["path"],
            "note": entry.get("note", ""),
            "touched_by": [fix["id"] for fix in touching],
            "variants": variants,
        }
        numbers_by_key[key] = numbers
    return files, numbers_by_key


def _check_line_refs(simulation: dict, files: dict, numbers_by_key: dict):
    for s_index, scenario in enumerate(simulation["scenarios"]):
        for index, step in enumerate(scenario["steps"]):
            where = f"simulation.scenarios[{s_index}].steps[{index}] ({step['title'][:40]!r})"
            refs = {step["file"]: step.get("lines", []), **step.get("also", {})}
            for key, lines in refs.items():
                file = files[key]
                variant = _fix_key(fix for fix in file["touched_by"] if fix in scenario["when"])
                rows = file["variants"][variant]
                for ref in lines:
                    if ref == "+":
                        if not any(row[1] == "+" for row in rows):
                            raise AnatomyError(
                                f"{where}: highlights the added lines of {file['label']}, but no fix active in "
                                f"this scenario adds lines inside its excerpt"
                            )
                    elif ref not in numbers_by_key[key]:
                        raise AnatomyError(
                            f"{where}: highlights {file['label']}:{ref}, which is outside the excerpt ranges "
                            f"of files.{key}"
                        )


def _x_value(text: str, kind: str, where: str) -> float:
    text = str(text).strip()
    if kind == "number":
        try:
            return float(text)
        except ValueError:
            raise AnatomyError(f"{where}: {text!r} is not a number") from None
    clock = _CLOCK.fullmatch(text)
    if clock:
        return int(clock[1]) * 60 + int(clock[2])
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise AnatomyError(f"{where}: {text!r} is neither HH:MM nor an ISO timestamp") from None
    return moment.timestamp() / 60


def _read_csv(path: Path, where: str) -> list[dict]:
    if not path.is_file():
        raise AnatomyError(f"{where}: data file {path} does not exist")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AnatomyError(f"{where}: {path} has no rows")
    return rows


def _resolve_chart(block: dict, base_dir: Path, where: str) -> dict:
    kind = block.get("x", {}).get("kind", "number")
    panels = []
    for index, panel in enumerate(block["panels"]):
        panel_where = f"{where}.panels[{index}]"
        rows = _read_csv(base_dir / panel["data"], panel_where)
        x_column = panel.get("x") or next(iter(rows[0]))
        for column in (x_column, panel["y"], panel.get("partial")):
            if column and column not in rows[0]:
                raise AnatomyError(f"{panel_where}: {panel['data']} has no column {column!r} (has {', '.join(rows[0])})")
        points = []
        for row_number, row in enumerate(rows, start=2):
            try:
                y = float(row[panel["y"]])
            except ValueError:
                raise AnatomyError(f"{panel_where}: {panel['data']}:{row_number}: {row[panel['y']]!r} is not a number") from None
            partial = bool(panel.get("partial")) and row[panel["partial"]].strip().lower() in {"1", "true", "yes"}
            points.append([_x_value(row[x_column], kind, f"{panel_where} {panel['data']}:{row_number}"), y, partial])
        panels.append({**panel, "points": points})
    markers = [{"x": _x_value(m["x"], kind, f"{where}.markers"), "label": m["label"]} for m in block.get("markers", [])]
    return {**block, "x": {"kind": kind, "label": block.get("x", {}).get("label", "")}, "panels": panels, "markers": markers}


def _resolve_table(block: dict, base_dir: Path, where: str) -> dict:
    if "data" not in block:
        return block
    path = base_dir / block["data"]
    if not path.is_file():
        raise AnatomyError(f"{where}: data file {path} does not exist")
    with path.open(newline="", encoding="utf-8") as handle:
        table = list(csv.reader(handle))
    header, rows = table[0], table[1:]
    return {**block, "columns": block.get("columns", header), "rows": rows}


def _resolve_figure(block: dict, base_dir: Path, where: str) -> dict:
    if "svg" not in block:
        return block
    path = base_dir / block["svg"]
    if not path.is_file():
        raise AnatomyError(f"{where}: svg {path} does not exist")
    svg = re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", path.read_text(encoding="utf-8")).strip()
    if _UNSAFE_SVG.search(svg):
        raise AnatomyError(f"{where}: {path} contains a script, an event handler or foreignObject")
    return {**block, "svg_markup": svg}


def _resolve_sections(spec: dict, base_dir: Path) -> list[dict]:
    resolvers = {"chart": _resolve_chart, "table": _resolve_table, "figure": _resolve_figure}
    sections = []
    for index, section in enumerate(spec.get("sections", [])):
        columns = section["columns"] if "columns" in section else [section["blocks"]]
        resolved = [
            [
                resolvers.get(block["type"], lambda b, _d, _w: b)(block, base_dir, f"sections[{index}] block {c}.{b}")
                for b, block in enumerate(column)
            ]
            for c, column in enumerate(columns)
        ]
        sections.append({"title": section["title"], "lede": section.get("lede", ""), "columns": resolved})
    return sections


def build(spec: dict, *, base_dir: Path, repo: Path) -> dict:
    lang = spec.get("lang", "en")
    ui = strings(lang, spec.get("ui", {}))
    source = Source(repo, spec.get("commit", "HEAD"))
    fixes = _resolve_fixes(spec, source, base_dir)
    files, numbers_by_key = _resolve_files(spec, source, base_dir, fixes)
    simulation = spec.get("simulation")
    if simulation:
        _check_line_refs(simulation, files, numbers_by_key)
    sections = _resolve_sections(spec, base_dir)
    return {
        "title": spec["title"],
        "eyebrow": spec.get("eyebrow", ""),
        "lede": spec.get("lede", ""),
        "lang": lang,
        "ui": ui,
        "facts": spec.get("facts", []),
        "commit": {"sha": source.sha, "short": source.sha[:10], "subject": source.subject},
        "files": files,
        "fixes": [
            {
                "id": fix["id"], "title": fix["title"], "toggle": fix.get("toggle", ""),
                "where": fix.get("where", ""), "why": fix.get("why", []), "diff": diff_rows(fix["patches"]),
            }
            for fix in fixes
        ],
        "simulation": simulation,
        "sections": sections,
        "sources": spec.get("sources", []),
        "uses_mermaid": any(
            block.get("type") == "figure" and "mermaid" in block
            for section in sections for column in section["columns"] for block in column
        ),
    }
