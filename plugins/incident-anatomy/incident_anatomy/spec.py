"""The anatomy file: its shape, checked strictly, because a key the viewer silently
ignores is a claim the author thinks is on the page and is not."""

from __future__ import annotations

import json
import re
from pathlib import Path

from incident_anatomy.errors import AnatomyError

TONES = {"bad", "leak", "fixed"}
CELL_TONES = {"ok", "warn", "bad"}
TIMELINE_TONES = {"key", "alert", "dim"}
LANGUAGES = {"en", "es"}

# Names a simulation string may use as {name}; arithmetic over k ({k-1}, {2*k}) is also allowed.
PLACEHOLDERS = {"k", "head", "count", "n", "value", "left", "left_time", "unit", "iteration", "retained"}
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_ARITHMETIC = re.compile(r"[\dk+\-*() ]+")

_SHAPES: dict[str, tuple[set[str], set[str]]] = {
    # object kind: (required keys, optional keys)
    "anatomy": ({"title", "files"}, {"eyebrow", "lede", "lang", "ui", "repo", "commit", "facts", "fixes",
                                    "simulation", "sections", "sources"}),
    "fact": ({"label", "value"}, set()),
    "file": ({"path", "ranges"}, {"label", "source", "note"}),
    "fix": ({"id", "title", "patch"}, {"toggle", "where", "why"}),
    "simulation": ({"scenarios"}, {"title", "lede", "iteration", "seconds_per_iteration", "jumps", "block_label",
                                   "meter", "vars", "chain", "note"}),
    "jump": ({"label", "iterations"}, set()),
    "meter": ({"label", "base", "max"}, {"unit", "limit", "limit_label", "base_label", "decimals", "notes"}),
    "notes": (set(), {"idle", "growing", "limit", "flat"}),
    "chain": (set(), {"title", "owner", "anchor", "none", "empty", "empty_fixed", "more", "link", "summary"}),
    "scenario": ({"when", "name", "steps"}, {"repeats", "meter_per_iteration", "notes"}),
    "step": ({"title", "file"}, {"tag", "tone", "block", "lines", "also", "detail", "vars", "retain",
                                 "transient", "meter", "first"}),
    "first": (set(), {"title", "tag", "detail"}),
    "item": ({"title"}, {"meta"}),
    "transient": ({"title"}, {"meta", "freed"}),
    "var": ({"value"}, {"tone"}),
    "section": ({"title"}, {"lede", "blocks", "columns"}),
    "prose": ({"type"}, {"title", "paragraphs", "card"}),
    "figure": ({"type"}, {"mermaid", "svg", "caption", "card"}),
    "chart": ({"type", "panels"}, {"x", "markers", "caption", "card"}),
    "panel": ({"kind", "data", "y"}, {"x", "partial", "label", "unit", "min", "max", "threshold"}),
    "threshold": ({"y"}, {"label"}),
    "marker": ({"x", "label"}, set()),
    "axis": (set(), {"kind", "label"}),
    "timeline": ({"type", "items"}, {"title", "card"}),
    "event": ({"t", "text"}, {"tone"}),
    "table": ({"type"}, {"title", "lede", "columns", "rows", "data", "card"}),
    "cell": ({"text"}, {"tone"}),
    "fixes": ({"type"}, {"card"}),
}


def _shape(obj, kind: str, where: str) -> dict:
    if not isinstance(obj, dict):
        raise AnatomyError(f"{where}: expected an object ({kind})")
    required, optional = _SHAPES[kind]
    missing = sorted(required - obj.keys())
    if missing:
        raise AnatomyError(f"{where}: missing {', '.join(missing)}")
    unknown = sorted(obj.keys() - required - optional)
    if unknown:
        raise AnatomyError(f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(required | optional))})")
    return obj


def _list(value, where: str) -> list:
    if not isinstance(value, list):
        raise AnatomyError(f"{where}: expected a list")
    return value


def _text(value, where: str) -> str:
    if not isinstance(value, str):
        raise AnatomyError(f"{where}: expected a string")
    return value


