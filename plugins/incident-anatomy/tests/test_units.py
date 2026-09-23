"""The pieces that decide whether the page can be trusted, on small inputs."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incident_anatomy.errors import AnatomyError  # noqa: E402
from incident_anatomy.excerpts import annotate, excerpt, parse_patch, parse_ranges  # noqa: E402
from incident_anatomy.spec import check_placeholders, validate  # noqa: E402

ORIGINAL = ["def total(items):", "    result = 0", "    for item in items:", "        result += item", "    return result"]

PATCH = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -2,4 +2,2 @@ def total(items):
-    result = 0
-    for item in items:
-        result += item
+    result = sum(items)
     return result
"""


class Excerpts(unittest.TestCase):
    def test_ranges_accept_single_lines_and_spans_within_the_file(self):
        self.assertEqual(parse_ranges(["1", "3-4", 5], "f", 5), {1, 3, 4, 5})
        with self.assertRaisesRegex(AnatomyError, "outside the file"):
            parse_ranges(["4-9"], "f", 5)

    def test_patch_is_laid_over_the_original_with_original_numbers(self):
        rows = annotate(ORIGINAL, parse_patch(PATCH, "p")[0].hunks, "p")
        self.assertEqual(
            [(n, k) for n, k, _ in rows],
            [(1, " "), (2, "-"), (3, "-"), (4, "-"), (None, "+"), (5, " ")],
        )

    def test_a_patch_that_does_not_match_is_refused_with_the_line(self):
        changed = ORIGINAL[:3] + ["        result = result + item"] + ORIGINAL[4:]
        with self.assertRaisesRegex(AnatomyError, "does not apply at line 4"):
            annotate(changed, parse_patch(PATCH, "p")[0].hunks, "p")

    def test_added_lines_show_when_a_neighbour_is_in_the_excerpt(self):
        rows = annotate(ORIGINAL, parse_patch(PATCH, "p")[0].hunks, "p")
        self.assertEqual([k for _, k, _ in excerpt(rows, {5})], ["+", ""])
        self.assertEqual(excerpt(rows, {1}), [[1, "", "def total(items):"]])


class Spec(unittest.TestCase):
    MINIMAL = {"title": "t", "files": {"a": {"path": "a.py", "ranges": ["1"]}}}

    def test_unknown_keys_are_refused_rather_than_ignored(self):
        with self.assertRaisesRegex(AnatomyError, "unknown key"):
            validate({**self.MINIMAL, "subtitle": "x"})

    def test_placeholders_are_known_names_or_arithmetic_over_k(self):
        check_placeholders("delivery {k}, previous {k-1}, chain {2*k}, head {head}", "x")
        with self.assertRaisesRegex(AnatomyError, "unknown placeholder"):
            check_placeholders("{message}", "x")

    def test_the_simulation_needs_the_scenario_without_fixes(self):
        spec = {
            **self.MINIMAL,
            "fixes": [{"id": "f", "title": "t", "patch": "p", "toggle": "t"}],
            "simulation": {"scenarios": [{"when": ["f"], "name": "n", "steps": [{"title": "s", "file": "a"}]}]},
        }
        with self.assertRaisesRegex(AnatomyError, "the incident as it happened"):
            validate(spec)

    def test_a_step_on_an_undeclared_file_is_refused(self):
        spec = {**self.MINIMAL, "simulation": {"scenarios": [{"when": [], "name": "n", "steps": [{"title": "s", "file": "b"}]}]}}
        with self.assertRaisesRegex(AnatomyError, "not a key of files"):
            validate(spec)


if __name__ == "__main__":
    unittest.main()
