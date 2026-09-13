"""Turn detector findings over several runs into one table of hit rates and evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .detect import DETECTORS, Finding, detect_all
from .events import Run

# A note is one line under the table, so a run with dozens of pieces of evidence is cut
# short. The full evidence stays on the Row for anything reading the rows directly.
NOTE_WIDTH = 240


@dataclass(frozen=True)
class Row:
    """One behaviour's rate across the runs that were read, with a sample of the evidence."""

    behaviour: str
    hits: int
    runs: int
    versions: list[str]
    note: str


def _versions(runs: list[Run]) -> list[str]:
    seen: list[str] = []
    for run in runs:
        if run.version not in seen:
            seen.append(run.version)
    return seen


def aggregate(runs: list[Run]) -> list[Row]:
    """Score every behaviour across every run.

    The note quotes the first run that hit, because that is the evidence a reader wants to
    check. When nothing hit, it quotes the first run anyway, so a miss can be told apart
    from a detector that found nothing to look at.
    """
    if not runs:
        return []
    findings: list[list[Finding]] = [detect_all(run) for run in runs]
    versions = _versions(runs)
    rows: list[Row] = []
    for position in range(len(DETECTORS)):
        per_run = [(runs[i], findings[i][position]) for i in range(len(runs))]
        hits = [(run, finding) for run, finding in per_run if finding.hit]
        sample = hits[0] if hits else per_run[0]
        rows.append(
            Row(
                behaviour=sample[1].behaviour,
                hits=len(hits),
                runs=len(runs),
                versions=versions,
                note=f"{sample[0].name}: {sample[1].evidence}",
            )
        )
    return rows


def render(rows: list[Row]) -> str:
    """Render the table and its notes as plain text."""
    if not rows:
        return "no runs read"
    width = max(len(row.behaviour) for row in rows)
    lines = [f"{'behaviour'.ljust(width)}  hits/runs  versions", f"{'-' * width}  ---------  --------"]
    for row in rows:
        rate = f"{row.hits}/{row.runs}"
        lines.append(f"{row.behaviour.ljust(width)}  {rate.ljust(9)}  {', '.join(row.versions)}")
    lines.append("")
    lines += [f"{row.behaviour}: {_one_line(row.note)}" for row in rows]
    return "\n".join(lines)


def _one_line(note: str) -> str:
    if len(note) <= NOTE_WIDTH:
        return note
    return f"{note[:NOTE_WIDTH]}… (+{len(note) - NOTE_WIDTH} more characters of evidence)"
