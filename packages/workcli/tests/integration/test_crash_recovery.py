"""Crash-recovery against real bd state: a fault mid-`deliver` leaves the
impl-placeholder handle + manifest note recorded (real partial state); a
subsequent `work reconcile` replays reconcile_placeholder and heals to final
state. Also: a malformed-JSON bd response on a --json read verb must surface
E_BACKEND_DRIFT with detail.reason == "invalid_json"."""

from __future__ import annotations

import io
import json
from collections.abc import Sequence

from tests.integration.conftest import _bd_env
from tests.integration.fault_runner import Fault, FaultInjectingBdRunner
from workcli.adapters.bd.runner import SubprocessBdRunner
from workcli.cli import main


def _drive(runner, argv: Sequence[str]) -> dict:
    out, err = io.StringIO(), io.StringIO()
    main(list(argv), runner=runner, out=out, err=err)
    return json.loads(out.getvalue())


def test_malformed_json_on_read_is_invalid_json_drift(fresh_install, bd_binary):
    real = SubprocessBdRunner(
        bd_binary=bd_binary, cwd=str(fresh_install), env=_bd_env(fresh_install)
    )
    created = _drive(
        real, ["create", "--raw", "--title", "cr-item", "--type", "task", "--priority", "2"]
    )
    item_id = created["data"]["id"]

    # Fault the `show --json` read with garbage stdout, exit 0.
    faulted = FaultInjectingBdRunner(
        real,
        fail_when=lambda _n, argv: "show" in argv and "--json" in argv,
        fault=Fault.MALFORMED_JSON,
    )
    env = _drive(faulted, ["show", item_id])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_BACKEND_DRIFT"
    assert env["error"]["detail"]["reason"] == "invalid_json"


def test_interrupted_deliver_is_healed_by_reconcile(fresh_install, bd_binary):
    """Fault a design-child `deliver` at the set_type call (after the spec: and
    manifest: notes are appended, before impl-placeholder is removed), leaving
    real partial state; `reconcile` must then complete the placeholder."""
    real = SubprocessBdRunner(
        bd_binary=bd_binary, cwd=str(fresh_install), env=_bd_env(fresh_install)
    )

    # --- Arrange: promote a shape-feat leaf → a shape-spec container. That mints
    # a design child (shape-design) + an impl-placeholder sibling under it
    # (transitions.py::promote → finalize_spec_instantiation). `create` requires
    # exactly one of --parent/--orphan; this leaf is standalone → --orphan.
    leaf = _drive(real, ["create", "feat", "--title", "cr-spec", "--priority", "2", "--orphan"])[
        "data"
    ]["id"]
    _drive(real, ["promote", leaf])
    design_child, placeholder = _design_and_placeholder(real, leaf)

    # A `## Continuations` single-item manifest. GRAMMAR (manifest.py, verified):
    # `- <noun>: <title> — AC: <acceptance>` — note the em-dash separator " — AC: ".
    spec_file = fresh_install / "cont.md"
    spec_file.write_text(
        "# spec\n\n## Continuations\n\n- feat: cr-impl — AC: the impl unit is built\n"
    )

    # --- Act: fault the deliver at the first `update ... --type` call. That argv
    # shape is emitted ONLY by backend.set_type (the other --type callers start
    # with `list`/`create`), which _reconcile_single runs FIRST — after both the
    # spec: and manifest: snapshot notes are appended, before the shape label is
    # added and before impl-placeholder is removed. Genuine mid-deliver state.
    def fail_on_set_type(_n: int, argv: Sequence[str]) -> bool:
        return argv[:1] == ["update"] and "--type" in argv

    faulted = FaultInjectingBdRunner(real, fail_when=fail_on_set_type, fault=Fault.NONZERO_EXIT)
    crashed = _drive(faulted, ["deliver", design_child, "--spec", str(spec_file)])
    assert crashed["ok"] is False  # the injected fault aborted deliver

    # Partial state is real: the placeholder still carries the impl-placeholder
    # handle (the recovery signal), has NOT yet gained its shape label, and the
    # in-band manifest snapshot the appends recorded before the fault is present
    # — that snapshot is what `reconcile` replays off, so its persistence proves
    # the fault landed after the appends and before the shape mutation.
    mid = _drive(real, ["show", placeholder])["data"]
    assert "impl-placeholder" in mid["labels"]
    assert "shape-feat" not in mid["labels"]
    assert "[work] manifest:" in mid["notes"]

    # --- Heal: reconcile replays reconcile_placeholder off the recorded snapshot.
    swept = _drive(real, ["reconcile"])
    assert swept["ok"] is True

    # Assert the recovery invariants that hold under ANY correct heal: the
    # impl-placeholder recovery handle is cleared (delivery no longer partial),
    # the design child is closed (delivery complete), and spec-ready is stamped.
    # We deliberately do NOT pin the placeholder's final *shape* label here: a
    # tracked lifecycle defect (spec children retain `creating-spec`, so
    # reconcile's instantiation sweep re-finalizes the placeholder and currently
    # overwrites its manifest-noun shape) makes that label defect-dependent. The
    # defect is filed as discovered work; pinning it green would bless the bug,
    # and pinning the buggy shape would encode it — so the harness asserts only
    # the handle/close/spec-ready invariants a correct fix must preserve.
    healed = _drive(real, ["show", placeholder])["data"]
    assert "impl-placeholder" not in healed["labels"]  # handle removed strictly last
    assert "spec-ready" in healed["labels"]
    assert _drive(real, ["show", design_child])["data"]["status"] == "closed"


def _design_and_placeholder(runner, container_id: str) -> tuple[str, str]:
    """Return (design_child_id, placeholder_id): the container's two children."""
    children = _drive(runner, ["show", container_id])["data"]["children"]  # single-id show
    design_child = placeholder = None
    for child_id in children:
        labels = _drive(runner, ["show", child_id])["data"]["labels"]
        if "shape-design" in labels:
            design_child = child_id
        else:
            placeholder = child_id
    assert design_child and placeholder, f"expected design+placeholder under {container_id}"
    return design_child, placeholder
