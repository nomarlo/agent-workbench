"""The code the page shows, read from git so that no line on the page can be invented,
and the fixes, as patches that must apply to exactly that code."""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path

from incident_anatomy.errors import AnatomyError

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_RANGE = re.compile(r"(\d+)(?:-(\d+))?")

# One displayed line: (original line number, or None for an added line; " ", "+" or "-"; text)
Row = tuple[int | None, str, str]


class Source:
    """One commit of one git repository."""

    def __init__(self, repo: Path, commit: str):
        self.repo = repo
        self.sha = self._git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}").strip()
        self.subject = self._git("log", "-1", "--format=%s", self.sha).strip()

    def _git(self, *args: str) -> str:
        completed = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "no such revision"
            raise AnatomyError(f"git {' '.join(args)} in {self.repo}: {detail}")
        return completed.stdout

    def lines(self, path: str) -> list[str]:
        return self._git("show", f"{self.sha}:{path}").splitlines()

    def has(self, path: str) -> bool:
        completed = subprocess.run(
            ["git", "-C", str(self.repo), "cat-file", "-e", f"{self.sha}:{path}"], capture_output=True
        )
        return completed.returncode == 0


def parse_ranges(ranges: list, where: str, length: int) -> set[int]:
    numbers: set[int] = set()
    for item in ranges:
        match = _RANGE.fullmatch(str(item))
        if not match:
            raise AnatomyError(f"{where}: range {item!r} is not N or N-M")
        start, end = int(match[1]), int(match[2] or match[1])
        if start < 1 or end < start or end > length:
            raise AnatomyError(f"{where}: range {item} is outside the file (lines 1-{length})")
        numbers.update(range(start, end + 1))
    return numbers


@dataclasses.dataclass
class Hunk:
    old_start: int
    header: str
    lines: list[tuple[str, str]]

    @property
    def first_changed_line(self) -> int:
        return self.old_start if any(op != "+" for op, _ in self.lines) else self.old_start + 1


@dataclasses.dataclass
class FilePatch:
    path: str
    creates: bool
    hunks: list[Hunk]


def _strip_prefix(path: str) -> str:
    path = path.split("\t")[0]
    return path[2:] if path[:2] in ("a/", "b/") else path


def parse_patch(text: str, where: str) -> list[FilePatch]:
    lines = text.splitlines()
    patches: list[FilePatch] = []
    old_path = None
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("--- "):
            old_path = line[4:]
            continue
        if line.startswith("+++ "):
            if line[4:].startswith("/dev/null"):
                raise AnatomyError(f"{where}: a fix that deletes a file cannot be shown as code")
            patches.append(FilePatch(_strip_prefix(line[4:]), (old_path or "").startswith("/dev/null"), []))
            continue
        match = _HUNK_HEADER.match(line)
        if not match:
            continue
        if not patches:
            raise AnatomyError(f"{where}: hunk before any file header")
        old_remaining = int(match[2] if match[2] is not None else 1)
        new_remaining = int(match[4] if match[4] is not None else 1)
        hunk = Hunk(old_start=int(match[1]), header=match[5].strip(), lines=[])
        while old_remaining > 0 or new_remaining > 0:
            if index >= len(lines):
                raise AnatomyError(f"{where}: truncated hunk {line}")
            body = lines[index]
            index += 1
            if body.startswith("\\"):
                continue
            op, content = (body[0], body[1:]) if body else (" ", "")
            if op == " ":
                old_remaining, new_remaining = old_remaining - 1, new_remaining - 1
            elif op == "-":
                old_remaining -= 1
            elif op == "+":
                new_remaining -= 1
            else:
                raise AnatomyError(f"{where}: unexpected line in hunk {line}: {body!r}")
            hunk.lines.append((op, content))
        patches[-1].hunks.append(hunk)
    if not patches:
        raise AnatomyError(f"{where}: no file changes found (write patches with `git diff`)")
    return patches


def annotate(original: list[str], hunks: list[Hunk], where: str) -> list[Row]:
    """The file with the hunks laid over it; fails when a hunk does not match the code."""
    rows: list[Row] = []
    cursor = 1
    for hunk in sorted(hunks, key=lambda h: h.old_start):
        start = hunk.first_changed_line
        if start < cursor:
            raise AnatomyError(
                f"{where}: two fixes change overlapping lines near line {hunk.old_start}; "
                "they cannot be shown applied together"
            )
        while cursor < start:
            rows.append((cursor, " ", original[cursor - 1]))
            cursor += 1
        for op, text in hunk.lines:
            if op == "+":
                rows.append((None, "+", text))
                continue
            found = original[cursor - 1] if cursor <= len(original) else None
            if found is None or found.rstrip() != text.rstrip():
                raise AnatomyError(
                    f"{where}: does not apply at line {cursor}: the patch expects {text!r}, "
                    f"the commit has {found!r}"
                )
            rows.append((cursor, op, found))
            cursor += 1
    while cursor <= len(original):
        rows.append((cursor, " ", original[cursor - 1]))
        cursor += 1
    return rows


def _nearest_original(rows: list[Row], index: int, step: int) -> int | None:
    index += step
    while 0 <= index < len(rows):
        if rows[index][0] is not None:
            return rows[index][0]
        index += step
    return None


def excerpt(rows: list[Row], numbers: set[int]) -> list[list]:
    """Rows inside the requested ranges; an added line shows when a neighbour does."""
    kept = []
    for index, (number, kind, text) in enumerate(rows):
        if number is None:
            keep = _nearest_original(rows, index, -1) in numbers or _nearest_original(rows, index, 1) in numbers
        else:
            keep = number in numbers
        if keep:
            kept.append([number, kind.strip(), text])
    return kept


def diff_rows(patches: list[FilePatch]) -> list[list]:
    """A fix as the page shows it: [kind, original line number or None, text]."""
    rows = []
    for patch in patches:
        rows.append(["file", None, patch.path + ("  (new file)" if patch.creates else "")])
        for hunk in patch.hunks:
            rows.append(["hunk", None, f"line {hunk.old_start}" + (f" · {hunk.header}" if hunk.header else "")])
            number = hunk.old_start
            for op, text in hunk.lines:
                rows.append([op.strip(), None if op == "+" else number, text])
                if op != "+":
                    number += 1
    return rows