def _number(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnatomyError(f"{where}: expected a number")
    return value


def _one_of(value, allowed: set[str], where: str):
    if value not in allowed:
        raise AnatomyError(f"{where}: {value!r} is not one of {', '.join(sorted(allowed))}")


def check_placeholders(text: str, where: str):
    for name in _PLACEHOLDER.findall(text):
        name = name.strip()
        if name not in PLACEHOLDERS and not _ARITHMETIC.fullmatch(name):
            raise AnatomyError(
                f"{where}: unknown placeholder {{{name}}} (known: {', '.join(sorted(PLACEHOLDERS))}, "
                "or arithmetic over k such as {k-1} or {2*k})"
            )


def _simulation_text(value, where: str) -> str:
    check_placeholders(_text(value, where), where)
    return value


def _line_refs(value, where: str):
    for ref in _list(value, where):
        if ref != "+" and (isinstance(ref, bool) or not isinstance(ref, int)):
            raise AnatomyError(f"{where}: line references are line numbers or \"+\" (the fix's added lines)")


def _validate_step(step, file_keys: set[str], variables: set[str], where: str):
    _shape(step, "step", where)
    for key in ("title", "tag", "detail"):
        if key in step:
            _simulation_text(step[key], f"{where}.{key}")
    if step["file"] not in file_keys:
        raise AnatomyError(f"{where}.file: {step['file']!r} is not a key of files")
    if "tone" in step:
        _one_of(step["tone"], TONES, f"{where}.tone")
    _line_refs(step.get("lines", []), f"{where}.lines")
    for key, refs in _shape_map(step.get("also", {}), f"{where}.also").items():
        if key not in file_keys:
            raise AnatomyError(f"{where}.also: {key!r} is not a key of files")
        _line_refs(refs, f"{where}.also.{key}")
    for name, value in _shape_map(step.get("vars", {}), f"{where}.vars").items():
        if name not in variables:
            raise AnatomyError(f"{where}.vars: {name!r} is not declared in simulation.vars")
        if isinstance(value, dict):
            _shape(value, "var", f"{where}.vars.{name}")
            _simulation_text(value["value"], f"{where}.vars.{name}.value")
            if "tone" in value:
                _one_of(value["tone"], TONES, f"{where}.vars.{name}.tone")
        else:
            _simulation_text(value, f"{where}.vars.{name}")
    for index, item in enumerate(_list(step.get("retain", []), f"{where}.retain")):
        _shape(item, "item", f"{where}.retain[{index}]")
        for key in item:
            _simulation_text(item[key], f"{where}.retain[{index}].{key}")
    if "transient" in step:
        transient = _shape(step["transient"], "transient", f"{where}.transient")
        _simulation_text(transient["title"], f"{where}.transient.title")
    if "first" in step:
        for key, value in _shape(step["first"], "first", f"{where}.first").items():
            _simulation_text(value, f"{where}.first.{key}")


def _shape_map(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise AnatomyError(f"{where}: expected an object")
    return value


def _validate_simulation(simulation, file_keys: set[str], toggle_ids: set[str]):
    _shape(simulation, "simulation", "simulation")
    variables = set(_list(simulation.get("vars", []), "simulation.vars"))
    for index, jump in enumerate(_list(simulation.get("jumps", []), "simulation.jumps")):
        _shape(jump, "jump", f"simulation.jumps[{index}]")
        _number(jump["iterations"], f"simulation.jumps[{index}].iterations")
    if "meter" in simulation:
        meter = _shape(simulation["meter"], "meter", "simulation.meter")
        for key in ("base", "max", "limit"):
            if key in meter:
                _number(meter[key], f"simulation.meter.{key}")
        for key, value in _shape(meter.get("notes", {}), "notes", "simulation.meter.notes").items():
            _simulation_text(value, f"simulation.meter.notes.{key}")
    if "chain" in simulation:
        for key, value in _shape(simulation["chain"], "chain", "simulation.chain").items():
            _simulation_text(value, f"simulation.chain.{key}")
    scenarios = _list(simulation["scenarios"], "simulation.scenarios")
    seen = set()
    for index, scenario in enumerate(scenarios):
        where = f"simulation.scenarios[{index}]"
        _shape(scenario, "scenario", where)
        when = frozenset(_list(scenario["when"], f"{where}.when"))
        unknown = sorted(when - toggle_ids)
        if unknown:
            raise AnatomyError(f"{where}.when: {', '.join(unknown)} are not ids of fixes with a toggle")
        if when in seen:
            raise AnatomyError(f"{where}.when: another scenario already covers {sorted(when) or 'no fixes'}")
        seen.add(when)
        if "meter_per_iteration" in scenario:
            _number(scenario["meter_per_iteration"], f"{where}.meter_per_iteration")
        for key, value in _shape(scenario.get("notes", {}), "notes", f"{where}.notes").items():
            _simulation_text(value, f"{where}.notes.{key}")
        steps = _list(scenario["steps"], f"{where}.steps")
        if not steps:
            raise AnatomyError(f"{where}.steps: a scenario needs at least one step")
        for step_index, step in enumerate(steps):
            _validate_step(step, file_keys, variables, f"{where}.steps[{step_index}]")
    if frozenset() not in seen:
        raise AnatomyError("simulation.scenarios: one scenario must have \"when\": [] (the incident as it happened)")


def _validate_block(block, fix_count: int, where: str):
    if not isinstance(block, dict) or block.get("type") not in {"prose", "figure", "chart", "timeline", "table", "fixes"}:
        raise AnatomyError(f"{where}: a block needs a type: prose, figure, chart, timeline, table or fixes")
    kind = block["type"]
    _shape(block, kind, where)
    if kind == "figure" and ("mermaid" in block) == ("svg" in block):
        raise AnatomyError(f"{where}: a figure has exactly one of mermaid or svg")
    if kind == "chart":
        _shape(block.get("x", {}), "axis", f"{where}.x")
        if "kind" in block.get("x", {}):
            _one_of(block["x"]["kind"], {"number", "time"}, f"{where}.x.kind")
        panels = _list(block["panels"], f"{where}.panels")
        if not panels:
            raise AnatomyError(f"{where}.panels: at least one panel")
        for index, panel in enumerate(panels):
            _shape(panel, "panel", f"{where}.panels[{index}]")
            _one_of(panel["kind"], {"line", "bar"}, f"{where}.panels[{index}].kind")
            if "threshold" in panel:
                _shape(panel["threshold"], "threshold", f"{where}.panels[{index}].threshold")
        for index, marker in enumerate(_list(block.get("markers", []), f"{where}.markers")):
            _shape(marker, "marker", f"{where}.markers[{index}]")
    if kind == "timeline":
        for index, event in enumerate(_list(block["items"], f"{where}.items")):
            _shape(event, "event", f"{where}.items[{index}]")
            if "tone" in event:
                _one_of(event["tone"], TIMELINE_TONES, f"{where}.items[{index}].tone")
    if kind == "table":
        if ("rows" in block) == ("data" in block):
            raise AnatomyError(f"{where}: a table has exactly one of rows or data (a CSV file)")
        if "rows" in block and "columns" not in block:
            raise AnatomyError(f"{where}: a table with rows needs columns")
        for row_index, row in enumerate(_list(block.get("rows", []), f"{where}.rows")):
            if len(_list(row, f"{where}.rows[{row_index}]")) != len(block["columns"]):
                raise AnatomyError(f"{where}.rows[{row_index}]: {len(row)} cells for {len(block['columns'])} columns")
            for cell_index, cell in enumerate(row):
                if isinstance(cell, dict):
                    _shape(cell, "cell", f"{where}.rows[{row_index}][{cell_index}]")
                    if "tone" in cell:
                        _one_of(cell["tone"], CELL_TONES, f"{where}.rows[{row_index}][{cell_index}].tone")
    if kind == "fixes" and not fix_count:
        raise AnatomyError(f"{where}: a fixes block with no fixes declared")


def validate(spec: dict):
    _shape(spec, "anatomy", "anatomy")
    if "lang" in spec:
        _one_of(spec["lang"], LANGUAGES, "lang")
    for key, value in _shape_map(spec.get("ui", {}), "ui").items():
        _text(value, f"ui.{key}")
    for index, fact in enumerate(_list(spec.get("facts", []), "facts")):
        _shape(fact, "fact", f"facts[{index}]")
    files = _shape_map(spec["files"], "files")
    if not files:
        raise AnatomyError("files: at least one file")
    for key, entry in files.items():
        _shape(entry, "file", f"files.{key}")
        _list(entry["ranges"], f"files.{key}.ranges")
        if "source" in entry:
            _one_of(entry["source"], {"git", "disk"}, f"files.{key}.source")
    fixes = _list(spec.get("fixes", []), "fixes")
    ids = set()
    for index, fix in enumerate(fixes):
        _shape(fix, "fix", f"fixes[{index}]")
        if fix["id"] in ids:
            raise AnatomyError(f"fixes[{index}]: duplicate id {fix['id']!r}")
        ids.add(fix["id"])
        _list(fix.get("why", []), f"fixes[{index}].why")
    toggle_ids = {fix["id"] for fix in fixes if fix.get("toggle")}
    if len(toggle_ids) > 4:
        raise AnatomyError("fixes: at most 4 fixes can have a toggle")
    if "simulation" in spec:
        _validate_simulation(spec["simulation"], set(files), toggle_ids)
    for index, section in enumerate(_list(spec.get("sections", []), "sections")):
        _shape(section, "section", f"sections[{index}]")
        if ("blocks" in section) == ("columns" in section):
            raise AnatomyError(f"sections[{index}]: a section has exactly one of blocks or columns")
        columns = section["columns"] if "columns" in section else [section["blocks"]]
        for column_index, column in enumerate(_list(columns, f"sections[{index}].columns")):
            for block_index, block in enumerate(_list(column, f"sections[{index}] column {column_index}")):
                _validate_block(block, len(fixes), f"sections[{index}] block {column_index}.{block_index}")
    for index, source in enumerate(_list(spec.get("sources", []), "sources")):
        _text(source, f"sources[{index}]")


def load(path: Path) -> dict:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AnatomyError(f"{path}: no such file") from None
    except json.JSONDecodeError as error:
        raise AnatomyError(f"{path}:{error.lineno}:{error.colno}: {error.msg}") from None
    validate(spec)
    return spec
