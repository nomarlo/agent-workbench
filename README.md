# agent-workbench

**Tools that make agent-driven development verifiable.**

When an agent writes the code, reading every line stops scaling. What scales is to make
the work *checkable*: a design the reviewer can approve before code exists, a picture
generated from the code rather than drawn, and gates that fail loudly instead of trusting
a summary. This repository collects the tools I built for that, generalised out of a real
codebase and published as working examples to adapt.

Each tool is a self-contained **Claude Code plugin** with a runnable example, end-to-end
tests and a live demo.

## Catalog

| Plugin | What it does | Demo |
|---|---|---|
| [`arch-lens`](plugins/arch-lens) | Generated architecture view of a branch: components in layer lanes from the real import and call graph, layer violations, class diagram, call-graph flows, and a plan-vs-as-built overlay. | [live](https://nomarlo.github.io/agent-workbench/arch-lens/) |

## Install

As Claude Code plugins, from this marketplace:

```
/plugin marketplace add nomarlo/agent-workbench
/plugin install arch-lens@agent-workbench
```

Each plugin's README also covers using it without Claude Code, for example as a CLI.

## Layout

```
.claude-plugin/marketplace.json   every plugin, listed
plugins/<name>/                   one self-contained plugin: manifest, skills, code,
                                  example, tests, docs, and site/build for its demo
site/index.html                   the catalog page of the Pages site
.github/workflows/                one CI workflow per plugin, the Pages build, and a check
                                  that the marketplace and plugins/ agree
```

The demos at [nomarlo.github.io/agent-workbench](https://nomarlo.github.io/agent-workbench/)
are regenerated from the current code on every push, so they cannot drift from what the
tools actually produce.

Adding a tool: see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). Each plugin carries its own copy.
