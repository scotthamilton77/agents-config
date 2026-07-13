"""Churn extractor — per-file added/deleted sums restricted to the net set.

Symmetric with `extract/estate.py`: takes the `GitRunner` seam, calls
`churn_for_commits` (the PyDriller walk), and reduces the raw per-commit
modified-file rows to one `FileChurn` per path — but only for files in the PR's
*net* set, so a file added-then-reverted within the PR (present in the churn
union, absent from the net diff) contributes no heat. Driven through
`ScriptedGitRunner`; no real git/PyDriller here.
"""

from __future__ import annotations

from tests.fakes import ScriptedGitRunner
from vizsuite.adapters.git.runner import ModifiedFileRow


def test_churn_sums_per_file_and_restricts_to_net():
    from vizsuite.extract.churn import FileChurn, churn

    git = ScriptedGitRunner(
        churn_rows=[
            ModifiedFileRow(new_path="a.py", old_path="a.py", added=5, deleted=1),
            ModifiedFileRow(new_path="a.py", old_path="a.py", added=3, deleted=0),
            ModifiedFileRow(new_path="b.py", old_path=None, added=10, deleted=0),
            ModifiedFileRow(new_path="c.py", old_path="c.py", added=9, deleted=9),
        ]
    )

    result = churn(git, ["oid1", "oid2"], net_files={"a.py", "b.py"})

    # a.py summed across both commits; b.py once; c.py excluded (not in net set).
    assert result == {
        "a.py": FileChurn(added=8, deleted=1),
        "b.py": FileChurn(added=10, deleted=0),
    }
    assert ("churn_for_commits", "oid1", "oid2") in git.calls


def test_deleted_file_keys_by_old_path():
    from vizsuite.extract.churn import FileChurn, churn

    git = ScriptedGitRunner(
        churn_rows=[
            ModifiedFileRow(new_path=None, old_path="gone.py", added=0, deleted=7),
        ]
    )

    result = churn(git, ["oid1"], net_files={"gone.py"})

    # a pure delete has new_path=None; it keys by old_path so it stays in scope.
    assert result == {"gone.py": FileChurn(added=0, deleted=7)}
