---
name: arch-lens
description: Generate the Arch Lens page for the current branch — components in layer lanes from the real import/call graph, a class diagram, call-graph flows, layer violations, and a plan-vs-as-built overlay. Use when the user asks for an architecture view, diagram or "arch lens" of a branch or PR, when a design plan is ready for sign-off (plan-only view), or after implementing a planned change (as-built view to compare against the plan).
---

# Arch Lens

The page is **generated, never drawn**: every node, edge and flow comes from the code or
from the plan. Do not hand-edit the HTML or invent boxes; if the picture is wrong, fix the
config (`arch-lens.toml`) or the plan and regenerate.

## Run it

The generator is the `arch_lens` package at the root of this plugin, two directories above
this skill's base directory. From the repository being analysed:

```bash
PYTHONPATH="<plugin root>" python3 -m arch_lens [options]
# or, when installed with pip:  arch-lens [options]
```

Python 3.11+, stdlib only. TypeScript extraction also needs `node` and the workspace's own
`typescript` package (it is never installed by arch-lens).

| Moment | Command |
|---|---|
| Plan ready, no code yet | `--plan docs/plans/<slug>.md --plan-only` |
| Code written | `--plan docs/plans/<slug>.md` (Plan / As-built / Diff toggle) |
| Any branch, no plan | no flags |
| After a review | add `--findings <file.json>` to pin findings on the nodes they name |

The output goes to `.arch-lens/<slug>.html`; the last lines of stdout list every
**unplanned** and **missing** file. Report those to the user: an unplanned file is scope the
plan did not declare, a missing one is a planned piece that was never built.

## First run in a repository

Without `arch-lens.toml` nothing is extracted. Write one by reading the codebase, not by
guessing: `arch-lens.example.toml` next to this plugin's README documents every key.

1. `[[layers]]`: one entry per architectural layer, top (entrypoints) to bottom (storage),
   with path globs and a `rank`. A dependency pointing to a lower rank is a violation.
   Leave `rank` out for a layer that legitimately goes both ways (task queues).
2. `[python]` `root` and `packages`, or `[typescript]` `root` and `src_dir`.
3. `[python.flows]`: the decorators and paths that mark entrypoints in this framework.
4. Generate once and look at the result: files in the `other` lane mean a layer glob is
   missing; a flood of violations usually means the ranks are in the wrong order.

## Plans

The plan format is in `docs/plan-format.md` of this plugin: a **Changes by layer** table
of backticked paths, **Public interface** code blocks (each after the backticked path of
the file it belongs to), and mermaid `sequenceDiagram` blocks for the planned flows.

## Publishing

The page is a single self-contained HTML file (it loads mermaid and fonts from CDNs). When
the host offers an artifact or page-publishing tool, publish the file with it and give the
user the link; otherwise give the path.
