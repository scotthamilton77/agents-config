#!/usr/bin/env python3
"""PROTOTYPE — wipe me. Builds data.json for the V1 PR-shape heat-map prototype.

Real bones: git file tree, graphify degrees, PR #238 changed files.
Fabricated flesh: consequence/complexity scores + drill-down stories.
"""
import hashlib
import json
import os
import subprocess
from collections import defaultdict

PR_URL = "https://github.com/scotthamilton77/agents-config/pull/238"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    cwd=HERE,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
OUT = os.path.join(HERE, "data.json")

# ---- real file tree ----
files_raw = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
).stdout.splitlines()
EXCLUDE_PREFIX = (".superpowers/", "graphify-out/", ".beads/", ".playwright-mcp/", "archive/")
EXCLUDE_SUFFIX = (".lock", ".png", ".jsonl")
files_raw = [
    f for f in files_raw
    if not f.startswith(EXCLUDE_PREFIX) and not f.endswith(EXCLUDE_SUFFIX)
]

def fsize(p):
    try:
        return os.path.getsize(os.path.join(ROOT, p))
    except OSError:
        return 0

# ---- graphify degrees (real structural centrality proxy) ----
g = json.load(open(os.path.join(ROOT, "graphify-out/graph.json")))
node_file = {n["id"]: n.get("source_file") or "" for n in g["nodes"]}
deg = defaultdict(int)
file_edges = defaultdict(int)  # (src_file, dst_file) -> count
for e in g.get("edges") or g.get("links") or []:
    if e.get("relation") == "contains":
        continue  # containment inflates degree without meaning coupling
    sf, tf = node_file.get(e.get("source"), ""), node_file.get(e.get("target"), "")
    if tf:
        deg[tf] += 1  # in-degree only: centrality = how much others lean on you
    if sf and tf and sf != tf:
        file_edges[(sf, tf)] += 1

max_deg = max(deg.values()) if deg else 1

def centrality(p):
    # story-tuned: history-based centrality is blind to brand-new load-bearing code —
    # the PR itself creates the dependencies. Project namespaces.py from its new importers.
    if p == "packages/installer/src/installer/core/namespaces.py":
        return 0.75
    # sqrt-dampened normalized in-degree so a few god files don't flatten everyone else
    return round((deg.get(p, 0) / max_deg) ** 0.5, 3)

# ---- PR #238 changed files (real numstat) ----
changed = {
    "packages/installer/src/installer/core/namespaces.py": {"adds": 71, "dels": 0, "status": "added"},
    "packages/installer/src/installer/core/backup.py": {"adds": 6, "dels": 8, "status": "modified"},
    "packages/installer/src/installer/core/overlay.py": {"adds": 3, "dels": 7, "status": "modified"},
    "packages/installer/src/installer/core/ownership.py": {"adds": 6, "dels": 2, "status": "modified"},
    "packages/installer/src/installer/core/staging.py": {"adds": 3, "dels": 10, "status": "modified"},
    "packages/installer/src/installer/tools/claude.py": {"adds": 3, "dels": 1, "status": "modified"},
    "packages/installer/tests/unit/test_namespaces.py": {"adds": 126, "dels": 0, "status": "added"},
    "packages/installer/tests/unit/test_ownership.py": {"adds": 4, "dels": 1, "status": "modified"},
}

# ---- fabricated consequence class (path heuristics + hand tags) ----
def consequence(p):
    hand = {
        "packages/installer/src/installer/core/backup.py": 0.95,   # destroys/restores user files
        "packages/installer/src/installer/core/ownership.py": 0.90, # decides what installer may overwrite
        "packages/installer/src/installer/core/namespaces.py": 0.80, # new canonical vocabulary under everything
        "packages/installer/src/installer/core/staging.py": 0.75,
        "packages/installer/src/installer/core/overlay.py": 0.70,
        "packages/installer/src/installer/tools/claude.py": 0.65,
    }
    if p in hand:
        return hand[p]
    if "tests/" in p or p.endswith(("_test.py", ".test.js")):
        return 0.15
    if p.startswith("packages/installer/src/"):
        return 0.7
    if p.startswith("packages/prgroom/src/"):
        return 0.6
    if p.startswith("scripts/"):
        return 0.65
    if "completion-gate" in p or "merge-guard" in p or ".critical-paths" in p:
        return 0.85
    if p.startswith("src/user/.claude/rules/") or p.startswith("src/user/.agents/rules/"):
        return 0.6
    if p.startswith("src/"):
        return 0.5
    if p.startswith("docs/"):
        return 0.1
    return 0.3

