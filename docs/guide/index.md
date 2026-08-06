# User Guide

> **This harness is being rebuilt, and this guide is catching up.** A large part
> of what the guide originally described — the completion gate, the merge guard,
> the PR-feedback skills, the planning and test-first skills — was retired and
> its replacement is not finished. Every page below has been swept so that it
> either describes something that exists or says plainly that it does not, but
> the shape of the workflow will keep changing until the rebuild closes. The
> plan of record is
> [`docs/specs/2026-07-21-harness-rework-way-forward.md`](../specs/2026-07-21-harness-rework-way-forward.md).
> Read it before you build a habit on anything here.

This guide is for someone who wants to **use** the deployed assets from this
repo — the skills, commands, and rules it installs into your AI coding
assistant — to run an opinionated, mostly-autonomous software development
lifecycle (SDLC). It is not a guide to hacking on the repo itself (see the
root `AGENTS.md` for that).

## What you get

Installing this configuration turns a bare AI coding CLI (Claude Code, Codex
CLI, Gemini CLI, or OpenCode) into one that follows a **portable discipline
layer**: a consistent way of taking work from idea → design → implementation →
verified, delivered change, with humans concentrated on judgment and thin
verification gates rather than babysitting.

The mental model has four kinds of pieces. Three of them ship today:

| Piece | Answers | Status |
|-------|---------|--------|
| **Rules** | the *always-on* contract | Ships. The laws, the decide-vs-escalate matrix, and the hard lines install as your assistant's instruction file; one further rule covers delegation. |
| **Skills** | *how* to do a thing | Ships, in a much smaller set than before — design and spec-writing, review, delegation, git cleanup, handoff. |
| **Commands** | a thing you invoke by name | Ships. One slash command, Claude Code only. |
| **Agents** | *who* does a thing | **Nothing ships.** The role-based agent definitions were retired and have no replacement yet. |
| **Gates** | *proof* before "done" | **No deployed implementation.** The completion gate and merge guard were retired; the contracts that replace them are still being built. |

The through-line is **evidence before assertion** — every completion claim
backed by a mechanical gate, and under-specified work bounced back *before*
implementation. That is the intent the rebuild is working toward; it is not
currently enforced by anything you install.

## How to read this guide

1. **[Getting Started](./getting-started.md)** — prerequisites, install, and what lands where.
2. **[Configuration](./configuration.md)** — review `settings.json`, teach the assistant your domain, and understand which `project-config.toml` sections are live.
3. **[The SDLC Workflow](./sdlc-workflow.md)** — the intended loop, phase by phase, with each phase marked for whether it has a deployed implementation.
4. **[Reference](./reference.md)** — a placeholder; the cheat-sheet tables are waiting on the rebuild.

If you just want to install and go, read Getting Started, then keep The SDLC
Workflow open as you work.
