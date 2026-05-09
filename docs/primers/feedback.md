Looks good so far.  HOWEVER, I'm looking at some of the primer material you captured. I want to discuss that before we come back to stamping the architecture approved. NOTE that I've made edits to the primer files, so re-read them before updating.  The comments below are additional to the edits I've made.

# GENERAL (applies to all):
- Be careful to limit code blocks where the agent would seem instructed to execute a series of shell commands or write-and-execute a code block on the fly - consider helper scripts where CLI calling and/or code execution should be deterministic.
- Avoid using prose to prescribe complex deterministic logic such as branching, sequencing of steps etc.  If a shell script is the right tool, create it as a helper and reference the shell script.

# RULES:
- yes, these are a claude-code-only construct, but the content within them needs to be available in all agents, so the install script [eventually] needs to embed these rules in the agent files for codex, gemini, etc.  The point being while these are currently defined as claude-only, consider them universal in applicability, BUT apply the best practices for claude code rules to these constructs.
- I noticed that your primer doesn't mention path scoping - which tells me you didn't read the docs completely.  Look at https://code.claude.com/docs/en/memory#organize-rules-with-claude/rules/.  In addition to that bit of important knowledge, a best practice embedded in that page section is "Rules load into context every session or when matching files are opened. For task-specific instructions that don’t need to be in context all the time, use skills instead, which only load when you invoke them or when Claude determines they’re relevant to your prompt."
- There's content in that primer that I question whether it should be.  The reader of the primer should understand (a) how rules work in claude - and best practices about them, and (b) how they are organized in this project (e.g. sourced under src/**/... and "installed" when necessary into the user space).  (We can annotate the future intent of making these embed into other agents' instructions so the reader doesn't complain it's claude-only.)  EVERYTHING ELSE IS NOISE.  Listing the rules included in the project: noise.  Instruction hierarchy: noise unless you can prove that's truly how it works (which I bet you can't b/c superpowers is not special/built into claude code).
- You mention "Advisory language belongs in skills or INSTRUCTIONS.md: noise (the bit about advisory vs. normative drift in the quality issues table: just remove the "... - or move to a skill").

# AGENTS:
Read https://code.claude.com/docs/en/sub-agents and cross-check your docs, and apply any new learnings to the contents of this file.

# SKILLS:
Read https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices and cross-check your docs, and apply any new learnings to the contents of this file.
