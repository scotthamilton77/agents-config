from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan

_CLAUDE_ONLY_FIELDS = ("skills:", "color:", "memory:")


def transform_agent_frontmatter(content: bytes) -> bytes:
    """Translate a shared (Claude-style) agent file's YAML frontmatter into the
    form Gemini's agent loader accepts: drop Claude-only keys (skills, color,
    memory) and rewrite a comma-separated ``tools:`` string into an inline YAML
    flow sequence.

    Surgical line port of bash ``transform_gemini_agent_frontmatter``
    (scripts/install.sh:643-688): a fence-counting state machine that edits only
    the lines it must and emits every other line verbatim. That verbatim path is
    why a ``description: |-`` block scalar — and any quoting or spacing — survives
    byte-for-byte; a pyyaml round-trip would reflow it. The ``tools:`` value is
    wrapped whole (``tools: [Read, Grep]``), preserving its raw spacing, rather
    than re-serialised item by item.

    Non-UTF-8 content is returned unchanged (an undecodable agent file must not
    abort the install). Like awk, every emitted record is newline-terminated.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    if not text:
        return content  # awk's main loop never runs on a 0-byte file: empty in, empty out

    # awk reads \n-separated records; a trailing \n is a terminator, not an empty
    # final record. Drop that artifact so an unchanged file round-trips identically.
    records = text.split("\n")
    if text.endswith("\n"):
        records = records[:-1]

    out: list[str] = []
    fences = 0  # number of '---' lines seen (frontmatter is the span where == 1)
    skipping = False  # inside a stripped key's indented continuation block
    for line in records:
        if line == "---":
            fences += 1
            skipping = False
            out.append(line)
            continue
        if fences == 1:
            if skipping:
                if not line or line[0].isspace():
                    continue  # swallow the stripped key's blank/indented block
                skipping = False
            # awk's $1 splits on its default FS (space/tab only), so match the
            # first space/tab-delimited token — not str.split(), which would also
            # break on \f/\v and strip a key bash would keep.
            field = line.lstrip(" \t").split(" ", 1)[0].split("\t", 1)[0]
            if field in _CLAUDE_ONLY_FIELDS:
                skipping = True
                continue
            if line.startswith("tools:"):
                value = line[len("tools:") :].lstrip()
                if value and not value.startswith("["):
                    out.append(f"tools: [{value}]")
                    continue
        out.append(line)

    return "".join(f"{rec}\n" for rec in out).encode("utf-8")


class GeminiAdapter:
    """Adapter for Google's Gemini CLI. Probes ~/.gemini/ as a directory —
    mirrors the bash installer's [[ -d "$HOME/.gemini" ]] detection."""

    name: str = "gemini"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".gemini"

    def dest_dir(self, home: Path) -> Path:
        return home / ".gemini"

    def is_detected(self, home: Path) -> bool:
        return (home / ".gemini").is_dir()

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
    ) -> bool:
        return True

    def post_staging_transforms(self, plan: StagingPlan, io: IOPort) -> StagingPlan:
        """Apply the Claude→Gemini agent frontmatter transform to every staged
        ``agents/`` file. Mirrors bash Phase 6.6 (scripts/install.sh:892-897):
        emits one verbose phase line when agent files are present, then rewrites
        each in place. Non-agent items and directory entries are left untouched.
        """
        logged = False
        for relpath, item in list(plan.items.items()):
            if item.namespace != "agents" or item.content is None:
                continue
            if not logged:
                io.info("Transforming agent frontmatter for Gemini", verbose=True)
                logged = True
            new_content = transform_agent_frontmatter(item.content)
            if new_content != item.content:
                plan.items[relpath] = replace(item, content=new_content)
        return plan
