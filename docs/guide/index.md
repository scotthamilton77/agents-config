# User Guide

This guide is for someone who wants to **use** the deployed assets from this
repo — the agents, skills, commands, and rules it installs into your AI coding
assistant — to run an opinionated, mostly-autonomous software development
lifecycle (SDLC). It is not a guide to hacking on the repo itself (see the
root `AGENTS.md` for that).

## What you get

Installing this configuration turns a bare AI coding CLI (Claude Code, Codex
CLI, Gemini CLI, or OpenCode) into one that follows a **portable discipline
layer**: a consistent way of taking work from idea → design → implementation →
verified, delivered change, with humans concentrated on judgment and thin
verification gates rather than babysitting.

The mental model has four kinds of pieces:

| Piece | Answers | Example |
|-------|---------|---------|
| **Rules** | the *always-on* contract | "find root causes, not band-aids"; the decide-vs-escalate matrix |
| **Skills** | *how* to do a thing | `grilling`, `test-driven-development`, `verify-checklist` |
| **Agents** | *who* does a thing | `quality-reviewer`, `tech-lead` |
| **Gates** | *proof* before "done" | the three-tier completion gate; `merge-guard` |

The through-line: **evidence before assertion.** Every completion claim is
backed by a mechanical gate (tests, build, lint, review), and under-specified
work is bounced back *before* implementation instead of after a wasted run.

## How to read this guide

1. **[Getting Started](./getting-started.md)** — prerequisites, install, and what lands where.
2. **[Configuration](./configuration.md)** — personalize the personas, tune `settings.json`, set your project's merge policy, wire up work tracking.
3. **[The SDLC Workflow](./sdlc-workflow.md)** — the opinionated loop, phase by phase: capture → brainstorm → plan → TDD → completion gate → delivery → merge.
4. **[Reference](./reference.md)** — cheat-sheet tables: skills by phase, agents, commands, rules, key settings.

If you just want to install and go, read Getting Started, then keep The SDLC
Workflow open as you work.
