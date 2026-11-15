#!/usr/bin/env python3
"""Write data/manifest.json: a sha256 for every published file, so the site sync
can publish only what changed (imagery changes daily, data files hourly)."""
import hashlib, json, os, sys
from datetime import datetime, timezone

root = sys.argv[1] if len(sys.argv) > 1 else "."
files = {}
for top in ("data", "media"):
    for d, _, names in os.walk(os.path.join(root, top)):
        for n in sorted(names):
            path = os.path.join(d, n)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel == "data/manifest.json":
                continue
            with open(path, "rb") as fh:
                files[rel] = {"sha256": hashlib.sha256(fh.read()).hexdigest(), "bytes": os.path.getsize(path)}
manifest = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": files}
with open(os.path.join(root, "data", "manifest.json"), "w") as fh:
    json.dump(manifest, fh, indent=1, sort_keys=True)
print(f"manifest: {len(files)} files, {sum(f['bytes'] for f in files.values())/1024:.0f} KiB")
