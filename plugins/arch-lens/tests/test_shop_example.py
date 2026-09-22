"""End to end over the example shop: a real git repository, the real CLI, the emitted model.

Run with `python3 -m unittest discover tests`. The TypeScript assertions need node and npm
(the example installs TypeScript into its web/ folder); they are skipped without them.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

from build_demo import SHOP, build_shop_repo, run_arch_lens  # noqa: E402

PLAN = "docs/plans/add-refunds.md"


class ShopExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.repo = build_shop_repo(Path(cls.scratch.name) / "shop")
        cls.typescript_available = (cls.repo / "web" / "node_modules" / "typescript").is_dir()
        cls.built = cls._model("--plan", PLAN, "--findings", str(SHOP / "review-findings.json"))
        cls.plan_only = cls._model("--plan", PLAN, "--plan-only")

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    @classmethod
    def _model(cls, *args: str) -> dict:
        out = Path(cls.scratch.name) / f"model-{len(args)}.json"
        completed = run_arch_lens(cls.repo, *args, "--json", str(out), "--out", str(out.with_suffix(".html")))
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return json.loads(out.read_text())

    def node(self, model: dict, suffix: str) -> dict:
        return next(n for n in model["nodes"] if n["path"].endswith(suffix))

    def edges_between(self, model: dict, source_suffix: str, target_suffix: str) -> list[dict]:
        source, target = self.node(model, source_suffix), self.node(model, target_suffix)
        return [e for e in model["edges"] if e["f"] == source["id"] and e["t"] == target["id"]]

    # ------------------------------------------------------------------ as-built

    def test_the_delta_is_measured_against_the_merge_base(self):
        changed = sorted(n["path"] for n in self.built["nodes"] if n["build"] == "changed")
        expected = [
            "backend/shop/orders/models.py",
            "backend/shop/orders/money.py",
            "backend/shop/orders/services.py",
            "backend/shop/orders/views.py",
            "backend/shop/payments/gateway.py",
            "web/api/src/client.ts",
            "web/api/src/payments.ts",
            "web/app/src/refundButton.ts",
        ]
        self.assertEqual(changed, expected)
        self.assertEqual(self.built["base"], "main")

    def test_files_land_in_the_lane_of_the_layer_their_path_matches(self):
        self.assertEqual(self.node(self.built, "orders/views.py")["layer"], "views")
        self.assertEqual(self.node(self.built, "payments/gateway.py")["layer"], "adapters")
        self.assertEqual(self.node(self.built, "orders/money.py")["layer"], "other")
        self.assertEqual(self.node(self.built, "app/src/refundButton.ts")["layer"], "web app")

    def test_only_the_upward_import_is_a_layer_violation(self):
        violations = [e for e in self.built["edges"] if e.get("violation")]
        self.assertEqual(self.built["violations"], 1)
        self.assertEqual(violations, self.edges_between(self.built, "orders/models.py", "orders/services.py"))
        self.assertEqual(violations[0]["label"], "REFUND_WINDOW_DAYS")

    def test_a_layer_without_rank_is_exempt_from_the_check(self):
        enqueue = self.edges_between(self.built, "orders/services.py", "orders/tasks.py")
        self.assertEqual(len(enqueue), 1)
        self.assertNotIn("violation", enqueue[0])

    def test_untouched_modules_the_delta_imports_appear_as_reused(self):
        self.assertEqual(self.node(self.built, "orders/serializers.py")["build"], "reused")
        self.assertFalse(any(n["path"].endswith("core/http.py") for n in self.built["nodes"]))

    def test_content_markers_connect_a_file_to_its_external_system(self):
        edges = self.edges_between(self.built, "payments/gateway.py", "external:Payment gateway (HTTP)")
        self.assertEqual([e["kind"] for e in edges], ["external"])

    def test_branch_added_symbols_rank_first_among_members(self):
        self.assertEqual(
            self.node(self.built, "orders/services.py")["members"],
            [
                "+refund_order(order_id, amount, reason) Refund",
                "+REFUND_WINDOW_DAYS",
                "+place_order(customer_id, total, source) Order",
            ],
        )

    # ------------------------------------------------------------------ flows

    def test_the_refund_flow_walks_view_service_gateway_database_and_queue(self):
        flow = next(f for f in self.built["flows"] if f["label"] == "POST RefundView")
        calls = [(s["kind"], s["call"]) for s in flow["steps"]]
        self.assertEqual(
            calls,
            [
                ("http", "request"),
                ("fn", "refund_order"),
                ("orm", "Order.objects.get"),
                ("fn", "refund"),
                ("http", "HTTP"),
                ("fn", "to_cents"),
                ("orm", "Refund.objects.create"),
                ("queue", "notify_customer (enqueue)"),
                ("queue", "deliver"),
            ],
        )
        http = next(s for s in flow["steps"] if s["call"] == "HTTP")
        self.assertEqual(http["wire"], "{charge, amount, reason}")

    def test_flows_that_touch_no_changed_module_are_dropped(self):
        labels = {f["label"] for f in self.built["flows"] if f["source"] == "python"}
        self.assertEqual(labels, {"POST RefundView", "POST OrderView", "GET OrderView"})

    # ------------------------------------------------------------------ plan overlay

    def test_the_plan_overlay_names_the_unplanned_and_the_missing(self):
        status = {n["path"]: n["plan"] for n in self.built["nodes"] if n["plan"]}
        self.assertEqual(status["backend/shop/orders/money.py"], "unplanned")
        self.assertEqual(status["backend/shop/orders/emails.py"], "missing")
        self.assertEqual(status["web/app/src/refundButton.ts"], "planned")
        self.assertEqual(sum(1 for s in status.values() if s == "planned"), 7)

    def test_the_plan_flows_travel_with_the_as_built_view(self):
        self.assertEqual([f["label"] for f in self.built["plan_flows"]], ["Refund an order"])

    def test_findings_are_pinned_by_file_and_by_basename(self):
        self.assertEqual(len(self.node(self.built, "orders/models.py")["findings"]), 1)
        self.assertEqual(len(self.node(self.built, "orders/money.py")["findings"]), 1)
        self.assertEqual(self.built["unmatched_findings"], [])

    # ------------------------------------------------------------------ plan only

    def test_plan_only_draws_the_declared_files_with_their_planned_members(self):
        self.assertFalse(any(n["build"] == "changed" for n in self.plan_only["nodes"]))
        self.assertEqual(len(self.plan_only["nodes"]), 8)
        self.assertEqual(
            self.node(self.plan_only, "orders/services.py")["planned_members"],
            ["+refund_order(order_id, amount, reason) Refund", "+REFUND_WINDOW_DAYS"],
        )

    def test_plan_only_relations_come_from_cross_references_and_never_point_up(self):
        planned = self.edges_between(self.plan_only, "orders/services.py", "orders/models.py")
        self.assertEqual([(e["kind"], e["label"]) for e in planned], [("planned", "Refund")])
        self.assertEqual(self.edges_between(self.plan_only, "orders/models.py", "orders/services.py"), [])

    # ------------------------------------------------------------------ typescript

    def test_typescript_edges_are_resolved_calls_through_the_checker(self):
        if not self.typescript_available:
            self.skipTest("TypeScript not installed in the example (needs npm)")
        port = self.edges_between(self.built, "app/src/refundButton.ts", "api/src/payments.ts")
        self.assertEqual([(e["kind"], e["label"]) for e in port], [("port", "PaymentMethod.confirmRefund()")])
        call = self.edges_between(self.built, "app/src/refundButton.ts", "api/src/client.ts")
        self.assertEqual([(e["kind"], e["label"]) for e in call], [("call", "refundOrder()")])
        backend = self.edges_between(self.built, "api/src/client.ts", "external:shop backend (HTTP)")
        self.assertEqual([e["kind"] for e in backend], ["call"])

    def test_typescript_flows_start_from_the_uncalled_changed_function(self):
        if not self.typescript_available:
            self.skipTest("TypeScript not installed in the example (needs npm)")
        flows = [f for f in self.built["flows"] if f["source"] == "typescript"]
        self.assertEqual([f["label"] for f in flows], ["refundButton.ts · requestRefund"])
        self.assertIn("«port» PaymentMethod.confirmRefund", flows[0]["mermaid"])
        self.assertIn("alt ", flows[0]["mermaid"])


@unittest.skipUnless(shutil.which("git"), "needs git")
class NoPlanNoTypeScript(unittest.TestCase):
    def test_a_python_only_run_without_a_plan_has_no_overlay(self):
        with tempfile.TemporaryDirectory() as scratch:
            repo = build_shop_repo(Path(scratch) / "shop", install_typescript=False)
            config = repo / "arch-lens.toml"
            config.write_text(config.read_text().split("[typescript]")[0])
            out = Path(scratch) / "model.json"
            completed = run_arch_lens(repo, "--json", str(out), "--out", str(Path(scratch) / "page.html"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            model = json.loads(out.read_text())
            self.assertFalse(model["has_plan"])
            self.assertTrue(all(n["plan"] is None for n in model["nodes"]))
            self.assertEqual(model["slug"], "feature/add-refunds")


if __name__ == "__main__":
    unittest.main()
