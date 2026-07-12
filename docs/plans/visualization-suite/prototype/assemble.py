#!/usr/bin/env python3
"""PROTOTYPE — wipe me. Assembles shell.html + data.json + variant_*.js into one file."""
import json
import sys
import os

D = os.path.dirname(os.path.abspath(__file__))
out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(D, "assembled.html")

with open(os.path.join(D, "shell.html"), encoding="utf-8") as f:
    html = f.read()
with open(os.path.join(D, "data.json"), encoding="utf-8") as f:
    data = json.load(f)
html = html.replace("/*__DATA__*/ null", json.dumps(data, separators=(",", ":")))

# inline d3 so the artifact is fully self-contained (no CDN, no server, no timeout)
d3_path = os.path.join(D, "d3.min.js")
if os.path.exists(d3_path):
    with open(d3_path, encoding="utf-8") as f:
        d3 = f.read()
    html = html.replace(
        '<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>',
        "<script>\n" + d3 + "\n</script>",
    )

present = []
for key in "ABCD":
    p = os.path.join(D, f"variant_{key}.js")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            html = html.replace(f"/*__VARIANT_{key}__*/", f.read())
        present.append(key)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"assembled variants {present} -> {out_path} ({os.path.getsize(out_path)//1024} KB)")
