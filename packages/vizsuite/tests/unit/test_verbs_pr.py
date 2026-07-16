"""`viz pr <n>` end-to-end (plan slices 2-3): reconcile → head-OID estate →
materialized snapshot → scc complexity → HTML.

Slice 2 replaced slice 1's ``HEAD`` estate with the reconciled PR head OID. Slice
3 adds the per-file heat plumbing: the verb materializes the head snapshot from
`git archive`, scc scans *that tempdir* (never the live checkout), the complexity
axis is scored, and the tempdir is torn down in a `finally`. The first two tests
fake every adapter; the last runs the real `SubprocessGitRunner` over a throwaway
repo with only `gh` and `scc` (external binaries) faked, proving the git wiring
end-to-end.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import run_cli
from tests.fakes import (
    ScriptedGhRunner,
    ScriptedGitRunner,
    ScriptedSccRunner,
    blob,
    gh_pr_result,
    scc_result,
    tar_of,
)
from vizsuite.adapters.git.runner import ModifiedFileRow
from vizsuite.envelope import ErrorCode, VizError

_SCENE_SCRIPT_RE = re.compile(
    r'<script id="viz-scene" type="application/json">(.*?)</script>', re.DOTALL
)


def _extract_scene(html: str) -> dict[str, Any]:
    """Pull the inlined scene JSON back out of a rendered artifact.

    The embedding boundary escapes `<`/`>`/`&` to `\\uXXXX` (spec §4.6); those
    are valid JSON string escapes, so `json.loads` reads the extracted text
    back losslessly.
    """
    match = _SCENE_SCRIPT_RE.search(html)
    assert match is not None
    scene: dict[str, Any] = json.loads(match.group(1))
    return scene


def _write_graph(
    tmp_path: Path,
    *,
    built_at_commit: str,
    nodes: list[dict[str, str]],
    links: list[dict[str, str]],
) -> None:
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    payload = {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "built_at_commit": built_at_commit,
        "nodes": nodes,
        "links": links,
    }
    (graph_dir / "graph.json").write_text(json.dumps(payload), encoding="utf-8")


def test_pr_reconciles_and_emits_html_from_head_estate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = ScriptedGitRunner(
        present_oids={"base000", "head111"},
        diff_files=["src/app.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=3, deleted=0)
        ],
        ls_tree_rows=[blob("src/app.py", "aaa111"), blob("README.md", "bbb222")],
        archive_tar_bytes=tar_of(
            {"src/app.py": "x = 1\n", "README.md": "# hi\n", ".critical-paths": "src/**\n"}
        ),
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5, "README.md": 2}))

    exit_code, envelope, stderr = run_cli(["pr", "7"], git_runner=git, gh_runner=gh, scc_runner=scc)

    assert exit_code == 0
    assert stderr == ""
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["pr"] == 7
    assert data["nodes"] == 2  # the estate (whole tree at head), not just the net set
    assert data["scored_files"] == 2  # complexity scored both estate files scc recognized
    assert data["consequential_files"] == 1  # src/app.py matched the .critical-paths marker
    # slice 5: PR metadata garnish (author/review-state) is wired into the envelope.
    assert data["author"] == "octocat"
    assert data["review_state"] == "APPROVED"

    # The estate is resolved at the reconciled head OID — never the checkout's HEAD.
    assert ("ls_tree", "head111") in git.calls
    assert ("ls_tree", "HEAD") not in git.calls

    artifact = Path(str(data["artifact"]))
    assert artifact == tmp_path / ".viz" / "out" / "pr-7.html"
    html = artifact.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "src/app.py" in html


def test_pr_materializes_snapshot_scans_scc_then_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Slice-3 plumbing: the verb materializes the head snapshot from `git archive`,
    # scc scans *that tempdir* (never the live checkout), and the tempdir is torn
    # down afterwards — a leaked snapshot dir is the failure this asserts against.
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = ScriptedGitRunner(
        present_oids={"base000", "head111"},
        diff_files=["src/app.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=8, deleted=0)
        ],
        ls_tree_rows=[blob("src/app.py", "aaa111")],
        archive_tar_bytes=tar_of({"src/app.py": "x = 1\n"}),
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 6}))

    exit_code, _envelope, _stderr = run_cli(
        ["pr", "9"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    assert ("archive_tar", "head111") in git.calls  # snapshot at the resolved head OID
    assert len(scc.calls) == 1  # scc scanned exactly one dir
    scanned_dir = Path(scc.calls[0][1])
    assert not scanned_dir.exists()  # the snapshot tempdir was rmtree'd in the finally


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def _rev_parse(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_pr_reconciles_against_real_git_with_fake_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Real SubprocessGitRunner over a two-commit repo — real archive+materialize —
    # with only gh and scc (external binaries) faked, using the real base/head OIDs
    # the reconciler must agree with.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = _rev_parse(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "head")
    head = _rev_parse(tmp_path)
    monkeypatch.chdir(tmp_path)

    gh = ScriptedGhRunner(
        gh_pr_result(base_oid=base, head_oid=head, changed_files=2, commit_count=1)
    )
    scc = ScriptedSccRunner(scc_result({"a.py": 3, "b.py": 1}))

    exit_code, envelope, stderr = run_cli(["pr", "5"], gh_runner=gh, scc_runner=scc)

    assert exit_code == 0
    assert stderr == ""
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    html = artifact.read_text(encoding="utf-8")
    assert "a.py" in html
    assert "b.py" in html


def test_pr_threads_heat_axes_repo_nwo_and_in_pr_into_the_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # .2.2: centrality is wired via the live-tree graphify-out/graph.json,
    # fused with complexity/consequence into per-file heat, and the repo slug
    # threads through from the widened gh graphql response.
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(
            base_oid="base000",
            head_oid="head111",
            changed_files=1,
            commit_count=1,
            repo_nwo="octocat/demo",
        )
    )
    git = ScriptedGitRunner(
        present_oids={"base000", "head111"},
        diff_files=["src/app.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=3, deleted=0)
        ],
        ls_tree_rows=[blob("src/app.py", "aaa111"), blob("lib/util.py", "bbb222")],
        archive_tar_bytes=tar_of({"src/app.py": "x = 1\n", "lib/util.py": "y = 1\n"}),
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5, "lib/util.py": 2}))
    _write_graph(
        tmp_path,
        built_at_commit="head111",
        nodes=[
            {"id": "s1", "source_file": "lib/util.py"},
            {"id": "s2", "source_file": "src/app.py"},
        ],
        links=[{"source": "s1", "target": "s2", "relation": "calls", "confidence": "EXTRACTED"}],
    )

    exit_code, envelope, _stderr = run_cli(
        ["pr", "11"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    assert scene["repo_nwo"] == "octocat/demo"
    assert scene["render_config"]["unavailable_axes"] == []  # graph present + fresh
    # envelope mirror of the available heat axes (all present when nothing is unavailable)
    assert data["heat_axes_available"] == ["complexity", "consequence", "load_bearing"]
    names = {descriptor["name"] for descriptor in scene["descriptors"]}
    assert names == {"complexity", "load_bearing", "consequence", "heat"}

    by_path = {node["path"]: node["attributes"] for node in scene["files"]}
    assert set(by_path["src/app.py"]) == {
        "complexity",
        "load_bearing",
        "consequence",
        "heat",
        "in_pr",
    }
    assert by_path["src/app.py"]["in_pr"] is True  # net-set file
    assert by_path["lib/util.py"]["in_pr"] is False  # context-only file
    assert by_path["src/app.py"]["load_bearing"] == 1.0  # sole EXTRACTED in-edge
    # .2.2 slice 4: the same EXTRACTED, intra-file-excluded edge backing
    # load_bearing threads onto the scene as a top-level dependency edge.
    assert scene["edges"] == [
        {"source": "lib/util.py", "target": "src/app.py", "kind": "dependency"}
    ]


def test_pr_fails_soft_to_unavailable_load_bearing_when_graphify_out_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)  # no graphify-out/ written — the optional-dep absent case
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = ScriptedGitRunner(
        present_oids={"base000", "head111"},
        diff_files=["src/app.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=3, deleted=0)
        ],
        ls_tree_rows=[blob("src/app.py", "aaa111")],
        archive_tar_bytes=tar_of({"src/app.py": "x = 1\n"}),
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5}))

    exit_code, envelope, _stderr = run_cli(
        ["pr", "12"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    assert scene["render_config"]["unavailable_axes"] == ["load_bearing"]
    # envelope mirror: load_bearing drops out of the available axes when graphify-out/ is absent
    assert data["heat_axes_available"] == ["complexity", "consequence"]
    by_path = {node["path"]: node["attributes"] for node in scene["files"]}
    # a real zero, never a stale/omitted value (spec §6.2).
    assert by_path["src/app.py"]["load_bearing"] == 0.0
    # fail-soft: an unavailable centrality axis threads an empty edge set too.
    assert scene["edges"] == []


def _pr_git(**overrides: Any) -> ScriptedGitRunner:
    """A `ScriptedGitRunner` for the fidelity-F1 (`--allow-stale-graph`) tests.

    All of these tests share the same one-file PR shape; only the
    `rev_list_oids`/`rev_list_errors` seam varies per test (the commits-behind
    lookup), so this centralizes the boilerplate the F1 slice added.
    """
    defaults: dict[str, Any] = {
        "present_oids": {"base000", "head111"},
        "diff_files": ["src/app.py"],
        "rev_list_oids": ["c1"],
        "churn_rows": [
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=3, deleted=0)
        ],
        "ls_tree_rows": [blob("src/app.py", "aaa111")],
        "archive_tar_bytes": tar_of({"src/app.py": "x = 1\n"}),
    }
    defaults.update(overrides)
    return ScriptedGitRunner(**defaults)


def test_pr_flag_off_with_mismatched_graph_commit_is_still_unavailable_regression_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # F1 regression pin: with `--allow-stale-graph` omitted, a graph whose
    # build commit disagrees with the PR head must produce the exact same
    # envelope as today (byte-identical to
    # test_pr_fails_soft_to_unavailable_load_bearing_when_graphify_out_is_absent's
    # assertions) — the opt-in changes nothing about the default path.
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = _pr_git()
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5}))
    _write_graph(
        tmp_path,
        built_at_commit="stale000",
        nodes=[{"id": "s1", "source_file": "src/app.py"}],
        links=[],
    )

    exit_code, envelope, _stderr = run_cli(
        ["pr", "13"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    assert scene["render_config"]["unavailable_axes"] == ["load_bearing"]
    assert "stale_graph" not in scene["render_config"]
    assert data["heat_axes_available"] == ["complexity", "consequence"]
    assert scene["edges"] == []


def test_pr_allow_stale_graph_flag_accepts_mismatched_commit_and_labels_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=4)
    )
    git = _pr_git(rev_list_oids=["c1", "c2", "c3", "c4"])
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5}))
    _write_graph(
        tmp_path,
        built_at_commit="stale000",
        nodes=[{"id": "s1", "source_file": "src/app.py"}],
        links=[],
    )

    exit_code, envelope, _stderr = run_cli(
        ["pr", "14", "--allow-stale-graph"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    # load_bearing is available (accepted-stale scores exactly like fresh), so
    # it drops out of unavailable_axes and back into the available-axes mirror.
    assert scene["render_config"]["unavailable_axes"] == []
    assert data["heat_axes_available"] == ["complexity", "consequence", "load_bearing"]
    assert scene["render_config"]["stale_graph"] == {
        "built_at_commit": "stale000",
        "commits_behind": 4,
    }
    # the commits-behind lookup went through the same git-runner seam
    # (`rev_list`), never a bespoke subprocess call.
    assert ("rev_list", "stale000", "head111") in git.calls


def test_pr_allow_stale_graph_flag_with_fresh_graph_has_no_stale_graph_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The opt-in is inert when the graph is already fresh — no stale_graph key,
    # no extra rev_list call for a commits-behind count nobody needs.
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = _pr_git()
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5}))
    _write_graph(
        tmp_path,
        built_at_commit="head111",
        nodes=[{"id": "s1", "source_file": "src/app.py"}],
        links=[],
    )

    exit_code, envelope, _stderr = run_cli(
        ["pr", "15", "--allow-stale-graph"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    assert scene["render_config"]["unavailable_axes"] == []
    assert "stale_graph" not in scene["render_config"]
    assert ("rev_list", "head111", "head111") not in git.calls


def test_pr_allow_stale_graph_flag_with_absent_graph_stays_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)  # no graphify-out/ written — the optional-dep absent case
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = _pr_git()
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5}))

    exit_code, envelope, _stderr = run_cli(
        ["pr", "16", "--allow-stale-graph"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    assert scene["render_config"]["unavailable_axes"] == ["load_bearing"]
    assert "stale_graph" not in scene["render_config"]


def test_pr_stale_graph_commits_behind_fails_soft_to_none_when_rev_list_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The build-commit is unknown locally (e.g. a merged/rebased-away commit),
    # so `git rev-list <built>..<head>` fails — the count fails soft to
    # `None`, and the build still succeeds with a labeled-but-uncounted badge.
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = _pr_git(
        rev_list_errors={
            ("stale000", "head111"): VizError(ErrorCode.ADAPTER_FAILURE, "unknown revision")
        }
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5}))
    _write_graph(
        tmp_path,
        built_at_commit="stale000",
        nodes=[{"id": "s1", "source_file": "src/app.py"}],
        links=[],
    )

    exit_code, envelope, _stderr = run_cli(
        ["pr", "17", "--allow-stale-graph"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    scene = _extract_scene(artifact.read_text(encoding="utf-8"))

    assert scene["render_config"]["stale_graph"] == {
        "built_at_commit": "stale000",
        "commits_behind": None,
    }
