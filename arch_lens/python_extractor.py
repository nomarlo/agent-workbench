"""Python: the import graph between changed modules, and flows from the AST call graph.

Stdlib only, and it runs on whatever interpreter is on the host, which may be older than
the one the project targets; `except A, B:` (PEP 758, Python 3.14) is re-parenthesized
before parsing so an older host can still read a 3.14 codebase.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from arch_lens.config import Config, PythonConfig, matches_any


def pep758_compat(source: str) -> str:
    return re.sub(
        r"^(\s*except )([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)+)(\s*:)",
        r"\1(\2)\3",
        source,
        flags=re.MULTILINE,
    )


def dotted_name(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


@dataclass
class FunctionInfo:
    args: list[list[str]]
    returns: str
    decorators: list[str]
    calls: list[str]
    wire_keys: list[str] | None


@dataclass
class ModuleInfo:
    functions: dict[str, FunctionInfo] = field(default_factory=dict)
    # local alias -> (absolute module, imported name or None for `import x`)
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    # (absolute module, names imported) in source order, for component edges
    import_list: list[tuple[str, list[str]]] = field(default_factory=list)
    parsed: bool = False


class PythonCodebase:
    def __init__(self, config: Config):
        assert config.python is not None
        self.config = config
        self.python: PythonConfig = config.python
        self.repo_root = config.repo_root
        self.prefix = self.python.root.strip("/") + "/" if self.python.root.strip("/") else ""
        self._modules: dict[str, ModuleInfo] = {}

    # ------------------------------------------------------------------ paths and modules

    def owns(self, path: str) -> bool:
        return path.startswith(self.prefix) and path.endswith(".py")

    def module_of(self, path: str) -> str | None:
        if not self.owns(path):
            return None
        return path.removeprefix(self.prefix).removesuffix(".py").removesuffix("/__init__").replace("/", ".")

    def path_of(self, module: str) -> str | None:
        base = self.prefix + module.replace(".", "/")
        for candidate in (base + ".py", base + "/__init__.py"):
            if (self.repo_root / candidate).is_file():
                return candidate
        return None

    def is_internal(self, module: str) -> bool:
        return module.split(".")[0] in self.python.packages

    def _absolute(self, path: str, module: str | None, level: int) -> str | None:
        if level == 0:
            return module
        own = self.module_of(path) or ""
        package_parts = own.split(".") if path.endswith("__init__.py") else own.split(".")[:-1]
        if level - 1 > len(package_parts):
            return None
        base = package_parts[: len(package_parts) - (level - 1)]
        return ".".join(base + ([module] if module else [])) or None

    def module(self, path: str) -> ModuleInfo:
        if path in self._modules:
            return self._modules[path]
        info = ModuleInfo()
        self._modules[path] = info
        full = self.repo_root / path
        if not full.is_file():
            return info
        try:
            tree = ast.parse(pep758_compat(full.read_text(encoding="utf-8", errors="replace")))
        except SyntaxError:
            return info
        info.parsed = True
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                absolute = self._absolute(path, node.module, node.level)
                if not absolute:
                    continue
                names = []
                for alias in node.names:
                    info.imports[alias.asname or alias.name] = (absolute, alias.name)
                    names.append(alias.name)
                info.import_list.append((absolute, names))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    info.imports[alias.asname or alias.name] = (alias.name, None)
                    info.import_list.append((alias.name, []))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        info.functions[f"{node.name}.{member.name}"] = self._function(member)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info.functions[node.name] = self._function(node)
        return info

    @staticmethod
    def _function(node) -> FunctionInfo:
        arguments = [
            [arg.arg, ast.unparse(arg.annotation) if arg.annotation else ""]
            for arg in node.args.args + node.args.kwonlyargs
            if arg.arg not in ("self", "cls")
        ]
        ordered_calls, wire_keys = [], None
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = dotted_name(sub.func)
                if name:
                    ordered_calls.append((sub.lineno, sub.col_offset, name))
            if isinstance(sub, ast.Dict) and wire_keys is None:
                keys = [k.value for k in sub.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                if len(keys) >= 3:
                    wire_keys = keys
        decorators = []
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            decorators.append(dotted_name(target) or "")
        return FunctionInfo(
            args=arguments,
            returns=ast.unparse(node.returns) if node.returns else "",
            decorators=decorators,
            # source order, not ast.walk's breadth-first order: a call nested three levels
            # deep must not fall past the step budget behind its shallower siblings
            calls=[name for _, _, name in sorted(ordered_calls)],
            wire_keys=wire_keys,
        )

    # ------------------------------------------------------------------ component edges

    def internal_imports(self, path: str) -> list[tuple[str, str]]:
        """(target module, label) per internal import, `from pkg import submodule` resolved
        to the submodule when it is a module of its own."""
        out = []
        for module, names in self.module(path).import_list:
            if not self.is_internal(module) or module.startswith(tuple(self.python.ignore_imports)):
                continue
            submodules = [name for name in names if self.path_of(f"{module}.{name}")]
            for name in submodules:
                out.append((f"{module}.{name}", ""))
            rest = [name for name in names if name not in submodules]
            if rest or not names:
                out.append((module, " · ".join(rest[:3])))
        collapsed = []
        for module, label in out:
            for prefix in self.python.collapse_imports:
                if module.startswith(prefix + "."):
                    module = prefix
            collapsed.append((module, label))
        return collapsed

    # ------------------------------------------------------------------ flows

    def _resolve_call(self, path: str, dotted: str, enclosing_class: str | None):
        """-> ('fn', path, function) | ('orm', text) | ('queue', path, actor) | None."""
        flows = self.python.flows
        head = dotted.split(".")[0]
        if head in flows.stoplist:
            return None
        if any(marker in dotted + "." for marker in flows.orm_markers):
            return ("orm", dotted)
        info = self.module(path)
        if head == "self":
            if enclosing_class is None or "." not in dotted:
                return None
            member = f"{enclosing_class}.{dotted.split('.', 1)[1]}"
            return ("fn", path, member) if member in info.functions else None
        for suffix in flows.queue_call_suffixes:
            if dotted.endswith(suffix):
                ref = self._resolve_call(path, dotted[: -len(suffix)], enclosing_class)
                return ("queue", ref[1], ref[2]) if ref and ref[0] == "fn" else None
        if "." not in dotted:
            if dotted in info.functions:
                return ("fn", path, dotted)
            if dotted in info.imports:
                module, original = info.imports[dotted]
                target = self.path_of(module) if original else None
                if target and original in self.module(target).functions:
                    return ("fn", target, original)
            return None
        if head in info.imports:
            module, original = info.imports[head]
            module = f"{module}.{original}" if original else module
            rest = dotted.split(".")[1:]
            target = self.path_of(module)
            if target and len(rest) == 1 and rest[0] in self.module(target).functions:
                return ("fn", target, rest[0])
        return None

    def _http_bridges(self, path: str) -> set[str]:
        info = self.module(path)
        clients = tuple(self.python.flows.http_clients)
        bridges = {name for name, fn in info.functions.items() if any(c.startswith(clients) for c in fn.calls)}
        grown = True
        while grown:
            grown = False
            for name, fn in info.functions.items():
                if name not in bridges and any(c in bridges for c in fn.calls):
                    bridges.add(name)
                    grown = True
        return bridges

    def _is_queue_consumer(self, decorators: list[str]) -> bool:
        return any(marker in decorator for decorator in decorators for marker in self.python.flows.queue_decorators)

    def _stereotype(self, path: str, layer: str) -> str:
        if any(self._is_queue_consumer(fn.decorators) for fn in self.module(path).functions.values()):
            return "queue consumer"
        return layer

    def _entry_files(self, changed: set[str]) -> list[str]:
        flows = self.python.flows
        groups = {self.config.group_of(path) for path in changed}
        entries = []
        root = self.repo_root / self.prefix if self.prefix else self.repo_root
        for full in sorted(root.rglob("*.py")):
            rel = str(full.relative_to(self.repo_root))
            if self.config.is_excluded(rel) or full.name == "__init__.py":
                continue
            if matches_any(rel, flows.entry_paths) and self.config.group_of(rel) in groups:
                entries.append(rel)
        for rel in sorted(changed):
            if rel not in entries and any(matches_any(rel, e.paths) for e in flows.method_entries):
                entries.append(rel)
        return entries

    def _is_entry(self, path: str, fn_name: str, info: FunctionInfo) -> bool:
        flows = self.python.flows
        bare = fn_name.rsplit(".", 1)[-1]
        if bare.startswith("_") or any(arg[0] in ("view_func", "func") for arg in info.args):
            return False
        if "." in fn_name and any(
            matches_any(path, entry.paths) and bare in entry.methods for entry in flows.method_entries
        ):
            return True
        if any(marker in decorator for decorator in info.decorators for marker in flows.entry_decorators):
            return True
        return matches_any(path, flows.entry_paths) and ("." not in fn_name or bare in flows.entry_methods)

    def _flow_label(self, fn_name: str) -> str:
        if "." not in fn_name:
            return fn_name
        klass, method = fn_name.split(".", 1)
        if method in self.python.flows.entry_methods:
            return f"{method.upper()} {klass}"
        return f"{klass}.{method}()"

    def build_flows(self, changed_files: list[str], layer_of) -> list[dict]:
        flows_cfg = self.python.flows
        changed = {path for path in changed_files if self.owns(path)}
        if not changed:
            return []
        flows = []

        def participant(parts: dict, order: list, key: str, spec: dict) -> str:
            if key not in parts:
                parts[key] = dict(spec, id=f"p{len(parts)}")
                order.append(key)
            return parts[key]["id"]

        def code_participant(parts, order, path):
            layer = layer_of(path)
            return participant(parts, order, path, {
                "label": path.rsplit("/", 1)[-1], "layer": layer,
                "stereo": self._stereotype(path, layer), "ext": False})

        def walk(path, fn_name, depth, steps, parts, order, seen):
            if depth > flows_cfg.max_depth or len(steps) >= flows_cfg.max_steps:
                return
            info = self.module(path).functions.get(fn_name)
            if not info:
                return
            source = code_participant(parts, order, path)
            enclosing_class = fn_name.split(".")[0] if "." in fn_name else None
            for call in info.calls:
                if len(steps) >= flows_cfg.max_steps:
                    return
                ref = self._resolve_call(path, call, enclosing_class)
                if ref is None:
                    continue
                if ref[0] == "orm":
                    db = participant(parts, order, "__db__", {
                        "label": flows_cfg.db_label, "layer": "infra", "stereo": "DB", "ext": True, "side": "R"})
                    steps.append({"f": source, "t": db, "call": call, "args": [], "ret": "", "kind": "orm"})
                    continue
                if ref[0] == "queue":
                    _, target_path, actor = ref
                    broker = participant(parts, order, "__queue__", {
                        "label": flows_cfg.queue_label, "layer": "infra", "stereo": "broker", "ext": True, "side": "R"})
                    target_info = self.module(target_path).functions.get(actor)
                    steps.append({"f": source, "t": broker, "call": f"{actor} (enqueue)",
                                  "args": target_info.args if target_info else [], "ret": "", "kind": "queue"})
                    consumer = code_participant(parts, order, target_path)
                    steps.append({"f": broker, "t": consumer, "call": "deliver", "args": [], "ret": "", "kind": "queue"})
                    if (target_path, actor) not in seen:
                        seen.add((target_path, actor))
                        walk(target_path, actor, depth + 1, steps, parts, order, seen)
                    continue
                _, target_path, target_fn = ref
                if matches_any(target_path, flows_cfg.skip_paths):
                    continue
                target_info = self.module(target_path).functions[target_fn]
                target = code_participant(parts, order, target_path)
                step = {"f": source, "t": target, "call": target_fn.rsplit(".", 1)[-1],
                        "args": target_info.args, "ret": target_info.returns, "kind": "fn"}
                if target_fn.rsplit(".", 1)[-1].startswith("_") and target_path == path:
                    step["priv"] = True
                steps.append(step)
                if target_fn in self._http_bridges(target_path):
                    api = participant(parts, order, "__http__", {
                        "label": flows_cfg.http_label, "layer": "external", "stereo": "external API",
                        "ext": True, "side": "R"})
                    http = {"f": target, "t": api, "call": "HTTP", "args": [], "ret": "", "kind": "http"}
                    wire_keys = target_info.wire_keys
                    if not wire_keys:
                        for callee_name in target_info.calls:
                            callee = self.module(target_path).functions.get(callee_name)
                            if callee and callee.wire_keys:
                                wire_keys = callee.wire_keys
                                break
                    if wire_keys:
                        http["wire"] = "{" + ", ".join(wire_keys) + "}"
                    steps.append(http)
                if (target_path, target_fn) not in seen:
                    seen.add((target_path, target_fn))
                    walk(target_path, target_fn, depth + 1, steps, parts, order, seen)

        for path in self._entry_files(changed):
            for fn_name, info in self.module(path).functions.items():
                if not self._is_entry(path, fn_name, info):
                    continue
                parts, order, steps = {}, [], []
                trigger_kind = "queue" if self._is_queue_consumer(info.decorators) else "http"
                trigger = participant(parts, order, "__trigger__", {
                    "label": "caller" if trigger_kind == "queue" else "client",
                    "layer": "external", "stereo": "trigger", "ext": True, "side": "L"})
                walk(path, fn_name, 1, steps, parts, order, {(path, fn_name)})
                if not steps:
                    continue
                root = parts.get(path, {}).get("id")
                if root:
                    steps.insert(0, {"f": trigger, "t": root,
                                     "call": "request" if trigger_kind == "http" else fn_name.rsplit(".", 1)[-1],
                                     "args": info.args, "ret": "", "kind": trigger_kind})
                touched = {key for key in parts if key in changed}
                if not touched:
                    continue
                flows.append({
                    "id": f"{path}#{fn_name}",
                    "label": self._flow_label(fn_name),
                    "source": "python",
                    "touched": len(touched),
                    "parts": {p["id"]: {k: v for k, v in p.items() if k != "id"} for p in parts.values()},
                    "order": [parts[k]["id"] for k in order],
                    "steps": steps,
                })

        by_shape: dict[str, dict] = {}
        for flow in flows:
            shape = json.dumps(flow["steps"][1:], sort_keys=True)
            if shape in by_shape:
                by_shape[shape]["label"] += " / " + flow["label"]
            else:
                by_shape[shape] = flow
        ranked = sorted(by_shape.values(), key=lambda f: (-f["touched"], -len(f["steps"]), f["label"]))
        for flow in ranked:
            flow.pop("touched", None)
        return ranked[: flows_cfg.max_flows]


def read_lines(repo_root: Path, path: str) -> list[str]:
    return (repo_root / path).read_text(encoding="utf-8", errors="replace").splitlines()
