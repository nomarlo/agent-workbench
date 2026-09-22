# What a plugin needs to live here

The point of this repository is that every tool in it works as an example someone else
can adapt. A plugin gets in when it has all of the following.

## Structure

```
plugins/<name>/
  .claude-plugin/plugin.json      name matches the folder and the marketplace entry
  skills/<name>/SKILL.md          when to use it and how, written for the agent
  README.md                       for people: what it does, how to adapt it, its limits
  LICENSE                         a copy; an installed plugin is copied without the repo root
  examples/                       a small, made-up codebase the tool runs on end to end
  tests/                          end to end over that example
  site/build                      optional: executable, `site/build <out dir>` writes the demo
```

Then list it in `.claude-plugin/marketplace.json`, add a row to the catalog in the root
`README.md` and a card in `site/index.html`, and add `.github/workflows/ci-<name>.yml`
filtered to `plugins/<name>/**`. The `marketplace` workflow fails when the listing, the
folders and the catalog disagree.

## Rules

1. **All adaptation lives in configuration.** Nothing about one particular codebase
   (paths, layer names, framework decorators, service names) is hard-coded. If the tool
   came from a real project, what that project needed becomes its example config.
2. **A runnable example, not a description.** The example is made up, small, and has
   planted problems for the tool to find, so a reader sees it catch something.
3. **Tests run the real thing.** Use the real CLI on the example in a real git repository,
   with no mocks of the tool's own parts. Skip only what needs an unavailable toolchain,
   and say so in the skip message.
4. **Nothing installed into the analysed project.** Use its toolchain when present, and
   degrade with a message when absent.
5. **Limits are stated.** Every README has a "Limits, stated" section. Say what the tool
   gets wrong before a user finds out.
6. **Generated, not drawn.** Anything visual comes from the code or from a written plan.

## Before publishing something extracted from private code

Search the plugin, including generated example output and screenshots, for the names of
the original company, its products, internal services, ticket prefixes, people, emails
and local paths. Keep that list of terms **out of this repository**: committing it would
publish exactly what it guards. Run it locally or from a hook that lives outside the repo.
