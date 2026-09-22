from __future__ import annotations

import ast
import unittest

from arch_lens.config import PlanConfig, glob_to_regex
from arch_lens.members import python_members, typescript_members
from arch_lens.plan import parse_files, parse_interface, same_file
from arch_lens.python_extractor import pep758_compat


class Globs(unittest.TestCase):
    def test_double_star_slash_spans_zero_or_more_directories(self):
        pattern = glob_to_regex("backend/**/views.py")
        self.assertTrue(pattern.match("backend/views.py"))
        self.assertTrue(pattern.match("backend/shop/orders/views.py"))
        self.assertFalse(pattern.match("backend/shop/orders/views_old.py"))

    def test_single_star_stays_inside_one_segment(self):
        pattern = glob_to_regex("**/views/*.py")
        self.assertTrue(pattern.match("shop/views/orders.py"))
        self.assertFalse(pattern.match("shop/views/v2/orders.py"))


class Pep758(unittest.TestCase):
    def test_bare_multi_exception_clauses_become_parseable_on_older_interpreters(self):
        source = "try:\n    pass\nexcept ValueError, KeyError:\n    pass\n"
        ast.parse(pep758_compat(source))
        self.assertIn("except (ValueError, KeyError):", pep758_compat(source))


class Members(unittest.TestCase):
    def test_python_generics_do_not_shed_phantom_parameters(self):
        members = python_members(["def merge(left: Mapping[str, str], right: dict[str, int]) -> dict:"])
        self.assertEqual(members, ["+merge(left, right) dict"])

    def test_typescript_exports_and_private_helpers_are_told_apart(self):
        members = typescript_members([
            "export const refundOrder = async (id: number) => id;",
            "export interface PaymentMethod {",
            "const toCents = (amount: number) => amount * 100;",
        ])
        self.assertEqual(members, ["+refundOrder()", "-toCents()", "+type PaymentMethod"])


class PlanParsing(unittest.TestCase):
    PLAN = """# X

## Changes by layer

| Layer | Files |
|---|---|
| backend services | `orders/services.py` |
| web | `app/src/button.ts` |

## Public interface

`orders/services.py`

```python
def refund_order(order_id: int) -> Refund: ...
# orders/models.py
class Refund: ...
```
"""

    def test_prefixes_qualify_paths_by_the_layer_column(self):
        files = parse_files(self.PLAN, PlanConfig(prefixes={"backend": "backend/shop/", "web": "web/"}))
        self.assertEqual(files, {"backend/shop/orders/services.py", "web/app/src/button.ts"})

    def test_a_comment_naming_a_file_switches_the_block_target(self):
        interface = parse_interface(self.PLAN, PlanConfig(), {"orders/services.py", "orders/models.py"})
        self.assertEqual(interface["orders/services.py"].members, ["+refund_order(order_id) Refund"])
        self.assertEqual(interface["orders/models.py"].members, ["+class Refund"])

    def test_a_bare_filename_matches_on_basename_and_a_path_on_segments(self):
        self.assertTrue(same_file("backend/shop/orders/views.py", "orders/views.py"))
        self.assertFalse(same_file("backend/shop/orders/views.py", "serializers/views.py"))
        self.assertTrue(same_file("backend/shop/orders/views.py", "views.py"))
        self.assertFalse(same_file("backend/shop/myorders/views.py", "orders/views.py"))


if __name__ == "__main__":
    unittest.main()
