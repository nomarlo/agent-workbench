"""End to end over the export-leak example: a real git repository, the measured evidence,
the real CLI and the resolved viewer data.

Run with `python3 -m unittest discover tests`.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

from build_demo import build_example, run_incident_anatomy  # noqa: E402


class ExportLeakExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.workdir = Path(cls.scratch.name)
        cls.anatomy_path = build_example(cls.workdir)
        cls.spec = json.loads(cls.anatomy_path.read_text())
        completed = run_incident_anatomy(
            str(cls.anatomy_path), "--json", str(cls.workdir / "data.json"), "--out", str(cls.workdir / "page.html")
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        cls.data = json.loads((cls.workdir / "data.json").read_text())
        cls.page = (cls.workdir / "page.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def samples(self, name: str) -> list[float]:
        with (self.workdir / "evidence" / f"memory-{name}.csv").open() as handle:
            return [float(row["traced_mib"]) for row in csv.DictReader(handle)]

    def test_the_bug_leaks_and_each_fix_stops_it_as_the_page_claims(self):
        no_fixes, fix1, fix2 = self.samples("no-fixes"), self.samples("fix1"), self.samples("fix2")
        self.assertGreater(no_fixes[-1], 10 * no_fixes[0] / 2, "memory without fixes should grow with deliveries")
        self.assertLess(max(fix1), 1.0)
        self.assertLess(max(fix2), 1.0)

    def test_the_simulated_slope_matches_the_measured_one(self):
        no_fixes = self.samples("no-fixes")
        measured_mib_per_delivery = (no_fixes[-1] - no_fixes[0]) / ((len(no_fixes) - 1) * 10)
        stated = next(s for s in self.spec["simulation"]["scenarios"] if s["when"] == [])["meter_per_iteration"]
        self.assertAlmostEqual(measured_mib_per_delivery, stated, delta=stated * 0.15)

    def test_excerpts_are_the_committed_lines_with_their_numbers(self):
        rows = self.data["files"]["worker"]["variants"][""]
        committed = (self.workdir / "repo" / "exporter" / "worker.py").read_text().splitlines()
        self.assertEqual(rows[0][0], 15)
        for number, kind, text in rows:
            self.assertEqual(kind, "")
            self.assertEqual(text, committed[number - 1])

    def test_a_toggled_fix_shows_its_patch_inside_the_excerpt(self):
        rows = self.data["files"]["worker"]["variants"]["fix1"]
        added = [text for _, kind, text in rows if kind == "+"]
        removed = [number for number, kind, _ in rows if kind == "-"]
        self.assertIn('            ExportWorker.recent_failures.append(f"{type(error).__name__}: {error}")', added)
        self.assertEqual(removed, [16, 17, 32])
        self.assertEqual(self.data["files"]["worker"]["touched_by"], ["fix1"])
        self.assertEqual(sorted(self.data["files"]["records"]["variants"]), ["", "fix2"])

    def test_the_page_carries_the_resolved_commit_and_passes_the_script_check(self):
        self.assertEqual(len(self.data["commit"]["sha"]), 40)
        self.assertIn(self.data["commit"]["short"], self.page)
        self.assertIn("mermaid@11", self.page)
        self.assertNotIn("__DATA__", self.page)

    def test_every_chart_point_comes_from_its_data_file(self):
        chart = self.data["sections"][1]["columns"][0][0]
        self.assertEqual(chart["type"], "chart")
        self.assertEqual([p[1] for p in chart["panels"][0]["points"]], self.samples("no-fixes"))

    def test_a_step_that_highlights_a_line_outside_its_excerpt_is_refused(self):
        spec = json.loads(self.anatomy_path.read_text())
        spec["simulation"]["scenarios"][0]["steps"][3]["lines"] = [3]
        broken = self.workdir / "broken-lines.json"
        broken.write_text(json.dumps(spec))
        completed = run_incident_anatomy(str(broken), "--check")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("worker.py:3, which is outside the excerpt", completed.stderr)

    def test_a_patch_that_does_not_apply_to_the_commit_is_refused(self):
        patch = (self.workdir / "fixes" / "fix2-validate-amount.patch").read_text()
        (self.workdir / "fixes" / "stale.patch").write_text(patch.replace('raw["customer"].strip()', 'raw["customer"]'))
        spec = json.loads(self.anatomy_path.read_text())
        spec["fixes"][1]["patch"] = "fixes/stale.patch"
        broken = self.workdir / "broken-patch.json"
        broken.write_text(json.dumps(spec))
        completed = run_incident_anatomy(str(broken), "--check")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("does not apply at line 13", completed.stderr)


if __name__ == "__main__":
    unittest.main()
