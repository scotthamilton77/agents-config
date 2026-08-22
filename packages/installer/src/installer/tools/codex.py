from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.admission import DIR_RECORD_FILE, entry_file_text
from installer.core.capabilities import is_user_invoked
from installer.core.model import Contribution, FileKind

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagedItem, StagingPlan

#: Where Codex reads a skill's policy declaration: a sidecar file beside
#: SKILL.md, relative to the deployed skill directory.
SIDECAR_RELPATH = Path("agents/openai.yaml")

#: The generated declaration. ``allow_implicit_invocation`` must be a real YAML
#: boolean — Codex's loader type-validates the field and rejects a string.
_SIDECAR_CONTENT = b"policy:\n  allow_implicit_invocation: false\n"


def _entry_text(plan: StagingPlan, item: StagedItem) -> str | None:
    """The skill's entry-file text as it will deploy: an override wins over the
    source tree, because overrides are the bytes that reach disk."""
    override = plan.dir_overrides.get(item.dest_relpath, {}).get(Path(DIR_RECORD_FILE))
    if override is not None:
        return override.content.decode("utf-8", errors="replace")
    return entry_file_text(item)


class CodexAdapter:
    """Adapter for OpenAI's Codex CLI. Detected when ~/.codex/ exists."""

    name: str = "codex"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".codex"

    def dest_dir(self, home: Path) -> Path:
        return home / ".codex"

    def is_detected(self, home: Path) -> bool:
        return (home / ".codex").is_dir()

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def project_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; CodexAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; CodexAdapter accepts uniformly
    ) -> bool:
        return True

    def post_staging_transforms(self, plan: StagingPlan, io: IOPort) -> StagingPlan:
        """Emit Codex's skill-policy sidecar for every user-invoked skill.

        A skill declaring ``disable-model-invocation: true`` has that key
        projected out of its Codex ``SKILL.md`` (Codex's loader does not define
        it); the declaration deploys instead as a generated
        ``agents/openai.yaml`` beside the entry file, which is how Codex keeps
        a skill out of implicit invocation. The file rides ``dir_overrides``,
        the channel for bytes inside an opaque DIR item, so the sync writes it,
        the idempotency check expects it, and the receipt's directory digest
        covers it for prune. A skill whose source tree ships its own sidecar,
        or whose overrides already carry one, keeps the authored bytes.
        """
        logged = False
        for dest, item in plan.items.items():
            if item.kind is not FileKind.DIR or item.namespace != "skills":
                continue
            if SIDECAR_RELPATH in plan.dir_overrides.get(dest, {}):
                continue
            if (item.source_path / SIDECAR_RELPATH).is_file():
                continue
            text = _entry_text(plan, item)
            if text is None or not is_user_invoked(text):
                continue
            if not logged:
                io.info("Emitting Codex skill-policy sidecars", verbose=True)
                logged = True
            plan.dir_overrides.setdefault(dest, {})[SIDECAR_RELPATH] = Contribution(
                source_path=item.source_path / DIR_RECORD_FILE, content=_SIDECAR_CONTENT
            )
        return plan
