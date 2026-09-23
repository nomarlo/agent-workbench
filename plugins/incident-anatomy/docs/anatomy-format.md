# The anatomy file

One JSON file describes the page. Unknown keys are errors, not warnings: a key the viewer
would silently ignore is a claim the author believes is on the page and is not. Paths
(patches, data files, SVGs) are relative to the anatomy file.

`examples/export-leak/anatomy.json` uses every feature and is the quickest reference.

## Text

Every prose string accepts a small inline markup; everything else is escaped.

| Markup | Renders |
|---|---|
| `` `code` `` | inline code |
| `**bold**`, `*em*` | bold, emphasis |
| `10^13^` | superscript |
| `[text](https://…)` | a link (http and https only) |

Inside `simulation`, strings also take placeholders, filled in for the current step:

| Placeholder | Value |
|---|---|
| `{k}`, `{k-1}`, `{2*k}` | the iteration number, and integer arithmetic over it |
| `{head}` | title of the newest retained item, or `chain.none` |
| `{count}` | how many items are retained |
| `{n}` | completed iterations that added to the meter (in `chain.more`: items not shown) |
| `{value}`, `{retained}`, `{unit}` | the meter's value, what the iterations added, its unit |
| `{left}`, `{left_time}` | iterations (and time, with `seconds_per_iteration`) until `meter.limit` |
| `{iteration}` | `simulation.iteration` |

## Top level

| Key | |
|---|---|
| `title` | required |
| `eyebrow`, `lede` | above and below the title |
| `lang` | `en` (default) or `es`: the viewer's own labels |
| `ui` | override any of the viewer's labels (`incident_anatomy/ui.py` lists them) |
| `repo` | the git repository, relative to the anatomy file; `--repo` overrides it |
| `commit` | the revision everything is resolved against (default `HEAD`); pin the one that ran |
| `facts` | `[{label, value}]`, the key facts beside the title |
| `files` | required, see below |
| `fixes` | see below |
| `simulation` | see below |
| `sections` | see below |
| `sources` | strings, listed in the footer |

## files

```json
"files": {
  "worker": {"path": "exporter/worker.py", "ranges": ["15-34"], "label": "worker.py", "note": "v2.4"}
}
```

`ranges` are `N` or `N-M`, and must lie inside the file. Only these lines are shown, and a
step may only highlight lines inside them. `source: "disk"` reads the path from disk
instead of git, relative to the anatomy file: use it for library code (say which version in
`note`), never for the code under investigation.

## fixes

```json
{"id": "fix1", "title": "…", "patch": "fixes/fix1.patch", "toggle": "short label",
 "where": "…", "why": ["paragraph", "paragraph"]}
```

The patch is a unified diff (`git diff` output). It must apply at `commit`, or nothing is
written. With `toggle`, the fix gets a checkbox in the simulation, and every file it
touches shows the patched version (added lines `+`, removed lines struck) while it is on.

## simulation

| Key | |
|---|---|
| `scenarios` | required: one per combination of toggled fixes, including `"when": []` |
| `iteration` | what one loop is called: message, request, delivery |
| `title`, `lede`, `note` | section heading, intro, footnote (label estimates here) |
| `seconds_per_iteration` | shows elapsed real time |
| `jumps` | `[{label, iterations}]`: buttons that skip ahead in repeating scenarios |
| `block_label` | caption of the dashed box around consecutive `block: true` steps |
| `vars` | names of the state variables listed under the step detail |
| `meter` | `{label, base, max, unit, limit, limit_label, base_label, decimals, notes}` |
| `chain` | `{title, owner, anchor, none, empty, empty_fixed, more, link, summary}` |

`meter.notes` (overridable per scenario) are the texts under the bar for the states
`idle`, `growing`, `limit` and `flat`.

With toggles on, the viewer uses the scenario whose `when` is the largest subset of the
fixes that are on.

### A scenario

```json
{"when": ["fix1"], "name": "Fix 1 only", "repeats": true, "meter_per_iteration": 0, "steps": [ … ]}
```

`repeats` means the last step leads into iteration k+1 (a crash loop, a retry).
`meter_per_iteration` is what one completed iteration adds to the meter; it is counted
at the step marked `"meter": true` (default: the last).

### A step

| Key | |
|---|---|
| `title`, `file` | required; `file` is a key of `files` |
| `lines` | line numbers to highlight, or `"+"` for the lines the active fixes add |
| `also` | `{file key: [lines]}`: other files this step runs, marked with • on their tab |
| `tag`, `tone` | short note beside the title; `bad`, `leak` or `fixed` |
| `block` | inside the dashed box |
| `detail` | the explanation shown for this step |
| `vars` | `{name: "value"}` or `{name: {value, tone}}`; values carry forward to later steps |
| `retain` | `[{title, meta}]`: items that survive the iteration and pile up in the chain |
| `transient` | `{title, meta, freed}`: an object alive only during this step |
| `meter` | the step at which the iteration's meter increment lands |
| `first` | `{title, tag, detail}` overrides for iteration 1 |

## sections

```json
{"title": "Evidence", "lede": "…", "columns": [[block, block], [block]]}
```

`blocks: [...]` instead of `columns` for a single column. Sections are numbered after the
simulation. Any block takes `"card": true`.

| Block | Keys |
|---|---|
| `prose` | `title`, `paragraphs` |
| `figure` | `mermaid` (source) or `svg` (a file; scripts, handlers and foreignObject are refused), `caption` |
| `chart` | `panels`, `x: {kind: number or time, label}`, `markers: [{x, label}]`, `caption` |
| `timeline` | `title`, `items: [{t, text, tone: key, alert or dim}]` |
| `table` | `title`, `lede`, and either `columns` + `rows` or `data` (a CSV; its header is the columns) |
| `fixes` | the fixes, each with its diff |

A chart panel is `{kind: line or bar, data: "evidence/x.csv", y: "column", x: "column",
partial: "column", label, unit, min, max, threshold: {y, label}}`. `x` defaults to the
first column; with `x.kind: "time"` it is `HH:MM` or an ISO timestamp. Rows whose
`partial` column is `1`, `true` or `yes` are drawn dashed, as a lower bound.

Table cells are strings or `{text, tone: ok, warn or bad}`.
