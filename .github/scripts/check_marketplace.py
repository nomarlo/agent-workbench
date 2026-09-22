"""The marketplace and the plugins folder agree: every listed plugin exists with a manifest
of the same name, every plugin folder is listed, and each plugin has the files a reader of
this repository relies on."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ["README.md", "LICENSE", ".claude-plugin/plugin.json"]

marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
listed = {entry["name"]: entry for entry in marketplace["plugins"]}
folders = {path.name for path in (ROOT / "plugins").iterdir() if path.is_dir()}
problems = []

for name in sorted(folders - set(listed)):
    problems.append(f"plugins/{name} is not listed in .claude-plugin/marketplace.json")
for name, entry in sorted(listed.items()):
    source = ROOT / entry["source"]
    if entry["source"] != f"./plugins/{name}":
        problems.append(f"{name}: source should be ./plugins/{name}, is {entry['source']}")
    for required in REQUIRED:
        if not (source / required).is_file():
            problems.append(f"{name}: missing {required}")
    manifest = source / ".claude-plugin/plugin.json"
    if manifest.is_file() and json.loads(manifest.read_text()).get("name") != name:
        problems.append(f"{name}: plugin.json name differs from its marketplace entry")
    if f"plugins/{name}" not in (ROOT / "README.md").read_text():
        problems.append(f"{name}: not in the catalog table of the root README")

print("\n".join(problems) or f"marketplace ok: {', '.join(sorted(listed))}")
sys.exit(1 if problems else 0)
