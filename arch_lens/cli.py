"""arch-lens: a generated, plan-vs-as-built architecture view of one branch.

  arch-lens                                   the branch delta against its merge-base
  arch-lens --plan docs/plans/x.md            ... with the plan laid over it (Plan | As-built | Diff)
  arch-lens --plan docs/plans/x.md --plan-only    before any code exists: the plan alone
  arch-lens --findings review.jsonl           pin review findings onto the nodes they name
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from arch_lens.config import Config, load_config
from arch_lens.model import build_model, load_findings
from arch_lens.plan import load_plan
from arch_lens.render import render_html

TS_EXTRACTOR = Path(__file__).parent / "extractors" / "typescript" / "extract.js"


def find_repo_root(start: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise SystemExit("arch-lens: not inside a git repository")
    return Path(completed.stdout.strip())


def typescript_loader(config: Config, args: argparse.Namespace):
    def load(base_sha: str, changed: list[str]) -> dict | None:
        if not shutil.which("node"):
            print("[arch-lens] node not found: TypeScript files appear without call edges", file=sys.stderr)
            return None
        ts = config.typescript
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / "graph.json"
            extractor_config = {
                "repo": str(config.repo_root),
                "root": ts.root,
                "srcDir": ts.src_dir,
                "tsconfig": ts.tsconfig,
                "baseSha": base_sha,
                "delta": changed,
                "seeds": args.seed,
                "entry": args.entry,
                "link": args.link,
                "focus": args.focus,
                "ignore": ts.ignore,
                "scopePackages": ts.scope_packages,
                "externals": [asdict(e) for e in ts.externals],
                "hops": ts.hops,
                "inHops": ts.in_hops,
                "anchorHops": ts.anchor_hops,
                "maxCallers": ts.max_callers,
                "maxFlows": ts.max_flows,
                "depth": ts.depth,
                "out": str(out),
            }
            config_path = Path(scratch) / "config.json"
            config_path.write_text(json.dumps(extractor_config))
            completed = subprocess.run(["node", str(TS_EXTRACTOR), "--config", str(config_path)])
            if completed.returncode != 0 or not out.exists():
                print("[arch-lens] the TypeScript extractor failed; continuing without its edges", file=sys.stderr)
                return None
            return json.loads(out.read_text())

    return load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arch-lens", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="arch-lens.toml (default: <repo root>/arch-lens.toml)")
    parser.add_argument("--base", help="ref whose merge-base with HEAD is the baseline (default: config, then origin/main, main)")
    parser.add_argument("--plan", type=Path, help="markdown plan to lay over the delta (see docs/plan-format.md)")
    parser.add_argument("--plan-only", action="store_true", help="ignore the code: draw the plan alone")
    parser.add_argument("--findings", type=Path, help="JSON list or JSONL of findings ({summary, file?}) to pin on nodes")
    parser.add_argument("--extra-flows", type=Path, help="JSON list of hand-written flows, same shape as the generated ones")
    parser.add_argument("--include-untracked", action="store_true", help="also include untracked files")
    parser.add_argument("--seed", action="append", default=[], help="TypeScript: an extra repo-relative file to start from")
    parser.add_argument("--entry", action="append", default=[], help="TypeScript: a flow root, 'path/file.ts#functionName'")
    parser.add_argument("--link", action="append", default=[], help="TypeScript: a declared bridge 'a.ts#fn=b.ts#fn:label'")
    parser.add_argument("--focus", action="append", default=[], help="TypeScript: keep only matching branches of a union call in flows")
    parser.add_argument("--json", type=Path, help="also write the model as JSON")
    parser.add_argument("--out", type=Path, help="output HTML (default: .arch-lens/<slug>.html)")
    args = parser.parse_args(argv)

    repo_root = find_repo_root(Path.cwd())
    config = load_config(args.config or repo_root / "arch-lens.toml", repo_root)
    if not config.python and not config.typescript and not args.plan_only:
        print("[arch-lens] the config declares neither [python] nor [typescript]; nothing to extract", file=sys.stderr)
    if args.plan_only and not args.plan:
        parser.error("--plan-only needs --plan")
    plan = None
    if args.plan:
        if not args.plan.exists():
            parser.error(f"plan not found: {args.plan}")
        plan = load_plan(args.plan, config.plan)

    model = build_model(
        config,
        base=args.base,
        plan=plan,
        plan_only=args.plan_only,
        findings=load_findings(args.findings) if args.findings else [],
        include_untracked=args.include_untracked,
        ts_graph_loader=typescript_loader(config, args) if config.typescript else None,
        extra_flows=json.loads(args.extra_flows.read_text()) if args.extra_flows else None,
    )
    html = render_html(model)
    out = args.out or repo_root / ".arch-lens" / f"{model['slug'].replace('/', '-')}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(model, indent=1), encoding="utf-8")

    changed = sum(1 for n in model["nodes"] if n["build"] == "changed")
    unplanned = [n["path"] for n in model["nodes"] if n["plan"] == "unplanned"]
    missing = [n["path"] for n in model["nodes"] if n["plan"] == "missing"]
    print(f"[arch-lens] {out}")
    print(
        f"[arch-lens] nodes {len(model['nodes'])} ({changed} changed) · edges {len(model['edges'])} · "
        f"flows {len(model['flows'])} (+{len(model['plan_flows'])} planned) · layer violations {model['violations']}"
    )
    if plan and not args.plan_only:
        print(f"[arch-lens] plan overlay: {len(unplanned)} unplanned, {len(missing)} missing")
        for path in unplanned:
            print(f"  unplanned  {path}")
        for path in missing:
            print(f"  missing    {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
