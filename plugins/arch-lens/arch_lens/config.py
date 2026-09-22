"""arch-lens.toml: everything the extractors used to hard-code about one codebase.

The engine knows nothing about a particular repository. Layers, source roots, what counts
as an entrypoint, which calls cross a process boundary: all of it is read from here, with
defaults that describe a conventional layered Python web backend.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDE = [
    "**/migrations/**",
    "**/node_modules/**",
    "**/build/**",
    "**/dist/**",
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/*.test.*",
    "**/*.spec.*",
    "**/*.stories.*",
]

DEFAULT_FLOW_STOPLIST = [
    "logger", "logging", "len", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "print", "isinstance", "getattr", "setattr", "hasattr", "super", "uuid",
    "uuid4", "timezone", "datetime", "re", "json", "typing", "sorted", "min", "max",
    "range", "enumerate", "zip", "any", "all",
]


def glob_to_regex(pattern: str) -> re.Pattern:
    """`**/` spans zero or more directories, `*` stays inside one segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(glob_to_regex(pattern).match(path) for pattern in patterns)


@dataclass
class Layer:
    name: str
    paths: list[str]
    rank: int | None = None
    color: str | None = None


@dataclass
class ExternalMarker:
    """A process boundary found by content, for the component view: there is no import to
    follow across an HTTP or SDK call, so a file whose text matches every pattern gets an
    edge to one shared external node."""

    label: str
    all: list[str]


@dataclass
class MethodEntry:
    paths: list[str]
    methods: list[str]


@dataclass
class PythonFlows:
    entry_paths: list[str] = field(
        default_factory=lambda: ["**/views/*.py", "**/views.py", "**/tasks/*.py", "**/tasks.py"]
    )
    entry_decorators: list[str] = field(default_factory=lambda: ["api_view", "route", "actor", "task"])
    entry_methods: list[str] = field(default_factory=lambda: ["get", "post", "put", "patch", "delete"])
    method_entries: list[MethodEntry] = field(default_factory=list)
    queue_decorators: list[str] = field(default_factory=lambda: ["actor", "task"])
    queue_call_suffixes: list[str] = field(default_factory=lambda: [".send", ".delay"])
    queue_label: str = "queue"
    orm_markers: list[str] = field(default_factory=lambda: [".objects."])
    db_label: str = "database"
    http_clients: list[str] = field(default_factory=lambda: ["requests.", "httpx."])
    http_label: str = "external API"
    skip_paths: list[str] = field(default_factory=list)
    stoplist: list[str] = field(default_factory=lambda: list(DEFAULT_FLOW_STOPLIST))
    max_depth: int = 6
    max_steps: int = 60
    max_flows: int = 8


@dataclass
class PythonConfig:
    root: str
    packages: list[str]
    ignore_imports: list[str] = field(default_factory=list)
    collapse_imports: list[str] = field(default_factory=list)
    flows: PythonFlows = field(default_factory=PythonFlows)


@dataclass
class TsExternal:
    id: str
    label: str
    file: str
    name: str
    kind: str = "external"


@dataclass
class TypeScriptConfig:
    root: str
    src_dir: str = "src"
    tsconfig: str = "tsconfig.json"
    scope_packages: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    externals: list[TsExternal] = field(default_factory=list)
    hops: int = 2
    in_hops: int = 1
    anchor_hops: int = 1
    max_callers: int = 8
    max_flows: int = 8
    depth: int = 8


@dataclass
class PlanConfig:
    changes_heading: str = "Changes by layer"
    interface_heading: str = "Public interface"
    prefixes: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    repo_root: Path
    name: str
    base: str | None
    layers: list[Layer]
    group_patterns: list[str]
    exclude: list[str]
    externals: list[ExternalMarker]
    python: PythonConfig | None
    typescript: TypeScriptConfig | None
    plan: PlanConfig
    overview: dict[str, str]

    def layer_of(self, path: str) -> str | None:
        for layer in self.layers:
            if matches_any(path, layer.paths):
                return layer.name
        return None

    def rank_of(self, layer_name: str) -> int | None:
        for layer in self.layers:
            if layer.name == layer_name:
                return layer.rank
        return None

    def group_of(self, path: str) -> str:
        for pattern in self.group_patterns:
            match = re.search(pattern, path)
            if match:
                return match.group(1)
        return path.split("/", 1)[0] if "/" in path else "root"

    def is_excluded(self, path: str) -> bool:
        return matches_any(path, self.exclude)


def _build(cls, raw: dict | None, **overrides):
    raw = dict(raw or {})
    raw.update(overrides)
    known = cls.__dataclass_fields__
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ValueError(f"unknown keys for {cls.__name__}: {', '.join(unknown)}")
    return cls(**raw)


def load_config(path: Path, repo_root: Path) -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    project = raw.get("project", {})

    python = None
    if "python" in raw:
        python_raw = dict(raw["python"])
        flows_raw = dict(python_raw.pop("flows", {}))
        method_entries = [_build(MethodEntry, entry) for entry in flows_raw.pop("method_entries", [])]
        flows = _build(PythonFlows, flows_raw, method_entries=method_entries)
        if "stoplist_extra" in python_raw:
            flows.stoplist += python_raw.pop("stoplist_extra")
        python = _build(PythonConfig, python_raw, flows=flows)

    typescript = None
    if "typescript" in raw:
        ts_raw = dict(raw["typescript"])
        externals = [_build(TsExternal, entry) for entry in ts_raw.pop("externals", [])]
        typescript = _build(TypeScriptConfig, ts_raw, externals=externals)

    return Config(
        repo_root=repo_root,
        name=project.get("name", repo_root.name),
        base=project.get("base"),
        layers=[_build(Layer, entry) for entry in raw.get("layers", [])],
        group_patterns=raw.get("groups", {}).get("patterns", []),
        exclude=project.get("exclude", DEFAULT_EXCLUDE),
        externals=[_build(ExternalMarker, entry) for entry in raw.get("externals", [])],
        python=python,
        typescript=typescript,
        plan=_build(PlanConfig, raw.get("plan")),
        overview=raw.get("overview", {}),
    )
