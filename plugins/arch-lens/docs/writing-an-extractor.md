# Writing an extractor

arch-lens is a pipeline with one fixed contract in the middle:

```
extractors (per language)  ──►  model  (schema/model.schema.json)  ──►  viewer (one HTML page)
```

The viewer never looks at source code, and an extractor never produces HTML. To support a
new language, you write something that emits nodes, edges and flows in the model's shape;
the lanes, plan overlay, layer violations, findings and every tab come for free.

## What exists

| Extractor | How it reads code | Edges | Flows |
|---|---|---|---|
| `arch_lens/python_extractor.py` | stdlib `ast` on the host interpreter | imports between internal modules | walked from entrypoints through the call graph: ORM, queue and HTTP hops are recognised by config |
| `arch_lens/extractors/typescript/extract.js` | the TypeScript compiler API and its type checker | **calls** resolved to their declarations, calls through interfaces, interface implementations | mermaid sequence diagrams from uncalled changed functions |
| `arch_lens/members.py` | regular expressions | none | none; it only gives signature lines for the class diagram, and works on plan fragments too |

The TypeScript extractor is a separate process on purpose: it needs the workspace's own
`typescript` package, which only node can load. `cli.py` writes its settings to a JSON file,
runs it, and reads the JSON graph back (see `typescript_loader`). The same pattern fits
any language whose best parser lives in another runtime, such as Go with `go/types` or the
JVM with a compiler plugin.

## The contract, briefly

**Nodes** are files. `path` is repo-relative (or `external:<label>` for a boundary);
`build` is `changed`, `reused` (an untouched neighbour the delta uses) or `external`. The
model assigns `layer` from the config's globs, so an extractor only reports paths.

**Edges** have a `kind`, and only `import`, `call` and `port` edges take part in the layer
check. Give `symbols` (what was called, with counts) and `sites` (function, line, text)
when you have them; the panel shows both.

**Flows** come in two shapes:

- `{label, mermaid}`: a finished `sequenceDiagram`. It is simplest and shown as is.
- `{label, parts, order, steps}`: structured steps. The viewer builds the diagram itself,
  which lets readers toggle argument types, private helpers and external participants.

Hand-written flows in either shape can be added with `--extra-flows file.json`, for the
bridges no static analysis will see: a webhook, a message bus, a scheduled job.

## Principles the existing extractors follow

- **Measure against the merge-base.** Always diff `merge-base(base, HEAD)`, never a local
  `main` that may be behind: a stale base inflates the delta with other people's work.
- **Changed code is the seed; expand a little, never everything.** Draw the changed files,
  the neighbours they use, and one level of callers. Treat a file that many others call
  as a *hub*: draw it, but never expand it.
- **Resolve, do not grep, when you can.** Text matching is fine for signatures and plans;
  edges should come from a parser or a type checker, or the diagram lies with confidence.
- **Say what was left out.** Cap members with a `.. N more ..` line, note depth limits in
  flows, list findings that matched no node. A silent truncation reads as "nothing there".
- **Run on the host with what is there.** No dependencies to install into the analysed
  project; read the project's own toolchain (its `typescript`), and tolerate an interpreter
  older than the project's (see `pep758_compat`).
