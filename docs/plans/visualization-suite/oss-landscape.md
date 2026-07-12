# OSS-Landscape Survey — Visualization-Suite Data Pipeline

WORKING NOTE for the operationalization discussion (feeds the grouped spec's F0
section). Produced 2026-07-12 by a 5-sweep background survey (git mining, viz
data formats, work-graph models, LLM relation inference, freshness caching) +
verified synthesis. Each candidate's license/maintenance was independently
fetched; unverified sub-claims are flagged at the bottom.

## 1. Shortlist (grouped by pipeline stage)

| Stage | Tool | Verdict | License | Maint. (verified) | What we take |
|---|---|---|---|---|---|
| **EXTRACT** | **PyDriller** | adopt | Apache-2.0 | v2.10, 2026-07-01; ~966★ | Per-commit/per-file churn, authorship, diff walk; scope to PR merge-base..head |
| **EXTRACT** | **scc** | adopt | MIT | active, ~8.5k★ | `scc --format json --by-file` → per-file LOC/comment/complexity for V1 heat axis |
| **EXTRACT** | Perceval (GrimoireLab) | steal | GPL-3.0 | active, GL 1.20 2026-03 | Versioned extraction-envelope shape (uuid/origin/updated_on/data); ignore the Elastic/Kibana platform |
| **EXTRACT** | code-maat | steal | GPL-3.0 | dormant (2025-07); ~2.6k★ | Logical/temporal-coupling algorithm + its `git log` incantation — reimplement in Python, don't take the JVM dep |
| **EXTRACT** | git-truck | steal | MIT | active, ~748★ | UX only (drill-down, hover panel, legend toggle) — Node/local-server, violates single-file constraint |
| **DATA CONTRACT** | **CodeCharta cc.json** | steal | BSD-3 | v1.143, 2026-06-23; ~476★ | The V1 schema shape: recursive node tree + generic `attributes` map + top-level `edges[]` + self-describing `attributeDescriptors`. Drop the MD5 wrapper and the app |
| **DATA CONTRACT** | d3-hierarchy | steal | ISC | active (already ours) | Terminal consumer contract — confirms cc.json-shaped tree feeds `d3.hierarchy().sum()` with zero translation |
| **DATA CONTRACT** | emerge | steal | MIT | active (2026-07-12); ~980★ | Metric checklist (fan-in/out, Tornhill complexity, Louvain) + node-link JSON shape as V2 edge-graph prior art |
| **DATA CONTRACT** | Gource log fmt | steal | GPL-3.0 | active, 0.56 2026-03 | Minimal 5-field `ts\|user\|A/M/D\|file\|color` event stream as V3's adapter-friendly intermediate |
| **RENDER (V2)** | **d3-dag / dagre** | adopt | MIT | d3-dag active 2026-07-12; ~1.5k★ | Sugiyama crossing-min layout from `{nodes, edges}` for the cross-plan overlay; inlineable, no build step |
| **RENDER (V2)** | Mermaid gantt | steal | MIT | very active; ~89k★ | Zero-build inline JS Gantt for the lane/timeline sub-view; generate its syntax from our JSON, not vice-versa |
| **V2 MODEL** | Plane / OpenProject | steal | AGPL-3.0 / GPL-3.0 | both very active | Typed directed edge table `{from,to,relation_type[,delay]}` kept *separate* from issue content; "draw only blocks/blocked-by, badge the rest" clutter-avoidance pattern |
| **INFER** | Graphiti | steal | Apache-2.0 | v0.29.2 2026-06-08; ~28.6k★ | Bi-temporal edge model + episodic incremental re-inference + per-edge provenance. No human review loop |
| **INFER** | cognee | steal | Apache-2.0 | v1.3.0 2026-07-12; ~27.6k★ | Strongest provenance story (`get_memory_provenance_graph()`); typed DocumentChunk→Entity edges to mirror in our persistence |
| **INFER** | LlamaIndex PropertyGraphIndex | steal | MIT | active | Schema-guided extraction: constrain the LLM to a fixed relation enum (BLOCKS/OVERLAPS/CONFLICTS/DEPENDS_ON) — most directly reusable idea, makes review + diffing tractable |
| **INFER** | GraphRAG | steal | MIT | active; ~33.6k★ | Parquet entity/relationship/community schema with source-chunk FKs — study, don't adopt (batch-oriented, incremental still clunky) |
| **FRESHNESS** | **doit** | adopt | MIT | active (1,519 commits); ~2.1k★ | Content-hash (md5) file-dep task DAG — the orchestration layer; no daemon, JSON files as `targets` |
| **FRESHNESS** | **diskcache** | adopt | Apache-2.0 | mature; ~2.9k★ | Explicit composite-fingerprint → JSON-blob KV store (SQLite+files, no server) for the LLM-call memoization |
| **FRESHNESS** | joblib.Memory | adopt (alt) | BSD-3 | v1.5.3 2025-12; ~4.4k★ | Drop-in `@memory.cache` if arg-hashing suffices; diskcache preferred when the real key is composite |
| **FRESHNESS** | DVC / Turborepo | steal | Apache-2.0 / MIT | active | Composite-hash recipe (`hash = f(file, prompt-version, model-id, upstream-hash)`) and `dvc.lock` manifest shape — ~30-line Python helper, not the tool |