# ---- fabricated change complexity (numstat-scaled, story-tuned) ----
def change_complexity(p, meta):
    base = min(1.0, (meta["adds"] + meta["dels"]) / 120.0)
    story = {
        # the hot spot: a brand-new module the rest of the package now leans on
        "packages/installer/src/installer/core/namespaces.py": 0.85,
        "packages/installer/tests/unit/test_namespaces.py": 0.35,  # long but mechanical
    }
    return round(story.get(p, base), 3)

# ---- drill-down stories for changed files (fabricated but faithful to the PR) ----
stories = {
    "packages/installer/src/installer/core/namespaces.py": {
        "headline": "New canonical module — everything now leans on it",
        "why": [
            "Brand-new 71-line module introduced as the single source of namespace vocabulary",
            "Three existing core modules (claude.py, ownership.py, backup.py) rewired to consume it",
            "A defect here propagates to every install, backup, and ownership decision",
            "NOTE: centrality is PROJECTED from the PR's new imports — history-based scoring is blind to newly load-bearing code",
        ],
        "check": [
            "Is the vocabulary complete — does any consumer still carry a private copy?",
            "Import cycle risk: core/ modules importing the new module",
            "Behavior drift: did any list ordering change silently?",
        ],
    },
    "packages/installer/src/installer/core/backup.py": {
        "headline": "Backup semantics touched — highest consequence in the PR",
        "why": [
            "Backup decides what user files get preserved vs clobbered on install",
            "Swapped its private namespace list for the canonical module",
        ],
        "check": ["Any namespace previously backed up that the canonical list omits?"],
    },
    "packages/installer/src/installer/core/ownership.py": {
        "headline": "Ownership rules rewired to canonical vocabulary",
        "why": [
            "Ownership gates what the installer may overwrite in user space",
            "Consumes the new namespaces module",
        ],
        "check": ["Ownership decisions unchanged for every pre-existing namespace?"],
    },
    "packages/installer/src/installer/core/overlay.py": {
        "headline": "Overlay consumer swap — net deletion",
        "why": ["Private list removed in favor of canonical import"],
        "check": ["Overlay still sees identical namespace set?"],
    },
    "packages/installer/src/installer/core/staging.py": {
        "headline": "Staging consumer swap — net deletion",
        "why": ["Private list removed in favor of canonical import"],
        "check": ["Staging routes unchanged?"],
    },
    "packages/installer/src/installer/tools/claude.py": {
        "headline": "Claude adapter now reads canonical vocabulary",
        "why": ["Tool adapter consumes shared namespace list"],
        "check": ["Claude-specific namespaces still complete?"],
    },
    "packages/installer/tests/unit/test_namespaces.py": {
        "headline": "New test module for the canonical vocabulary",
        "why": ["126 lines of new coverage for the new module"],
        "check": ["Do tests assert the *contract* (consumers agree) or just re-state the list contents? Tautology tests would pass while consumers drift."],
    },
    "packages/installer/tests/unit/test_ownership.py": {
        "headline": "Ownership tests updated for the rewire",
        "why": ["Small mechanical assertion updates"],
        "check": [],  # attention bar: deleted-assertion checks are mechanically caught — nothing here earns human review time
    },
}

