# Plan format

arch-lens reads a plan written in plain markdown, before or alongside the code. Three
parts are recognised; each is optional, and everything else in the file is ignored, so
the plan stays a document written for people.

The example in [`examples/shop/feature/docs/plans/add-refunds.md`](../examples/shop/feature/docs/plans/add-refunds.md)
uses all three.

## 1. Changes by layer

A table under a heading named `Changes by layer` (configurable as
`plan.changes_heading`). Every backticked token ending in `.py`, `.ts`, `.tsx`, `.js` or
`.jsx` is a file the plan will touch.

```markdown
## Changes by layer

| Layer | Files | Change |
|---|---|---|
| backend services | `orders/services.py` | new `refund_order` |
| web | `app/src/refundButton.ts` | `requestRefund` |
```

These drive the overlay:

| Status | Meaning |
|---|---|
| **planned** | changed on the branch and declared here |
| **unplanned** | changed on the branch, not declared: scope the plan did not agree to |
| **missing** | declared, not present: a planned piece that was never built |

**Matching.** A path with a directory matches on whole path segments from the end:
`orders/views.py` matches `backend/shop/orders/views.py`, not `.../myorders/views.py`
or `.../serializers/views.py`. A bare filename matches on basename.

**Prefixes.** When the first column contains a key of `[plan.prefixes]`, its prefix is
prepended, so `orders/services.py` in a `backend …` row becomes
`backend/shop/orders/services.py`. That places plan-only nodes in the right lane.

## 2. Public interface

A section under a heading named `Public interface` (configurable as
`plan.interface_heading`). Each fenced code block belongs to **the last backticked file
path written before it**. Inside a block, a comment line naming a file switches the
target for the lines that follow:

````markdown
## Public interface

`orders/services.py`

```python
REFUND_WINDOW_DAYS = 30

def refund_order(order_id: int, amount: float, reason: str) -> Refund: ...
# orders/models.py
class Refund: ...
```
````

The blocks are read as text, not parsed, so fragments and `...` bodies are fine.
Recognised: Python `def`, `class` and `UPPER_CASE` constants; TypeScript `export const`,
`export function`, `export interface`, `export type`, `export class` and top-level
`const` helpers.

In a plan-only view these become the class diagram. Relations between planned files come
from cross-references: a planned symbol of one file named in another file's planned code.
They are only drawn within one language and never pointing up the layer order.

## 3. Planned flows

Any fenced ` ```mermaid ` block whose body starts with `sequenceDiagram`, labelled by the
nearest heading above it. They appear in the Flows tab as `plan · <heading>`, next to the
flows extracted from the code once it exists, so the planned path and the built path can
be read side by side.
