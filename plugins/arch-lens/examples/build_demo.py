#!/usr/bin/env python3
"""Build the example shop as a real git repository and run arch-lens on its feature branch.

  python3 examples/build_demo.py              # writes examples/shop/output/*.html
  python3 examples/build_demo.py --keep DIR   # also keeps the generated repository in DIR

The repository gets two commits: the baseline on `main`, and the refunds feature (with its
plan) on `feature/add-refunds`. TypeScript is installed into web/ with npm when available;
without it, the TypeScript files still appear, just without call edges.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOP = HERE / "shop"
REPO_ROOT = HERE.parent


def _git(repo: Path, *args: str):
    subprocess.run(
        ["git", "-c", "user.name=arch-lens demo", "-c", "user.email=demo@example.invalid", *args],
        cwd=repo, check=True, capture_output=True,
    )


def build_shop_repo(dest: Path, *, with_feature: bool = True, install_typescript: bool = True) -> Path:
    shutil.copytree(SHOP / "base", dest, dirs_exist_ok=True)
    (dest / ".gitignore").write_text("node_modules/\n.arch-lens/\n")
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "shop: orders and payments")
    if with_feature:
        _git(dest, "checkout", "-q", "-b", "feature/add-refunds")
        shutil.copytree(SHOP / "feature", dest, dirs_exist_ok=True)
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "-m", "shop: refunds")
    if install_typescript and shutil.which("npm"):
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--silent"],
            cwd=dest / "web", check=False, capture_output=True,
        )
    return dest


def run_arch_lens(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "arch_lens", *args],
        cwd=repo, env={**_env(), "PYTHONPATH": str(REPO_ROOT)}, capture_output=True, text=True,
    )


def _env() -> dict:
    import os

    return dict(os.environ)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=Path, help="build the repository here and keep it")
    parser.add_argument("--out", type=Path, default=SHOP / "output", help="where the HTML pages go")
    args = parser.parse_args()

    scratch = None
    if args.keep:
        repo = args.keep.resolve()
        repo.mkdir(parents=True, exist_ok=True)
    else:
        scratch = tempfile.TemporaryDirectory()
        repo = Path(scratch.name) / "shop"
    build_shop_repo(repo)
    args.out.mkdir(parents=True, exist_ok=True)

    runs = [
        ("add-refunds.html", ["--plan", "docs/plans/add-refunds.md",
                              "--findings", str(SHOP / "review-findings.json")]),
        ("add-refunds-plan-only.html", ["--plan", "docs/plans/add-refunds.md", "--plan-only"]),
    ]
    for name, extra in runs:
        completed = run_arch_lens(repo, *extra, "--out", str(args.out.resolve() / name))
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            return completed.returncode
    if scratch:
        scratch.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
