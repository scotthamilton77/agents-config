"""Build the layout-ready backlog graph JSON from a bd export + track
classification. Interim census tool -- see README.md for the retirement note.
"""
import argparse
import collections
import datetime
import json
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--export", required=True, help="bd export JSONL path")
parser.add_argument("--classification", required=True, help="classify.py output JSON path")
parser.add_argument("--out", required=True, help="graph JSON output path")
args = parser.parse_args()

beads = {}
with open(args.export) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        b = json.loads(line)
        beads[b['id']] = b

MILESTONES = {
    'agents-config-wgclw': ('Milestone M0 — Discipline-layer rearchitecture', 0),
    'agents-config-abn9': ('Milestone M1 — Post-Fable operations', 1),
    'agents-config-qn0g': ('Milestone M2 — Brainstorm-readiness gate', 2),
    'agents-config-vaac': ('Milestone M3 — Worker fleet through PR autonomy', 3),
    'agents-config-t142': ('Milestone M4 — Overnight autonomy', 4),
    'agents-config-yf2ov': ('Milestone M5 — Post-MVP capabilities', 5),
    'agents-config-uxns2': ('Milestone PORT — Portable discipline layer', 6),
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
    for a in ancestors(bid):
        if a in MILESTONES:
            return a
    return None

classification = json.load(open(args.classification))
NONCLOSED = ('open', 'in_progress', 'blocked', 'deferred')
nonclosed_ids = set(bid for bid, b in beads.items() if b['status'] in NONCLOSED)

# Determine which closed epics/milestones are needed as containers (ancestor of a non-closed bead)
needed_closed = set()
for bid in nonclosed_ids:
    for a in ancestors(bid):
        if beads[a]['status'] == 'closed':
            needed_closed.add(a)

include_ids = nonclosed_ids | needed_closed

def clean_desc(b):
    d = (b.get('description') or '').replace('\n', ' ').replace('\r', ' ')
    d = re.sub(r'\s+', ' ', d).strip()
    return d[:200]

def inherited_track(bid):
    # `classification` only covers non-closed beads (classify.py's own
    # NONCLOSED scope). A closed container is included here precisely
    # because it has a non-closed descendant (`needed_closed`'s own
    # construction), so inherit the majority track among its classified
    # descendants instead of defaulting to 'unknown' -- a wrong color and
    # spurious cross-track edges on every dependency touching it otherwise.
    counts = collections.Counter()
    stack = [bid]
    seen = {bid}
    while stack:
        cur = stack.pop()
        for cid in beads:
            if cid not in seen and parent_of(cid) == cur:
                seen.add(cid)
                stack.append(cid)
                if cid in classification:
                    counts[classification[cid]] += 1
    if not counts:
        return 'unknown'
    return counts.most_common(1)[0][0]

bead_records = []
for bid in sorted(include_ids):
    b = beads[bid]
    if bid in classification:
        track = classification[bid]
    elif b.get('issue_type') == 'milestone':
        track = 'ops-meta'
    elif bid in needed_closed:
        track = inherited_track(bid)
    else:
        track = 'unknown'
    rec = {
        'id': bid,
        'title': b['title'],
        'status': b['status'],
        'priority': b.get('priority'),
        'type': b.get('issue_type'),
        'track': track,
        'milestone': milestone_of(bid),
        'parent': parent_of(bid),
        'labels': b.get('labels') or [],
        'desc': clean_desc(b),
    }
    if bid in needed_closed:
        rec['closed_container'] = True
    bead_records.append(rec)

edges = []
seen = set()
for bid in sorted(include_ids):
    b = beads[bid]
    for d in sorted(b.get('dependencies') or [], key=lambda d: (d['issue_id'], d['depends_on_id'], d['type'])):
        frm, to, typ = d['issue_id'], d['depends_on_id'], d['type']
        if frm not in include_ids or to not in include_ids:
            continue
        key = (frm, to, typ)
        if key in seen:
            continue
        seen.add(key)
        edges.append({'from': frm, 'to': to, 'type': typ})

graph = {
    'generated': datetime.date.today().isoformat(),
    'milestones': [
        {'id': mid, 'title': beads[mid]['title'], 'status': beads[mid]['status'], 'order': order}
        for mid, (short, order) in sorted(MILESTONES.items(), key=lambda x: x[1][1])
        if mid in beads  # a hard-coded milestone absent from a partial/filtered export
                          # is a diagnostic gap, not a reason to crash mid-render
    ],
    'tracks': ['installer', 'prgroom', 'workcli', 'pdlc-orchestrator', 'holding-place', 'vizsuite',
               'skills-discipline', 'portability', 'ops-meta', 'unknown'],
    'beads': bead_records,
    'edges': edges,
}

with open(args.out, 'w') as f:
    json.dump(graph, f, indent=2)

print("beads:", len(bead_records), "edges:", len(edges))
print("closed containers included:", len(needed_closed))
