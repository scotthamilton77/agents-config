# User Prompts

Rules for asking the user a question and stopping for an answer.

- **`AskUserQuestion` is capped at 4 options.** The tool's input schema enforces `options.maxItems = 4` (and `questions.maxItems = 4`). A call with 5+ options — or 5+ questions in one call — fails input validation at runtime. Audit any skill, command, or agent prompt that calls `AskUserQuestion` against this cap before shipping it.
- **For 5+ options, use a prose letter-prompt fallback.** Print the options inline as a lettered list (A, B, C, D, E, ...), one per line, each with a one-line description. The letter is the user's reply token; do not embed the letter inside the option label.
- **Letter-prompts require an EXPLICIT wait-gate.** Unlike `AskUserQuestion` (which is structurally turn-ending), prose prompts are a soft convention — the model will keep going unless told to stop. After the lettered list, write a literal "STOP. Wait for the user's single-letter reply before continuing." Do NOT infer the user's choice from prior context. On the reply, parse the first letter case-insensitively; if ambiguous (no letter, multiple letters, or outside the offered range), ask once for clarification then halt rather than guessing.
