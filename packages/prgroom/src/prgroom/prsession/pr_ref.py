"""PRRef — the per-PR identity used as the state store's key — and the commit-id shape.

Both identify a thing this CLI addresses by name rather than by content, and both
are validated before anything is spent on them: a ref that cannot resolve to a PR
and a SHA that cannot be a commit are refused at their entry point, not at the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The two fully-qualified PR-ref forms the CLI accepts. ``owner``/``repo`` allow
# the GitHub-legal character set; ``number`` is a positive integer (``#0`` and a
# bare ``#`` are rejected so a malformed ref never resolves to PR 0).
_SLUG = r"[A-Za-z0-9._-]+"
_OWNER_REPO_HASH = re.compile(rf"^(?P<owner>{_SLUG})/(?P<repo>{_SLUG})#(?P<number>[1-9]\d*)$")
# After the PR number, real GitHub URLs commonly carry a trailing ``/path``
# (``/files``), a ``#fragment`` (``#discussion_r123``), and/or a ``?query``
# (``?tab=files``) — any combination. The number is the captured group; anything
# after it is ignored, so the tail accepts ``/``, ``#``, or ``?`` then the rest.
_URL = re.compile(
    rf"^https?://github\.com/(?P<owner>{_SLUG})/(?P<repo>{_SLUG})/pull/(?P<number>[1-9]\d*)(?:[/#?].*)?$"
)
_BARE_NUMBER = re.compile(r"^(?P<number>[1-9]\d*)$")

# A full git object id. Abbreviations are refused everywhere a commit is named:
# a review is pinned by comparing against what GitHub reports, which is always
# the full id, and a prefix would compare unequal to the head it does identify.
_COMMIT_SHA = re.compile(r"[0-9a-fA-F]{40}")


def is_commit_sha(value: str) -> bool:
    """True iff ``value`` is a 40-character hex commit id, in either case.

    Matched whole rather than anchored: ``$`` also matches before a trailing
    newline, and an id read out of a file arrives carrying one.
    """
    return _COMMIT_SHA.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class PRRef:
    """Identifies one PR. Frozen + slots so it is hashable and usable as a dict key."""

    owner: str
    repo: str
    number: int

    @classmethod
    def parse(cls, text: str, *, default_repo: tuple[str, str] | None = None) -> PRRef:
        """Parse a CLI PR-ref string into a :class:`PRRef`.

        Accepts ``owner/repo#<n>``, a full ``https://github.com/owner/repo/pull/<n>``
        URL (with an optional trailing path), or a bare ``<n>`` when ``default_repo``
        supplies the ``(owner, repo)`` to resolve it against. A malformed ref — or a
        bare number with no ``default_repo`` — raises
        :class:`~prgroom.errors.PreconditionError` tagged ``PRECONDITION_BAD_PR_REF``
        (exit 2, rendered 4-line block). Imported lazily because ``errors`` already
        imports this module (``lock_held_error``); a top-level import would cycle.
        """
        from prgroom.errors import ErrorCode, PreconditionError

        for pattern in (_OWNER_REPO_HASH, _URL):
            m = pattern.match(text)
            if m is not None:
                return cls(owner=m["owner"], repo=m["repo"], number=int(m["number"]))
        bare = _BARE_NUMBER.match(text)
        if bare is not None and default_repo is not None:
            owner, repo = default_repo
            return cls(owner=owner, repo=repo, number=int(bare["number"]))
        raise PreconditionError(ErrorCode.PRECONDITION_BAD_PR_REF, detail=text)

    def slug(self) -> str:
        """Filesystem-/label-safe stem: ``<owner>-<repo>-<n>``, used by the file store."""
        return f"{self.owner}-{self.repo}-{self.number}"

    def display(self) -> str:
        """Human-facing GitHub shorthand: ``<owner>/<repo>#<n>``."""
        return f"{self.owner}/{self.repo}#{self.number}"

    def to_dict(self) -> dict[str, Any]:
        """The ``{owner, repo, number}`` JSON shape used in state + contract payloads."""
        return {"owner": self.owner, "repo": self.repo, "number": self.number}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PRRef:
        return cls(owner=d["owner"], repo=d["repo"], number=d["number"])
