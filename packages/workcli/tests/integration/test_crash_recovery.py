"""Crash-recovery against real bd state: a fault mid-`deliver` leaves the
impl-placeholder handle + manifest note recorded (real partial state); a
subsequent `work reconcile` replays reconcile_placeholder and heals to final
state. Also: a malformed-JSON bd response on a --json read verb must surface
E_BACKEND_DRIFT with detail.reason == "invalid_json"."""

from __future__ import annotations

from collections.abc import Sequence

from tests.integration.conftest import ITEST_TRACK, _bd_env, driver_for
from tests.integration.fault_runner import Fault, FaultInjectingBdRunner
from workcli.adapters.bd.runner import SubprocessBdRunner

# These tests wrap the real runner in a fault-injecting one, so they build their
# drivers by hand rather than taking the `driver` fixture. `driver_for` is the
# same factory the fixture uses, which is what keeps their `work` calls bound to
# the install's own project-config.toml instead of the ambient repository's.


def test_malformed_json_on_read_is_invalid_json_drift(fresh_install, bd_binary):
    real = SubprocessBdRunner(
        bd_binary=bd_binary, cwd=str(fresh_install), env=_bd_env(fresh_install)
    )
    drive = driver_for(real, fresh_install)
    created = drive(["create", "--raw", "--title", "cr-item", "--type", "task", "--priority", "2"])
    item_id = created["data"]["id"]

    # Fault the `show --json` read with garbage stdout, exit 0.
    faulted = FaultInjectingBdRunner(
        real,
        fail_when=lambda _n, argv: "show" in argv and "--json" in argv,
        fault=Fault.MALFORMED_JSON,
    )
    env = driver_for(faulted, fresh_install)(["show", item_id])
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
    drive = driver_for(real, fresh_install)

    # --- Arrange: promote a shape-feat leaf → a shape-spec container. That mints
    # a design child (shape-design) + an impl-placeholder sibling under it
    # (transitions.py::promote → finalize_spec_instantiation). `create` requires
    # exactly one of --parent/--orphan; this leaf is standalone → --orphan, which
    # leaves no parent to inherit a track from, so it names one itself.
    leaf = drive(
        [
            "create",
            "feat",
            "--title",
            "cr-spec",
            "--priority",
            "2",
            "--orphan",
            "--track",
            ITEST_TRACK,
        ]
    )["data"]["id"]
    drive(["promote", leaf])
    design_child, placeholder = _design_and_placeholder(drive, leaf)

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
    crashed = driver_for(faulted, fresh_install)(
        ["deliver", design_child, "--spec", str(spec_file)]
    )
    assert crashed["ok"] is False  # the injected fault aborted deliver

    # Partial state is real: the placeholder still carries the impl-placeholder
    # handle (the recovery signal), has NOT yet gained its shape label, and the
    # in-band manifest snapshot the appends recorded before the fault is present
    # — that snapshot is what `reconcile` replays off, so its persistence proves
    # the fault landed after the appends and before the shape mutation.
    mid = drive(["show", placeholder])["data"]["items"][0]
    assert "impl-placeholder" in mid["labels"]
    assert "shape-feat" not in mid["labels"]
    assert "[work] manifest:" in mid["notes"]

    # --- Heal: reconcile replays reconcile_placeholder off the recorded snapshot.
    swept = drive(["reconcile"])
    assert swept["ok"] is True

    # Assert the full correct heal: the impl-placeholder recovery handle is
    # cleared (delivery no longer partial), the design child is closed
    # (delivery complete), spec-ready is stamped, and the placeholder keeps
    # its manifest-noun shape — the instantiation sweep must never re-finalize
    # it into a planned shape-spec container (wgclw.9.8).
    healed = drive(["show", placeholder])["data"]["items"][0]
    assert "impl-placeholder" not in healed["labels"]  # handle removed strictly last
    assert "spec-ready" in healed["labels"]
    assert "shape-feat" in healed["labels"]  # manifest-noun shape survives the sweep
    assert "creating-spec" not in healed["labels"]
    assert "planned" not in healed["labels"]
    assert drive(["show", design_child])["data"]["items"][0]["status"] == "closed"


def _design_and_placeholder(drive, container_id: str) -> tuple[str, str]:
    """Return (design_child_id, placeholder_id): the container's two children."""
    children = drive(["show", container_id])["data"]["items"][0][
        "children"
    ]  # show → {"items": [...]}
    design_child = placeholder = None
    for child_id in children:
        labels = drive(["show", child_id])["data"]["items"][0]["labels"]
        if "shape-design" in labels:
            design_child = child_id
        else:
            placeholder = child_id
    assert design_child and placeholder, f"expected design+placeholder under {container_id}"
    return design_child, placeholder
