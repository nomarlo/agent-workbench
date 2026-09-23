#!/usr/bin/env python3
"""Build the export-leak example end to end: a real git repository, the measured
evidence, and the page.

  python3 examples/build_demo.py              # writes examples/export-leak/output/anatomy.html
  python3 examples/build_demo.py --out DIR    # somewhere else (the Pages build uses this)

The repository gets one commit from examples/export-leak/repo; measure.py then runs the
worker against it with and without each fix patch, and incident-anatomy renders
anatomy.json against both. The evidence CSVs are also refreshed in the example folder, so
the committed data always matches the committed code.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "export-leak"
PLUGIN_ROOT = HERE.parent

_FIXED_DATE = "2026-03-04T09:00:00+00:00"


def _git(repo: Path, *args: str):
    env = {**os.environ, "GIT_AUTHOR_DATE": _FIXED_DATE, "GIT_COMMITTER_DATE": _FIXED_DATE}
    subprocess.run(
        ["git", "-c", "user.name=incident-anatomy demo", "-c", "user.email=demo@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, env=env,
    )


def build_example(workdir: Path) -> Path:
    """Lay the example out in workdir as the author would have it: anatomy.json, fixes/,
    a git repository in repo/ and measured evidence/. Returns the anatomy file."""
    shutil.copy(EXAMPLE / "anatomy.json", workdir / "anatomy.json")
    shutil.copytree(EXAMPLE / "fixes", workdir / "fixes", dirs_exist_ok=True)
    repo = workdir / "repo"
    shutil.copytree(EXAMPLE / "repo", repo, dirs_exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "exporter: export orders to the warehouse, one page per message")
    subprocess.run([sys.executable, str(EXAMPLE / "measure.py"), str(repo), str(workdir / "evidence")], check=True)
    return workdir / "anatomy.json"


def run_incident_anatomy(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(PLUGIN_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "incident_anatomy", *args], capture_output=True, text=True, env=env
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=EXAMPLE / "output")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        anatomy = build_example(Path(scratch))
        args.out.mkdir(parents=True, exist_ok=True)
        completed = run_incident_anatomy(str(anatomy), "--out", str(args.out / "anatomy.html"))
        sys.stdout.write(completed.stdout)
        if completed.returncode != 0:
            sys.stderr.write(completed.stderr)
            return completed.returncode
        shutil.copytree(Path(scratch) / "evidence", EXAMPLE / "evidence", dirs_exist_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
