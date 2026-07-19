"""Classify every non-closed bead into a track by anchor-epic then keyword
heuristics. Interim census tool -- see README.md for the retirement note.
"""
import argparse
import json
import collections

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--export", required=True, help="bd export JSONL path")
parser.add_argument("--out", required=True, help="classification JSON output path")
args = parser.parse_args()

beads = {}
with open(args.export) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        b = json.loads(line)
        beads[b['id']] = b

MILESTONES = {
    'agents-config-wgclw': ('M0', 0),
    'agents-config-abn9': ('M1', 1),
    'agents-config-qn0g': ('M2', 2),
    'agents-config-vaac': ('M3', 3),
    'agents-config-t142': ('M4', 4),
    'agents-config-yf2ov': ('M5', 5),
    'agents-config-uxns2': ('PORT', 6),
}

def parent_of(bid):
    b = beads.get(bid)
    if not b: return None
    for d in b.get('dependencies') or []:
        if d['type'] == 'parent-child' and d['issue_id'] == bid:
            return d['depends_on_id']
    return None

def ancestors(bid):
    chain = []
    cur = bid
    seen = set()
    while True:
        p = parent_of(cur)
        if not p or p in seen:
            break
        chain.append(p)
        seen.add(p)
        cur = p
    return chain

def milestone_of(bid):
    chain = ancestors(bid)
    for a in chain:
        if a in MILESTONES:
            return a
    return None

# Track anchor epics (ancestor id prefix match)
TRACK_ANCHORS = [
    ('prgroom', ['agents-config-fca6', 'agents-config-abn9.8']),
    ('workcli', ['agents-config-wgclw.9']),
    ('pdlc-orchestrator', ['agents-config-wgclw.2', 'agents-config-wgclw.3', 'agents-config-wgclw.4',
                            'agents-config-wgclw.5', 'agents-config-wgclw.6', 'agents-config-wgclw.11']),
    ('holding-place', ['agents-config-wgclw.10', 'agents-config-g6ix3']),
    ('vizsuite', ['agents-config-yf2ov.2']),
]

def anchor_track(bid):
    chain = [bid] + ancestors(bid)
    for track, prefixes in TRACK_ANCHORS:
        for a in chain:
            for p in prefixes:
                if a == p or a.startswith(p + '.'):
                    return track
    return None

KEYWORDS = [
    ('prgroom', ['prgroom', 'pr-groom', 'pr grooming']),
    ('workcli', ['workcli', 'work facade', 'work-facade', 'work cli']),
    ('pdlc-orchestrator', ['pdlc orchestrator', 'pdlc ', ' pdlc']),
    ('holding-place', ['holding place', 'holding-place', 'icebox', 'idea pipeline']),
    ('vizsuite', ['vizsuite', 'viz suite', 'visualization suite', 'viz queue', 'viz sweep',
                  'landscape', 'fact identity', 'tracker port', 'funnel rung', '.viz/', 'estate treemap',
                  'attention ledger', 'file-sonar', 'constellation']),
    ('installer', ['installer', 'install.sh', 'install.py', 'src/kits', 'uv-tool', 'project-scoped install']),
    ('portability', ['portable discipline', 'overlay-preserving', 'multi-machine', 'home + work machine',
                      'custom-harness', 'api gateway']),
    ('skills-discipline', ['skill', 'rule', 'command', 'formula', 'molecule', 'hep ', 'brainstorm',
                            'simplify', 'quality-gate', 'completion-gate', 'merge-guard', 'codex', 'gemini',
                            'opencode', 'graphify', 'agent persona', 'ralf', 'bd ', 'bd-', 'beads', 'jq ',
                            'whats-next', 'bead-implementor', 'worker-report', 'container gate',
                            'close-walk', 'collect.py', 'append-notes', 'append-acceptance', 'append-design',
                            'project-config.toml', 'merge-gate', 'gate_trust_mode', 'foreign-agent-review',
                            'verify-artifacts', 'red-phase', 'decision record', 'persona-vs-orchestration']),
    ('ops-meta', ['triage', 'roadmap', 'milestone', 'instrumentation', '85/5/10', 'cost per session',
                  'model-routing', 'escalation ladder', 'dashboard', 'kpi', 'audit log', 'session ids',
                  'weekly rollup', 'cost telemetry', 'review feedback loop', 'defect router', 'calibration',
                  'post-fable economics', 'agent-team workflow', 'interventions per', 'operating ratio']),
]

def keyword_track(bid):
    b = beads[bid]
    text = ((b.get('title') or '') + ' ' + (b.get('description') or '')).lower()
    for track, kws in KEYWORDS:
        for kw in kws:
            if kw in text:
                return track
    return None

def classify(bid):
    b = beads[bid]
    if b.get('issue_type') == 'milestone':
        return 'ops-meta'
    labels = b.get('labels') or []
    if 'install' in labels:
        return 'installer'
    if 'prgroom' in labels:
        return 'prgroom'
    t = anchor_track(bid)
    if t:
        return t
    t = keyword_track(bid)
    if t:
        return t
    return 'unknown'

NONCLOSED = ('open', 'in_progress', 'blocked', 'deferred')
nonclosed_ids = [bid for bid, b in beads.items() if b['status'] in NONCLOSED]
print("nonclosed total", len(nonclosed_ids))

track_ctr = collections.Counter()
classification = {}
for bid in nonclosed_ids:
    tr = classify(bid)
    classification[bid] = tr
    track_ctr[tr] += 1

for tr, c in track_ctr.most_common():
    print(tr, c)

unknowns = [bid for bid in nonclosed_ids if classification[bid] == 'unknown']
print("\nUNKNOWN sample:")
for bid in unknowns[:40]:
    print(bid, beads[bid]['status'], beads[bid]['issue_type'], '|', beads[bid]['title'][:90])

json.dump(classification, open(args.out, 'w'))

print("\n\n=== MILESTONE MAP ===")
for mid, (name, order) in sorted(MILESTONES.items(), key=lambda x: x[1][1]):
    if mid not in beads:
        # A hard-coded milestone id absent from a partial/filtered export
        # (e.g. a scrubbed or scoped `bd export`) is a diagnostic gap, not a
        # reason to crash before the classification.json this script exists
        # to produce has been written.
        print(f"\n{name} ({mid}) -- not present in this export, skipping")
        continue
    m = beads[mid]
    children = [bid for bid in beads if parent_of(bid) == mid]
    open_desc_count = 0
    child_info = []
    for cid in children:
        cb = beads[cid]
        # count open descendants (nonclosed status) under this child
        stack = [cid]
        desc = []
        while stack:
            cur = stack.pop()
            desc.append(cur)
            kids = [x for x in beads if parent_of(x) == cur]
            stack.extend(kids)
        n_open = sum(1 for d in desc if beads[d]['status'] in NONCLOSED)
        child_info.append((cid, cb['issue_type'], cb['status'], cb['title'][:70], n_open))
    print(f"\n{name} ({mid}) status={m['status']}")
    for cid, ctype, cstatus, ctitle, nopen in sorted(child_info, key=lambda x:-x[4]):
        if nopen > 0 or cstatus != 'closed':
            print(f"  {cid} [{ctype}/{cstatus}] open_desc={nopen} | {ctitle}")
