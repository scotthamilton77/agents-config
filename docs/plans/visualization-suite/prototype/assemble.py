#!/usr/bin/env python3
"""PROTOTYPE — wipe me. Assembles shell.html + data.json + variant_*.js into one file."""
import json
import sys
import os

D = "/Users/scott/src/projects/agents-config/.superpowers/brainstorm/proto-v1"
out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(D, "assembled.html")

html = open(os.path.join(D, "shell.html")).read()
data = json.load(open(os.path.join(D, "data.json")))
html = html.replace("/*__DATA__*/ null", json.dumps(data, separators=(",", ":")))

# inline d3 so the artifact is fully self-contained (no CDN, no server, no timeout)
d3_path = os.path.join(D, "d3.min.js")
if os.path.exists(d3_path):
    html = html.replace(
        '<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>',
        "<script>\n" + open(d3_path).read() + "\n</script>",
    )

present = []
for key in "ABCD":
    p = os.path.join(D, f"variant_{key}.js")
    if os.path.exists(p):
        html = html.replace(f"/*__VARIANT_{key}__*/", open(p).read())
        present.append(key)

open(out_path, "w").write(html)
print(f"assembled variants {present} -> {out_path} ({os.path.getsize(out_path)//1024} KB)")