# mock function-level hotspot scans — fabricated, marked "mock scan" in the UI
stories["packages/installer/src/installer/core/namespaces.py"]["hotspots"] = [
    {"name": "NAMESPACE_REGISTRY constant block", "complexity": 0.25, "centrality": 0.95, "consequence": 0.85,
     "note": "The single source of truth every consumer imports — low logic, maximum leverage. A wrong entry here is a wrong install everywhere."},
    {"name": "resolve_namespace() branching", "complexity": 0.8, "centrality": 0.7, "consequence": 0.7,
     "note": "Longest new function in the PR; nested fallback branches for tool-specific overrides. This is where the review minutes go."},
    {"name": "module-level validation on import", "complexity": 0.45, "centrality": 0.5, "consequence": 0.6,
     "note": "Fails fast on malformed vocabulary — good — but runs at import time for every consumer."},
]
stories["packages/installer/src/installer/core/backup.py"]["hotspots"] = [
    {"name": "_backup_targets() selection", "complexity": 0.35, "centrality": 0.3, "consequence": 0.95,
     "note": "Decides which user files are preserved before overwrite. The consumer swap changed its input list — verify no namespace fell out."},
]

# ---- assemble per-file records ----
files = []
for p in files_raw:
    meta = changed.get(p)
    rec = {
        "path": p,
        "bytes": fsize(p),
        "centrality": centrality(p),
        "consequence": consequence(p),
        "changed": bool(meta),
    }
    if meta:
        rec.update(meta)
        rec["complexity"] = change_complexity(p, meta)
        rec["story"] = stories.get(p)
        # GitHub PR file anchor: sha256 hex of the file path
        rec["diff_url"] = f"{PR_URL}/files#diff-{hashlib.sha256(p.encode()).hexdigest()}"
    else:
        rec["complexity"] = 0.0
    files.append(rec)

# ---- impacted-but-unchanged: files with graph edges into changed files ----
changed_set = set(changed)
impacted = sorted(
    {sf for (sf, tf), _n in file_edges.items() if tf in changed_set and sf not in changed_set}
    | {tf for (sf, tf), _n in file_edges.items() if sf in changed_set and tf not in changed_set}
)

# ---- directory aggregation (2..4 segments) + dir-level edges for graph variants ----
def dir_of(p):
    seg = p.split("/")
    return "/".join(seg[: min(len(seg) - 1, 4)]) or "(root)"

dirs = defaultdict(lambda: {"bytes": 0, "files": 0, "changed": 0, "centrality": 0.0, "consequence": 0.0, "complexity": 0.0})
for f in files:
    d = dirs[dir_of(f["path"])]
    d["bytes"] += f["bytes"]
    d["files"] += 1
    d["changed"] += 1 if f["changed"] else 0
    d["centrality"] = max(d["centrality"], f["centrality"])
    d["consequence"] = max(d["consequence"], f["consequence"])
    d["complexity"] = max(d["complexity"], f["complexity"])

dir_edges = defaultdict(int)
for (sf, tf), n in file_edges.items():
    a, b = dir_of(sf), dir_of(tf)
    if a != b:
        dir_edges[(a, b)] += n

data = {
    "pr": {
        "id": "#238",
        "title": "refactor(installer): centralize namespace vocabulary into canonical module",
        "commit": "33f4ffb",
        "url": PR_URL,
        "files_changed": len(changed),
        "adds": sum(m["adds"] for m in changed.values()),
        "dels": sum(m["dels"] for m in changed.values()),
    },
    "weights_default": {"complexity": 0.4, "centrality": 0.3, "consequence": 0.3},
    "files": files,
    "impacted": impacted,
    "dirs": [{"path": k, **v} for k, v in sorted(dirs.items())],
    "dir_edges": [{"source": a, "target": b, "n": n} for (a, b), n in sorted(dir_edges.items())],
}
json.dump(data, open(OUT, "w"), indent=1)
print(f"files={len(files)} dirs={len(data['dirs'])} dir_edges={len(data['dir_edges'])} impacted={len(impacted)}")
print(f"wrote {OUT} ({os.path.getsize(OUT)//1024} KB)")
