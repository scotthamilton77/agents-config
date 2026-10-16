# Model comparison protocol

The owner paused prompt refinement and requested a higher-grade model comparison.
Run one call per unchanged PR 838, 839, 843 and 846 request using the byte-identical
candidate-3 instructions, GPT-6.1 Sol and low reasoning effort. Keep the same
Codex route, instruction isolation, shell/web settings, four selected repairs,
four clean controls and judgment rubric from the parent protocol. Only the
requested model changes. Retain the raw responses, events, settings, usage,
validation and judgments. Compare against the four candidate-3 Luna-low runs.

Use the existing four-repair, four-control threshold and judge every proposed
replacement for preserved meaning, not merely schema or lint validity. A failing
result remains a failing result; no retry replaces this fixed run. These single
runs can show a sample difference but do not establish general model reliability
or causal certainty across stochastic runs. The skill pin remains unchanged.
