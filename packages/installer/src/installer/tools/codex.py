from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

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


def _authored_sidecar(plan: StagingPlan, item: StagedItem) -> bytes | None:
    """Sidecar bytes the skill already supplies, override winning over the
    source tree; ``None`` when nothing but the generated file would exist."""
    override = plan.dir_overrides.get(item.dest_relpath, {}).get(SIDECAR_RELPATH)
    if override is not None:
        return override.content
    authored = item.source_path / SIDECAR_RELPATH
    return authored.read_bytes() if authored.is_file() else None


def _disables_implicit_invocation(content: bytes) -> bool:
    """True when ``content`` already declares the policy a user-invoked skill
    requires — ``allow_implicit_invocation`` exactly ``False``, matching the
    strict reading the boolean gets everywhere else."""
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        return False
    if not isinstance(parsed, dict):
        return False
    policy = parsed.get("policy")
    return isinstance(policy, dict) and policy.get("allow_implicit_invocation") is False


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
        covers it for prune. A user-invoked skill that supplies its own sidecar
        keeps the authored bytes only when they already declare the policy; an
        authored sidecar that does not is a contradiction in source — the front
        matter says never fire unprompted, the sidecar would deploy Codex the
        opposite — and it aborts the staging rather than letting either file
        silently win.
        """
        logged = False
        for dest, item in plan.items.items():
            if item.kind is not FileKind.DIR or item.namespace != "skills":
                continue
            text = _entry_text(plan, item)
            if text is None or not is_user_invoked(text):
                continue
            authored = _authored_sidecar(plan, item)
            if authored is not None:
                if not _disables_implicit_invocation(authored):
                    raise ValueError(  # noqa: TRY003  # single call-site; subclass not justified
                        f"{dest}: skill declares disable-model-invocation but ships "
                        f"its own {SIDECAR_RELPATH} without "
                        "allow_implicit_invocation: false — resolve the "
                        "contradiction in source"
                    )
                continue
            if not logged:
                io.info("Emitting Codex skill-policy sidecars", verbose=True)
                logged = True
            plan.dir_overrides.setdefault(dest, {})[SIDECAR_RELPATH] = Contribution(
                source_path=item.source_path / DIR_RECORD_FILE, content=_SIDECAR_CONTENT
            )
        return plan
