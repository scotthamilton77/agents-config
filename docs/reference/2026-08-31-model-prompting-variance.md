# Per-Model Prompting Variance

**Sources read: 2026-08-31.** Companion to `model-catalog.md`: that file answers
*which model* a dispatch should pick; this one answers whether the *prompt and
parameters* should change once it has. Findings are true of the cited sources as
they stood on the read date; provider guidance moves.

**Question.** This repo dispatches the same prompts to Claude, GPT tiers (via
Codex CLI), and GLM / Kimi / DeepSeek / Gemini (via OpenRouter). Do documented
per-model prompting differences warrant per-model prompt variants at the
dispatch sites?

**Answer, in one line.** No per-model *prose* forks — the folklore-level style
differences ("GLM needs mechanical steps", "DeepSeek needs encouragement") have
no first-party backing — but per-model *parameters* (temperature, token floors,
reasoning passthrough) are documented, conflicting, and currently unmanaged, and
shared prompts should be written to an intersection dialect that every family
tolerates.

---

## What the repo does today

Every dispatch mechanism sends an identical prompt regardless of target model.
This is deliberate doctrine, not drift — the review-panel design states "the
model is the dispatcher's to pick, every time", and no prompt renderer inspects
the transport.

| Dispatch site | Routes to | Prompt varies by model? |
|---|---|---|
| `src/user/.claude/skills/review-panel/contracts.json` + `emit_prompts.py` | Review lenses → Codex or OpenRouter by vendor class; no model named in config | No — `render_prompt()` never sees the transport |
| `src/user/.claude/skills/ac-attack/lenses.json` | AC-attack lenses → Codex / OpenRouter | No |
| `src/user/.claude/skills/openrouter-claude-subagent/` (`scripts/run.js`, `scripts/proxy.js`) | Gemini flash tiers, Kimi k2.6 / k2.7-code / k3, GLM (roster in `references/model-routing.md`) | No — proxy forwards unmodified; model is a `--model` flag. **No sampling params pinned either** — provider defaults apply |
| `src/plugins/codex/.claude/skills/delegating-to-codex/SKILL.md` | `gpt-5.6-sol` / `terra` / `luna`, `gpt-5.3-codex` | No — tier picked by task profile, same mandate |
| `src/user/.claude/skills/choosing-a-delegate/SKILL.md` | Vendor-selection logic only | n/a |
| `packages/prgroom/src/prgroom/agent/dispatcher.py` | Fallback chains crossing tiers (`ollama gemma4` → `haiku` → `gpt-5.6-luna`; `opus[1m]` → `gpt-5.6-terra`) | No — one template per contract (`load_prompt(self._contract)`), served unchanged to every rung |
| `packages/grillui/src/grillui/drivers.py` (`request_body`) | Fast tier defaults to `google/gemini-3.5-flash-lite` (`tiers.py`) | No — and it pins `temperature: 0` model-blind; see Gemini finding below |

---

## What the providers document

### OpenAI (GPT-5.x, via Codex)

