"""The page's model: nodes, edges and flows in one schema (schema/model.schema.json).

Extractors contribute nodes and edges; this module merges them, lays the plan over the
as-built delta, pins review findings and marks the edges that break the layer order.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from arch_lens.config import Config
from arch_lens.git import Git
from arch_lens.members import members_of
from arch_lens.plan import Plan, same_file
from arch_lens.python_extractor import PythonCodebase, read_lines

TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
REGISTRY_FANOUT = 8


class ModelBuilder:
    def __init__(self, config: Config):
        self.config = config
        self.nodes: list[dict] = []
        self.by_path: dict[str, dict] = {}
        self.edges: list[dict] = []

    def lane_of(self, path: str, lang: str) -> str:
        layer = self.config.layer_of(path)
        if layer:
            return layer
        return self.config.group_of(path) if lang == "ts" else "other"

    def add_node(self, path: str, build: str, lang: str, **extra) -> dict:
        if path in self.by_path:
            node = self.by_path[path]
            if build == "changed":
                node["build"] = "changed"
            node.update({k: v for k, v in extra.items() if v is not None})
            return node
        node = {
            "id": f"n{len(self.nodes)}",
            "path": path,
            "label": extra.pop("label", None) or path.rsplit("/", 1)[-1],
            "layer": extra.pop("layer", None) or self.lane_of(path, lang),
            "group": extra.pop("group", None) or ("external" if build == "external" else self.config.group_of(path)),
            "lang": lang,
            "build": build,
            "plan": None,
            "members": [],
            "findings": [],
        }
        node.update({k: v for k, v in extra.items() if v is not None})
        self.nodes.append(node)
        self.by_path[path] = node
        return node

    def add_edge(self, source: dict, target: dict, kind: str, label: str = "", **extra):
        if source["id"] == target["id"]:
            return
        for edge in self.edges:
            if edge["f"] == source["id"] and edge["t"] == target["id"] and edge["kind"] == kind:
                return
        self.edges.append({"f": source["id"], "t": target["id"], "kind": kind, "label": label, **extra})


def _python_part(builder: ModelBuilder, codebase: PythonCodebase, changed: list[str]):
    changed_py = [path for path in changed if codebase.owns(path)]
    changed_modules = {codebase.module_of(path): path for path in changed_py}
    reused_paths: set[str] = set()
    for path in changed_py:
        source = builder.by_path[path]
        for module, label in codebase.internal_imports(path):
            target_path = next(
                (p for m, p in changed_modules.items() if m and (module == m or module.startswith(m + "."))),
                None,
            )
            if target_path is None:
                target_path = codebase.path_of(module)
                if not target_path:
                    continue
                if target_path.endswith("__init__.py") and module not in codebase.python.collapse_imports:
                    continue  # a package re-export hub says nothing about the design
                reused_paths.add(target_path)
                builder.add_node(target_path, "reused", "py", label=module)
            builder.add_edge(source, builder.by_path[target_path], "import", label)
    return reused_paths


def _prune_registry_fanout(builder: ModelBuilder, reused_paths: set[str]):
    """A registry module (a urls.py, a task index) imports dozens of modules; drawing every
    reused neighbour it alone references drowns the diagram. Such a file keeps its edges to
    changed nodes and to reused neighbours some other changed file also references."""
    reused_ids = {builder.by_path[p]["id"] for p in reused_paths}
    for source_id in {e["f"] for e in builder.edges}:
        to_reused = [e for e in builder.edges if e["f"] == source_id and e["t"] in reused_ids]
        if len(to_reused) <= REGISTRY_FANOUT:
            continue
        for edge in to_reused:
            if not any(e["t"] == edge["t"] and e["f"] != source_id for e in builder.edges):
                builder.edges.remove(edge)
    referenced = {e["t"] for e in builder.edges} | {e["f"] for e in builder.edges}
    kept = [n for n in builder.nodes if n["build"] != "reused" or n["id"] in referenced or n["lang"] == "ts"]
    builder.nodes[:] = kept
    builder.by_path = {n["path"]: n for n in kept}


def _external_markers(builder: ModelBuilder, changed: list[str]):
    for path in changed:
        node = builder.by_path.get(path)
        if node is None:
            continue
        text = (builder.config.repo_root / path).read_text(encoding="utf-8", errors="replace")
        for marker in builder.config.externals:
            if all(re.search(pattern, text) for pattern in marker.all):
                target = builder.add_node(f"external:{marker.label}", "external", "ext",
                                          label=marker.label, layer="external", group="external")
                builder.add_edge(node, target, "external", "calls")


def _typescript_part(builder: ModelBuilder, graph: dict):
    id_of_ts = {}
    for ts_node in graph["nodes"]:
        path = ts_node["id"]
        if ts_node.get("external"):
            node = builder.add_node(f"external:{ts_node['label']}", "external", "ext",
                                    label=ts_node["label"], layer="external", group="external")
        else:
            node = builder.add_node(
                path,
                "changed" if ts_node.get("changed") else "reused",
                "ts",
                label=ts_node.get("label"),
                group=ts_node.get("pkg"),
                ts={k: ts_node.get(k) for k in ("distance", "hub", "seed", "viaPort", "inDelta") if ts_node.get(k) is not None},
            )
        id_of_ts[path] = node
    for edge in graph["edges"]:
        source, target = id_of_ts.get(edge["from"]), id_of_ts.get(edge["to"])
        if not source or not target:
            continue
        symbols = edge.get("symbols", [])
        label = ", ".join(s["symbol"] for s in symbols[:2]) + (f" +{len(symbols) - 2}" if len(symbols) > 2 else "")
        builder.add_edge(source, target, edge["kind"], label, symbols=symbols, sites=edge.get("sites", [])[:12])
    for path, contract in graph.get("contracts", {}).items():
        if path in builder.by_path:
            builder.by_path[path]["contract"] = contract
    for path, functions in graph.get("functionsByFile", {}).items():
        if path in builder.by_path:
            builder.by_path[path]["functions"] = functions


def _plan_overlay(builder: ModelBuilder, plan: Plan):
    for node in builder.nodes:
        if node["build"] == "changed":
            node["plan"] = "planned" if any(same_file(node["path"], p) for p in plan.files) else "unplanned"
    for piece in sorted(plan.files):
        if "migrations" in piece or any(same_file(n["path"], piece) for n in builder.nodes):
            continue
        builder.add_node(piece, "missing", "ts" if piece.endswith(TS_SUFFIXES) else "py", plan="missing")

    for key, entry in plan.interface.items():
        for node in builder.nodes:
            matched = (
                node["path"].endswith(key) or key.endswith(node["path"])
                if "/" in key
                else node["path"].rsplit("/", 1)[-1] == key.rsplit("/", 1)[-1]
            )
            if matched:
                planned = node.setdefault("planned_members", [])
                planned += [m for m in entry.members if m not in planned]
                node["plan_text"] = node.get("plan_text", "") + entry.text


def _planned_relations(builder: ModelBuilder) -> list[dict]:
    """In a plan-only view there is no code to read edges from; a planned symbol named in
    another file's planned code counts as a relation, within one language and never
    upward in the layer order."""
    owner_of: dict[str, dict] = {}
    for node in builder.nodes:
        for member in node.get("planned_members", []):
            symbol = re.match(r"^[+-](?:class |type )?(\w+)", member)
            if symbol and len(symbol.group(1)) > 3:
                owner_of.setdefault(symbol.group(1), node)
    edges, seen = [], set()
    for node in builder.nodes:
        text = node.get("plan_text", "")
        for symbol, owner in owner_of.items():
            if not text or owner is node or (node["id"], owner["id"]) in seen:
                continue
            if (node["lang"] == "ts") != (owner["lang"] == "ts"):
                continue
            source_rank, target_rank = builder.config.rank_of(node["layer"]), builder.config.rank_of(owner["layer"])
            if source_rank is not None and target_rank is not None and source_rank > target_rank:
                continue
            if re.search(rf"\b{re.escape(symbol)}\b", text):
                seen.add((node["id"], owner["id"]))
                edges.append({"f": node["id"], "t": owner["id"], "kind": "planned", "label": symbol})
    return edges


def _mark_violations(builder: ModelBuilder) -> int:
    by_id = {n["id"]: n for n in builder.nodes}
    count = 0
    for edge in builder.edges:
        if edge["kind"] not in ("import", "call", "port"):
            continue
        source_rank = builder.config.rank_of(by_id[edge["f"]]["layer"])
        target_rank = builder.config.rank_of(by_id[edge["t"]]["layer"])
        if source_rank is not None and target_rank is not None and source_rank > target_rank:
            edge["violation"] = True
            count += 1
    return count


def load_findings(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        records = json.loads(text)
        records = records if isinstance(records, list) else [records]
    except json.JSONDecodeError:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    findings = []
    for record in records:
        if isinstance(record, str):
            findings.append({"summary": record})
        elif isinstance(record, dict) and record.get("summary"):
            findings.append({"summary": record["summary"], "file": record.get("file")})
    return findings


def _attach_findings(builder: ModelBuilder, findings: list[dict]) -> list[str]:
    unmatched = []
    for finding in findings:
        hit = None
        for node in builder.nodes:
            if finding.get("file") and same_file(node["path"], finding["file"]):
                hit = node
                break
            basename = node["path"].rsplit("/", 1)[-1]
            if not finding.get("file") and basename and basename in finding["summary"]:
                hit = node
                break
        if hit:
            hit["findings"].append(finding["summary"])
        else:
            unmatched.append(finding["summary"])
    return unmatched


def _in_scope(config: Config, path: str) -> bool:
    if config.is_excluded(path):
        return False
    if config.python and path.endswith(".py") and path.startswith(config.python.root.strip("/") + "/"):
        return True
    if config.typescript and path.endswith(TS_SUFFIXES) and path.startswith(config.typescript.root.strip("/") + "/"):
        return not path.endswith(".d.ts")
    return False


def build_model(
    config: Config,
    *,
    base: str | None,
    plan: Plan | None,
    plan_only: bool,
    findings: list[dict],
    include_untracked: bool,
    ts_graph_loader=None,
    extra_flows: list[dict] | None = None,
) -> dict:
    git = Git(config.repo_root)
    builder = ModelBuilder(config)
    flows: list[dict] = []
    base_ref = base_sha = None
    changed: list[str] = []

    if not plan_only:
        base_ref, base_sha = git.resolve_base(base or config.base)
        changed = [p for p in git.changed_files(base_sha, include_untracked) if _in_scope(config, p)]
        added = git.added_symbol_names(base_sha)
        for path in changed:
            lang = "ts" if path.endswith(TS_SUFFIXES) else "py"
            node = builder.add_node(path, "changed", lang)
            node["members"] = members_of(path, read_lines(config.repo_root, path), added.get(path, set()))

        reused_paths: set[str] = set()
        if config.python:
            codebase = PythonCodebase(config)
            reused_paths = _python_part(builder, codebase, changed)
            flows += codebase.build_flows(changed, lambda p: builder.lane_of(p, "py"))
        if config.typescript and ts_graph_loader and any(p.endswith(TS_SUFFIXES) for p in changed):
            graph = ts_graph_loader(base_sha, changed)
            if graph:
                _typescript_part(builder, graph)
                flows += [dict(flow, source="typescript") for flow in graph.get("flows", [])]
        _prune_registry_fanout(builder, reused_paths)
        _external_markers(builder, changed)

    if plan:
        _plan_overlay(builder, plan)
    if plan_only:
        builder.edges = _planned_relations(builder)
    violations = _mark_violations(builder)
    unmatched = _attach_findings(builder, findings)
    for node in builder.nodes:
        node.pop("plan_text", None)

    info = git.describe()
    lanes = [layer.name for layer in config.layers]
    for node in builder.nodes:
        if node["layer"] not in lanes and node["layer"] not in ("other", "external"):
            lanes.append(node["layer"])
    lanes += ["other", "external"]
    return {
        "project": config.name,
        "slug": (plan.path.stem if plan else info["branch"]) or "branch",
        "branch": info["branch"],
        "head": info["head"],
        "base": base_ref,
        "base_sha": base_sha[:10] if base_sha else None,
        "plan": str(plan.path) if plan else None,
        "plan_only": plan_only,
        "has_plan": bool(plan and plan.files),
        "lanes": [lane for lane in lanes if any(n["layer"] == lane for n in builder.nodes)],
        "layer_colors": {layer.name: layer.color for layer in config.layers if layer.color},
        "nodes": builder.nodes,
        "edges": builder.edges,
        "violations": violations,
        "unmatched_findings": unmatched,
        "flows": (extra_flows or []) + flows,
        "plan_flows": plan.flows if plan else [],
        "overview": {k: v for k, v in config.overview.items() if k in ("l1", "l2") and v},
    }
