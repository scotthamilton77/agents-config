#!/usr/bin/env bash
# One-command regeneration of the Backlog Landscape HTML from a live bd
# export. See README.md for what this produces and its retirement condition.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out_dir="$here/output"
mkdir -p "$out_dir"

export_jsonl="$out_dir/beads-export.jsonl"
classification_json="$out_dir/classification.json"
graph_json="$out_dir/backlog-graph.json"
landscape_html="$out_dir/backlog-landscape.html"

echo "[1/4] bd export -> $export_jsonl"
bd export -o "$export_jsonl"

echo "[2/4] classify.py -> $classification_json"
python3 "$here/classify.py" --export "$export_jsonl" --out "$classification_json"

echo "[3/4] build_graph.py -> $graph_json"
python3 "$here/build_graph.py" \
  --export "$export_jsonl" \
  --classification "$classification_json" \
  --out "$graph_json"

echo "[4/4] build_landscape.py -> $landscape_html"
python3 "$here/build_landscape.py" --graph "$graph_json" --out "$landscape_html"

echo
echo "Regenerated: $landscape_html"
