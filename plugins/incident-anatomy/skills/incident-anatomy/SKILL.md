---
name: incident-anatomy
description: Build an interactive explainer page for one incident or bug — a step-by-step simulation of the mechanism over the real code lines, retained state, measured evidence, and the fixes as real patches with toggles that show which path disappears. Use when the user asks to explain, document or "make an anatomy / explainer / postmortem page" of an incident, a leak, a production bug or a subtle failure mechanism, after the root cause has been found.
---

# Incident anatomy

The page explains **one mechanism** so that a reader who was not in the investigation can
follow it, check it and approve the fix. Its value is that nothing on it is decoration:
every code line is read from git by the renderer, every fix is a patch that must apply to
that commit, and every chart is drawn from a data file. You write the explanation; the
tool refuses to publish a line or a number it cannot trace.

Do not start the page before the mechanism is understood. If the root cause is still a
hypothesis, keep investigating; the page comes last.

## Run it

The renderer is the `incident_anatomy` package at the root of this plugin, two directories
above this skill's base directory:

```bash
PYTHONPATH="<plugin root>" python3 -m incident_anatomy <dir>/anatomy.json --repo <repo> --check
PYTHONPATH="<plugin root>" python3 -m incident_anatomy <dir>/anatomy.json --repo <repo>
# or, when installed with pip:  incident-anatomy …
```

Python 3.11+, stdlib only; `node`, when present, syntax-checks the emitted script. The page
is written next to the anatomy file. Keep the working directory **outside** the repository
(a scratch folder): the page is about the code, not part of it.

## Working directory

```
<scratch>/incident-XYZ/
  anatomy.json          the page, as data (format: docs/anatomy-format.md of this plugin)
  fixes/*.patch         one patch per fix, from `git diff`
  evidence/*.csv        every number a chart or data table shows
  anatomy.html          generated
```

`examples/export-leak/` in this plugin is a complete, working instance of all of it: read
its `anatomy.json` before writing the first one.

## Method

1. **Pin the commit.** The one that was running when it happened, not the branch tip.
   Every excerpt and patch is resolved against it; set `"commit"`.
2. **Collect evidence into files.** Each query you ran (metrics, logs, traces, SQL) goes
   into `evidence/` as CSV, and its caption names the source and the exact query or
   filter. Prefer evidence that could have **disproved** the hypothesis: a ratio that
   would stay constant if the leak lived inside one request, a count that would level off
   if it were a cache. Mark partial data (query limits, truncated windows) with a
   `partial` column rather than dropping it.
3. **Reproduce when you can**, and say how in the sources: a local script, a test, a
   measurement like the example's `measure.py`. A reproduction beats a screenshot.
4. **Write each fix as a real edit.** In a scratch worktree at the pinned commit, make the
   change, run the relevant tests, then `git diff > fixes/<name>.patch`. Never hand-write a
   patch: the renderer rejects one that does not apply, and a patch that applies but was
   never run is a claim nobody checked.
5. **Order the fixes** from the one that removes the whole class of failure to the one
   that removes this instance, and say in each fix what remains if only that one ships.
6. **Write the simulation.** One scenario per combination of toggled fixes, always
   including `"when": []` (as it happened). Steps are what the code does, in order, each
   pointing at the lines that do it. Use `retain` for what survives the iteration and
   `transient` for what lives only during a step. If the meter's slope is an estimate,
   say so in `simulation.note`.
7. **List what holds by coincidence** (other fields or paths with the same weakness that
   have not failed yet) in a table of their own, apart from what actually failed.
8. **Check, render, look.** `--check` first; then render and step through every scenario
   in a browser. An empty panel or a step that highlights nothing is a defect.

## Verify before publishing

Hand the finished `anatomy.json` and `evidence/` to a subagent (a cheaper model is fine)
with this brief: *"List every sentence in this anatomy that states a number, a line
number, a count, a time or a causal claim. For each, name the evidence file, the code
excerpt or the source that supports it, or mark it UNSUPPORTED."* Fix or remove every
UNSUPPORTED item, or label it as an estimate. The renderer guarantees the code and the
charts; this pass covers the prose.

## Publishing

Incident pages carry internal names: services, customers, hosts, ticket ids. Publish them
privately (the host's artifact or page tool, when there is one) and give the user the
link. Never commit one to a public repository; the public example here is synthetic.

## Limits, stated

- The simulation is a narrated model of the mechanism, not a trace replay: steps and
  retained state are written by the author, only the code lines are resolved.
- Charts are line and bar panels over CSV; anything richer belongs in a figure (mermaid
  or a sanitised SVG).
- At most four fixes can have a toggle; fixes that change overlapping lines of the same
  file cannot be shown applied together.