- **Contradiction sensitivity — the strongest documented style claim of any
  vendor.** "Poorly-constructed prompts containing contradictory or vague
  instructions can be more damaging to GPT-5 than to other models, as it expends
  reasoning tokens searching for a way to reconcile the contradictions."
  (<https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide>)
  The GPT-5.1 guide's remedy: "clarify conflicting rules, remove redundant or
  contradictory lines, tighten vague guidance."
  (<https://developers.openai.com/cookbook/examples/gpt-5/gpt-5-1_prompting_guide>)
- **Persistence framing is native vocabulary.** OpenAI recommends injecting
  "keep going until the user's query is completely resolved" / "be extremely
  biased for action" into agentic prompts (same guides). Claude prompts don't
  carry this by default.
- Tool-preamble cadence guidance exists for Codex specifically
  (<https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide>).

### Google (Gemini 3.x)

- **Manual CoT scaffolding is documented as harmful:** Gemini 3 "may
  over-analyze verbose or overly complex prompt engineering techniques used for
  older models"; the guide says to simplify prompts and use `thinking_level`
  instead. (<https://ai.google.dev/gemini-api/docs/gemini-3>)
- **Temperature must stay at 1.0:** "we strongly recommend keeping the
  temperature parameter at its default value of 1.0"; lowering it "may lead to
  unexpected behavior, such as looping or degraded performance." (same guide)
  This collides directly with grillui's `temperature: 0` pin on its
  Gemini-flash fast tier — reproducibility for schema extraction was the
  rationale there, and it is exactly the setting Google warns against.
- General guidance recommends delimiters, few-shot examples, and
  context-before-instructions ordering.
  (<https://ai.google.dev/gemini-api/docs/prompting-strategies>)

### Anthropic (the house baseline)

- **Goal-level framing is preferred over prescriptive steps:** "Prefer general
  instructions over prescriptive steps … Claude's reasoning frequently exceeds
  what a human would prescribe."
  (<https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices>)
- **Aggressive imperatives now overtrigger:** prompts written to fix
  undertriggering on older models ("CRITICAL: You MUST…") cause overtriggering
  on current models; Opus 5 over-verifies when given verification instructions
  it no longer needs. (same page)
- **Cross-family transfer is not free, by Anthropic's own admission:** "If
  you've done lots of tweaking to your prompt, it's likely to be well-tuned to
  OpenAI specifically, and you should consider reworking it for Claude."
  (<https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk>)

### Zhipu / Z.ai (GLM)

- No first-party prompting-style guidance exists. Function-calling docs give
  generic schema hygiene (meaningful names, detailed descriptions; only
  `tool_choice: auto` is supported).
  (<https://docs.z.ai/guides/capabilities/function-calling>)
- Z.ai's Claude Code integration routes Claude Code's *unmodified* prompts to
  GLM via an Anthropic-compatible endpoint — a first-party (if commercial)
  signal that GLM is meant to tolerate Claude-style prompting as-is.
  (<https://docs.z.ai/scenario-example/develop-tools/claude>)
- No temperature recommendation for coding; the API docs' own samples use 1.0
  and 0.6 inconsistently. (<https://docs.z.ai/guides/llm/glm-4.6>)

### DeepSeek

- **Temperature is task-split by first-party table:** coding/math → 0.0;
  general conversation → 1.3.
  (<https://api-docs.deepseek.com/quick_start/parameter_settings/>) The R1
  reasoner instead wants 0.5–0.7 (0.6 recommended), and in thinking mode
  temperature has reduced effect.
  (<https://api-docs.deepseek.com/guides/thinking_mode/>)
- **R1 only: "Avoid adding a system prompt; all instructions should be
  contained within the user prompt."**
  (<https://github.com/deepseek-ai/deepseek-r1>) Never restated nor withdrawn
  for V3.x — treat as R1-specific and unconfirmed elsewhere.
- The "narrates tool calls instead of making them" behavior is *not*
  acknowledged in any DeepSeek documentation; evidence is third-party bug
  reports only (e.g. <https://github.com/deepseek-ai/DeepSeek-V3/issues/1244>).
  The "encourage it to act" folklore is unsourced at the first-party level.

### Moonshot (Kimi)

- **A documented parameter conflict inside one family:** `Kimi-K2-Instruct`
  recommends setting `temperature = 0.6`
  (<https://huggingface.co/moonshotai/Kimi-K2-Instruct>), while the
  thinking/code variants (`kimi-k2.7-code`, `kimi-k2.6`) **forbid** setting
  temperature at all, require `max_tokens >= 16000` for tool calling, and
  require `reasoning_content` passed back on multi-turn tool calls.
  (<https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model>)
  A single pinned temperature across Kimi variants violates one side or the
  other silently.
- No stylistic prompting guidance at all.

### Comparative evidence

- Prompt-*format* sensitivity is large and does not vanish with scale or
  instruction tuning: up to 76 accuracy points from formatting changes alone in
  few-shot settings (Sclar et al., FormatSpread,
  <https://arxiv.org/abs/2310.11324>), and proprietary reasoning-tier models
  are not automatically the robust ones on this axis.
- No source runs the same agentic prompt across Claude / GPT-5 / Gemini 3 /
  the CN families side by side. The decisive experiment does not exist in
  public.

---

## Not settled

- Whether DeepSeek R1's no-system-prompt rule applies to V3.x (silent, not
  contradicted).
- Whether GPT-5's contradiction sensitivity is benchmarked or
  vendor-qualitative (the guides don't say).
- Any stylistic sensitivity for GLM / Kimi / DeepSeek — the providers document
  nothing; absence of evidence, not evidence of absence.
- Whether Google's Gemini-3 temperature warning measurably bites
  `gemini-3.5-flash-lite` on grillui's constrained (`response_format`
  json_schema) extraction turns — schema-constrained decoding may damp the
  failure mode the warning describes.

---

## Recommendation

**Do not fork prompts per model.** No provider documents a stylistic dialect
requiring different prose per family, two (Z.ai, Anthropic-compatible
endpoints generally) actively sell unmodified-prompt portability, and per-model
prose variants would multiply every future prompt edit across N copies —
exactly the add-operator-without-delete-operator failure this repo's charter
guards against.

**Do three narrow things instead:**

1. **Write shared dispatch prompts to the intersection dialect.** One style is
   documented-safe everywhere, and it is close to what the house already does:
   goal-level framing with an explicit deliverable contract; no redundant or
   conflicting imperatives (GPT-5 degrades on them); no manual CoT scaffolding
   (Gemini 3 over-analyzes it); no ALL-CAPS "CRITICAL/MUST" pressure (current
   Claude overtriggers on it); consistent delimiter formatting (format
   sensitivity swings double digits on every family tested). This is an
   authoring guideline for the existing lens/mandate prose, not a new artifact.
2. **Centralize per-model *parameters*, not prose.** The documented variance is
   in knobs: DeepSeek 0.0-coding / 0.6-reasoner, Kimi's set-it/forbid-it split,
   Kimi's 16k token floor and `reasoning_content` passthrough, Gemini 3's
   temperature-stays-1.0. Today no OpenRouter dispatch pins any of these
   (provider defaults apply), which is accidentally safe — the hazard arrives
   the day someone pins a "sensible" temperature across the roster. The
   `openrouter-claude-subagent` roster in `references/model-routing.md` is the
   natural home for a per-model parameter column; grillui's `temperature: 0`
   on a Gemini flash tier is the one live instance to re-verify against
   Google's warning.
3. **Allow one-line per-transport addenda where a vendor asks for them.** The
   only documented case today: OpenAI recommends explicit persistence framing
   ("keep going until resolved") for agentic GPT runs — a single line the Codex
   dispatch path could append without touching shared prose. R1's
   no-system-prompt rule joins this list only if an R1-class reasoner ever
   enters the roster.
