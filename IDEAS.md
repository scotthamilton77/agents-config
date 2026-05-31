### New State - Ideas to keep us on track

Your job, agent, is to also keep these in mind as we continue to brainstorm and develop the details of the target architecture.  Eventually we can purge these from the project context once we fully capture this scope in the backlog.

#### Core Orchestration & Architecture
* **The Deterministic Code-First Orchestrator:**
    * Move orchestration logic out of Markdown (`SKILL.md`) and Bash scripts into a compiled/scripted language (Python/Go).
    * The orchestrator manages state transitions; agents are treated as isolated functions that read specs and write code.
* **WMS (Work Management System) Decoupling:**
    * Abstract the underlying tracker (Beads, GitHub, Jira) behind a CLI wrapper.
    * Execution agents must have ZERO awareness of the WMS. The Orchestrator handles all state updates and graph traversal.

#### The Mechanical Pipeline Gates
* **The "Agent-Ready" Thin Slice:**
    * A Unit of Work (UoW) is only ready when it is atomic and backed by machine-verifiable Acceptance Tests (ATs).
    * No judgmental/subjective criteria allowed in the execution phase.
* **The Red/Green Mechanical Gate:**
    * The transition from Test Writing to Implementation is gated by a deterministic runner (`npm test`, `pytest`).
    * Tests must compile against stubs and actively *fail* before implementation begins. No LLM "vibe checks" allowed for this gate.

#### Feedback Loops & Error Handling
* **The 3-Strike Circuit Breaker:**
    * Hardcode a limit on adversarial AI-to-AI review cycles. If an agent fails to pass the mechanical tests/reviews 3 times, the pipeline halts. Throw away the dirty git branch.
* **Dual Autopsy Agents (RCA):**
    * Triggered on a 3-Strike failure. Generates machine-readable facts, not excuses.
    * *Specification RCA Agent:* Looks for logical contradictions, missing context, and untestable criteria.
    * *Architecture Health RCA Agent:* Looks for tight coupling, legacy tech debt, and state contamination.
* **The Historical Linter (Pre-Mortem Agent):**
    * Reviews specs *before* execution, but only allowed to flag weaknesses if it can cite a specific, documented historical failure or ADR. Eliminates strawman hallucinations.

#### UX & Human-in-the-Loop
* **The "Cool Idea" Quarantine:**
    * A behavioral protocol for the interactive brainstorming agent. Actively isolates out-of-scope, complex ideas into an Icebox so the human can focus on the immediate thin slice without fear of losing the idea.
* **Visual AT Analysis Engine (Concept):**
    * Escape "bullet-point review hell" using spatial/visual node graphs (e.g., D3.js).
    * Map ATs against stable `CONTEXT.md` domains. Size by complexity, color by risk.
    * Use multimodal AI to analyze the topological graph and highlight architectural violations instantly.
* **Dreaming / Subconscious Backlog Process (Concept):**
    * Verbatim (Scott, 2026-05-17, while designing the PDLC state machine in `agents-config-wgclw.1`): a background process that periodically scans the backlog looking for new connections, broken connections, stale connections, between work items. Consider this a "dreaming" process or subconscious process of strengthening edges between memory nodes.
    * Purpose: supports topic-correlated Idea resurfacing (option C from the holding-place exit-condition tradeoff) AND sequencing recommendations during "what's next to work on" pulls — e.g. "you want to work on X, but Y might be a blocking dependency for X."
    * Provenance backreference: captured live during the brainstorm of `agents-config-wgclw.1` (PDLC State Machine Design); parked here pending an official Capture surface.

#### Architecture and Objectives
* **Architecture Context:**
  * A project needs a high-level architecture (CONTEXT.md, HLD artifacts (TBD)) and every objective must be linkable to a specific part of the architecture.
* **Architecture Heatmap:**
  * Given an HLD, we should be able to show the work associated with the HLD components (at whatever state they are in) to show which parts are theoretical, which are planned, which are done, and to whatever degree.  This can help in prioritization/bucketing, but also allows us to maintain focus on specific components without losing track of the rest of the architecture, and perform audits to see where we're veering off MVP or tracer bullet goals.