**RENDER (V1 tree):** nothing beats self-contained D3 — no shortlist entry.
git-truck and CodeCharta both prove the use case but ship a server/app;
confirmed as expected.

## 2. What we take vs build — the load-bearing picks

- **PyDriller (adopt):** the commit-range walker feeding V1's churn/authorship
  ledger. It is *not* a GitHub client — PR metadata (reviews, labels) still
  needs PyGithub/`gh` layered on and reconciled by commit-sha membership. That
  join is ours (see gaps).
- **scc (adopt):** shell out for per-file complexity/LOC rather than
  reimplement counting. Flat per-file array → we fold into the hierarchical
  tree by path.
- **cc.json (steal the shape):** adopt tree+attributes+edges+descriptors as
  our de-facto schema. Understand this as "best prior art," not a standard
  (see gaps). Drop the checksum wrapper.
- **d3-dag (adopt):** the actual V2 renderer. Feeds on beads' dependency
  edges; plan-lane/territory/conflict-edge *semantics* on top are ours.
- **doit + diskcache (adopt):** doit for stage-level "skip if content
  unchanged" DAG; diskcache for the composite-fingerprint memoization of the
  expensive LLM call. Together they cover FRESHNESS with no orchestrator.
- **LlamaIndex schema-guided extraction + Graphiti provenance/incremental
  (steal):** compose the INFER stage from these; the human accept/reject queue
  is ours.

## 3. Verified gaps (→ BUILD)

1. **PR-scoped git+GitHub fused extraction.** Every git miner (PyDriller,
   code-maat, git2net) knows commit ranges but not PRs; every forge-API lib
   (Perceval, PyGithub) knows PRs but not churn/coupling. Nothing joins "which
   files coupled-changed" with "inside which PR." **BUILD** the reconciler
   (PyDriller walk + `gh`/PyGithub, joined by sha).
2. **Cross-plan dependency/overlap/conflict overlay as a first-class
   renderable model.** GitHub Projects roadmap draws *no* dependency edges
   (github/roadmap#956/#215 open for years); OpenProject/Plane draw only
   intra-hierarchy edges and badge the rest; GitLab's cross-epic timeline is
   proprietary EE-only. Plan-as-lane grouping + typed conflict-edge geometry +
   territory shading has no OSS precedent. **BUILD** on borrowed layout
   primitives (d3-dag).
3. **LLM inference of plan-doc relationships with all three of {per-edge
   provenance, incremental single-doc re-inference, human accept/reject}.**
   Every candidate delivers at most two, always as a side-effect of a
   different primary goal. The **human review queue** (proposed edges as a
   pending state, gated by CLI/light UI) has no OSS home. Purpose-built
   requirements/planning-doc conflict detection surfaced only academic
   prototypes with no maintained code. **BUILD** the review-queue layer over
   borrowed extraction/provenance patterns.
4. **Composite-fingerprint LLM-call cache as a packaged library.** Matches
   were either generic arg-hashing memoizers (joblib/diskcache/cachew) or full
   pipeline systems (DVC/doit/Turborepo) — none treats "prompt-version +
   model-id" hashing or token-cost as first-class. **BUILD** the ~30-50 line
   sha256 manifest helper; use diskcache/doit as the substrate.
5. **A neutral "SARIF-for-treemaps" interchange standard.** No IETF/OASIS
   standard, no schema-only PyPI/npm package, no cross-tool consortium format.
   cc.json is renderer-coupled. **BUILD** on cc.json's shape as our own
   de-facto contract — not adopting a standard, because none exists.

## 4. Bottom line

The pipeline's **mechanical edges stand firmly on OSS shoulders**: EXTRACT
(PyDriller + scc), FRESHNESS (doit + diskcache), and V2 RENDER (d3-dag +
Mermaid) are all mature, correctly-licensed, and directly adoptable — that's
roughly half the pipeline bought, not built. The **DATA CONTRACT is
borrowed-shape, not bought**: cc.json is the best prior art and we adopt its
structure, but no renderer-independent standard exists, so the schema is ours
to own. The **hard, differentiating middle — the git+GitHub PR-join extractor,
the cross-plan overlay semantics, and the human-in-the-loop edge-review layer
for LLM inference — is genuinely unaddressed OSS territory and is ours to
build**, though each sits on borrowed primitives (sha joins, d3-dag layout,
LlamaIndex/Graphiti extraction). Net: buy the plumbing, borrow the schema,
build the three novel joins that make this suite specific to an AI-agent
delivery repo.

**Verification flags:** All adopt-candidates independently confirmed (license
+ maintenance + behavior). Two sub-claims did **not** surface in fetch and
remain unverified — (a) CodeCharta's cc.json **v1.6 per-File `checksum`** for
incremental re-analysis (schema changelog exists but the checksum field wasn't
confirmed); (b) doit's dependency check being **MD5 content-hash vs mtime**
(README says "re-runs only what changed" but did not name the mechanism — it
is md5 by doit's documented default, but the fetch didn't prove it). Confirm
both by reading source before designing on them. Proprietary reference points
(GitHub Projects v2, GitLab Roadmap) are non-OSS and correctly excluded from
adoption.
