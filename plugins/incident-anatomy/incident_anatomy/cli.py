"""incident-anatomy: an interactive, evidence-backed explainer page for one incident.

  incident-anatomy anatomy.json                 writes anatomy.html next to it
  incident-anatomy anatomy.json --repo ../app   the git repository the excerpts come from
  incident-anatomy anatomy.json --check         validate only: files, lines, patches, data

Every code line on the page is read from git at the anatomy's commit, every fix is a patch
that must apply to that commit, and every chart is drawn from a data file. When one of
those does not hold, the page is not written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from incident_anatomy.build import build
from incident_anatomy.errors import AnatomyError
from incident_anatomy.render import render_html
from incident_anatomy.spec import load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="incident-anatomy", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("anatomy", type=Path, help="the anatomy JSON file")
    parser.add_argument("--repo", type=Path, help="git repository of the excerpts (default: the anatomy's "
                                                   "\"repo\", else the current directory)")
    parser.add_argument("--out", type=Path, help="output HTML (default: next to the anatomy, same name)")
    parser.add_argument("--json", type=Path, help="also write the resolved viewer data")
    parser.add_argument("--check", action="store_true", help="validate and resolve, write nothing")
    args = parser.parse_args(argv)

    anatomy_path = args.anatomy.resolve()
    base_dir = anatomy_path.parent
    try:
        spec = load(anatomy_path)
        repo = args.repo or (base_dir / spec["repo"] if "repo" in spec else Path.cwd())
        data = build(spec, base_dir=base_dir, repo=repo.resolve())
        page = render_html(data)
    except AnatomyError as error:
        print(f"incident-anatomy: {error}", file=sys.stderr)
        return 1

    excerpt_lines = sum(len(v[""]) for v in (f["variants"] for f in data["files"].values()))
    print(
        f"{len(data['files'])} files ({excerpt_lines} lines) read at {data['commit']['short']}; "
        f"{len(data['fixes'])} fixes apply cleanly"
        + (f"; {len(data['simulation']['scenarios'])} scenarios" if data["simulation"] else "")
    )
    if args.check:
        return 0
    out = args.out or anatomy_path.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)
    return 0
