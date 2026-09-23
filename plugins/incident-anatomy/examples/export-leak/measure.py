#!/usr/bin/env python3
"""Measure what the example worker retains, at the commit and with each fix applied.

  python3 measure.py <repo> <evidence dir>

This is the example's production evidence: instead of querying a metrics store, it runs
the worker against the same bad page over and over (what redelivery does) and records
tracemalloc's traced memory. Each scenario runs in a fresh interpreter on a copy of the
repository with the fix patches applied, so the numbers on the page are measured, not typed.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DELIVERIES = 150
SAMPLE_EVERY = 10
PAGE_SIZE = 500

SCENARIOS = {
    "no-fixes": [],
    "fix1": ["fix1-keep-strings.patch"],
    "fix2": ["fix2-validate-amount.patch"],
}

PROGRAM = f"""
import sys, tracemalloc
from exporter.warehouse import Warehouse
from exporter.worker import BatchFailed, ExportWorker

def fetch_page(cursor):
    page = [
        {{"order_id": f"o-{{cursor}}-{{i}}", "customer": f"  customer {{i}}  ",
          "amount": f"{{i}}.50", "notes": "gift wrap, leave at the door " * 3}}
        for i in range({PAGE_SIZE})
    ]
    page[137]["amount"] = "250000000000.00"   # 2.5e13 cents: does not fit numeric(15,2)
    return page

worker = ExportWorker(Warehouse())
tracemalloc.start()
baseline = tracemalloc.get_traced_memory()[0]
print("delivery,traced_mib")
for delivery in range(1, {DELIVERIES} + 1):
    page = fetch_page("page-7")
    try:
        worker.handle(page)
    except BatchFailed:
        pass
    del page
    if delivery % {SAMPLE_EVERY} == 0:
        print(f"{{delivery}},{{(tracemalloc.get_traced_memory()[0] - baseline) / 2**20:.3f}}")
"""


def measure(repo: Path, patches: list[str]) -> list[tuple[int, float]]:
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "repo"
        shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"))
        for patch in patches:
            subprocess.run(["git", "apply", str(HERE / "fixes" / patch)], cwd=copy, check=True)
        completed = subprocess.run(
            [sys.executable, "-c", PROGRAM], cwd=copy, check=True, capture_output=True, text=True
        )
    rows = list(csv.DictReader(completed.stdout.splitlines()))
    return [(int(row["delivery"]), float(row["traced_mib"])) for row in rows]


def main(argv: list[str]) -> int:
    repo, evidence = Path(argv[1]), Path(argv[2])
    evidence.mkdir(parents=True, exist_ok=True)
    samples_by_scenario = {name: measure(repo, patches) for name, patches in SCENARIOS.items()}
    for name, samples in samples_by_scenario.items():
        with (evidence / f"memory-{name}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["delivery", "traced_mib"])
            writer.writerows(samples)
    no_fixes = samples_by_scenario["no-fixes"]
    with (evidence / "growth-per-sample.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["delivery", "grown_mib"])
        for (_, before), (delivery, after) in zip(no_fixes, no_fixes[1:]):
            writer.writerow([delivery, f"{after - before:.3f}"])
    with (evidence / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Scenario", f"Traced after {DELIVERIES} deliveries (MiB)", "Growth per delivery (KiB)"])
        labels = {"no-fixes": "No fixes", "fix1": "Fix 1 · keep strings", "fix2": "Fix 2 · validate the amount"}
        for name, samples in samples_by_scenario.items():
            (first_delivery, first_mib), (last_delivery, last_mib) = samples[0], samples[-1]
            per_delivery_kib = (last_mib - first_mib) / (last_delivery - first_delivery) * 1024
            writer.writerow([labels[name], f"{last_mib:.2f}", f"{per_delivery_kib:.0f}"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
