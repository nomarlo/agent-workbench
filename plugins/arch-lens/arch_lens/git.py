"""The branch delta, always measured against the merge-base.

Diffing against a local `main` that is behind its remote inflates the delta with every
file merged upstream since the last pull, so the base is resolved to a merge-base SHA once
and every diff below compares the working tree against it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class Git:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def run(self, *args: str, check: bool = False) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=self.repo_root, capture_output=True, text=True
        )
        if check and completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed.stdout if completed.returncode == 0 else ""

    def resolve_base(self, preferred: str | None) -> tuple[str, str]:
        candidates = [preferred] if preferred else ["origin/main", "main", "origin/master", "master"]
        for candidate in candidates:
            sha = self.run("merge-base", candidate, "HEAD").strip()
            if sha:
                return candidate, sha
        raise RuntimeError(
            f"no merge-base between HEAD and {' / '.join(candidates)}; pass --base <ref>"
        )

    def changed_files(self, base_sha: str, include_untracked: bool = False) -> list[str]:
        names = set(self.run("diff", "--name-only", base_sha).splitlines())
        if include_untracked:
            names |= set(self.run("ls-files", "--others", "--exclude-standard").splitlines())
        return sorted(name for name in names if (self.repo_root / name).exists())

    def changed_line_ranges(self, base_sha: str, path: str) -> list[tuple[int, int]]:
        ranges = []
        for hunk in re.finditer(
            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", self.run("diff", "-U0", base_sha, "--", path), re.M
        ):
            start = int(hunk.group(1))
            length = 1 if hunk.group(2) is None else int(hunk.group(2))
            if length > 0:
                ranges.append((start, start + length - 1))
        return ranges

    def added_symbol_names(self, base_sha: str) -> dict[str, set[str]]:
        """Names of the definitions the branch adds, per file: ranking them first keeps a
        changed function from being crowded out of its class box by old constants."""
        names_by_path: dict[str, set[str]] = {}
        current = None
        for line in self.run("diff", base_sha, "-U0").splitlines():
            if line.startswith("+++ b/"):
                current = line[6:]
                continue
            if current is None or not line.startswith("+"):
                continue
            symbol = re.match(
                r"\+\s*(?:export )?(?:async )?(?:def|class|function|const|let) (\w+)"
                r"|\+([A-Z][A-Z0-9_]{2,})\s*=",
                line,
            )
            if symbol:
                names_by_path.setdefault(current, set()).add(symbol.group(1) or symbol.group(2))
        return names_by_path

    def describe(self) -> dict[str, str]:
        return {
            "branch": self.run("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "head": self.run("rev-parse", "--short", "HEAD").strip(),
        }
