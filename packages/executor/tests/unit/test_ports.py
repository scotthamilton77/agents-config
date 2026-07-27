"""The real, subprocess-backed ports — driven through a scripted runner, so
neither `grind` nor `work` has to exist for these to run."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from unittest import mock

import pytest

from executor.envelope import ErrorCode, ExecutorError
from executor.ports import (
    EVENT_WAS_WRITTEN,
    CommandResult,
    GrindRuntime,
    RuntimePort,
    SubprocessRunner,
    TrackerPort,
    WorkTracker,
)
from tests.unit.fakes import FakeRuntime, FakeTracker, ScriptedRunner, run_state

_STATUS = ("grind", "status", "--full")
_CHECK = ("grind", "check")
_LOG = ("grind", "log")


def _ok(payload: object, exit_code: int = 0) -> CommandResult:
    return CommandResult(exit_code, json.dumps(payload), "")


def _state_reply() -> CommandResult:
    return _ok({"ok": True, "state": {"items": {"it-1": {"status": "queued", "lane": "lane-a"}}}})


def test_state_reads_the_full_fold_and_passes_the_directory_through() -> None:
    """
    Given a runtime port built with an explicit grind directory
    When the fold is read
    Then `grind status --full --dir DIR` runs and its `state` object is parsed.
    """
    runner = ScriptedRunner({_STATUS: _state_reply()})

    state = GrindRuntime(runner, grind_dir="/runs/grind-a").state()

    assert runner.calls == [("grind", "status", "--full", "--dir", "/runs/grind-a")]
    assert state.items["it-1"].lane == "lane-a"


def test_no_directory_leaves_resolution_to_the_runtime() -> None:
    """
    Given a runtime port built without a directory
    When the fold is read
    Then no `--dir` is passed.

    Pins that omitting the flag stays distinguishable from passing one: the
    runtime gives an absent `--dir` its own meaning.
    """
    runner = ScriptedRunner({_STATUS: _state_reply()})

    GrindRuntime(runner).state()

    assert runner.calls == [("grind", "status", "--full")]


def test_append_sends_the_event_type_and_a_json_payload() -> None:
    """
    Given an event to append
    When the runtime port appends it
    Then `grind log <type> --json <payload>` runs with the payload encoded.
    """
    runner = ScriptedRunner({_LOG: _ok({"ok": True, "applied": True})})

    GrindRuntime(runner).append("item_started", {"item": "it-1"})

    assert runner.calls == [("grind", "log", "item_started", "--json", '{"item": "it-1"}')]


def test_an_event_the_runtime_flags_instead_of_applying_is_a_typed_failure() -> None:
    """
    Given the runtime accepting an event it could not apply, reporting
    `ok: true` with `applied: false`
    When the port appends it
    Then a non-retryable failure carries the runtime's own anomaly reason.

    Reading only `ok` would let the executor claim it enacted a pairing the
    runtime recorded as a flag rather than a transition.
    """
    runner = ScriptedRunner(
        {
            _LOG: _ok(
                {
                    "ok": True,
                    "applied": False,
                    "anomaly": {"reason": "item_done illegal from status 'queued'"},
                }
            )
        }
    )

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).append("item_done", {"item": "it-1"})

    assert raised.value.retryable is False
    assert "item_done illegal from status 'queued'" in raised.value.message


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": True},
        {"ok": True, "applied": None},
        {"ok": True, "applied": "yes"},
        {"ok": True, "applied": 1},
    ],
    ids=["absent", "null", "string", "int"],
)
def test_an_append_reply_without_a_usable_applied_flag_is_an_envelope_fault(
    reply: object,
) -> None:
    """
    Given a runtime whose `log` reply carries no usable `applied` flag
    When the port appends
    Then E_RUNTIME_ENVELOPE is raised rather than success reported.

    Reading "not false" as applied would report a transition on no evidence
    at all — the exact failure the flag check exists to prevent, reached
    instead through an incompatible or corrupt runtime.
    """
    runner = ScriptedRunner({_LOG: _ok(reply)})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).append("item_started", {"item": "it-1"})

    assert raised.value.code is ErrorCode.RUNTIME_ENVELOPE


def test_a_binary_that_cannot_be_launched_is_a_failed_result() -> None:
    """
    Given a resolved binary that cannot be executed
    When the real runner runs it
    Then a failed CommandResult comes back naming the reason.

    A launch failure is a transport problem. Letting the OSError escape would
    have the CLI reduce it to a non-retryable internal error and hide the
    actionable reason.
    """

    def _denied(*_args: object, **_kwargs: object) -> object:
        raise PermissionError(13, "Permission denied")

    with mock.patch.object(subprocess, "run", _denied):
        result = SubprocessRunner().run(["grind", "status"])

    assert result.exit_code != 0
    assert "Permission denied" in result.stderr


def test_a_flagged_event_with_no_readable_anomaly_still_fails_typed() -> None:
    """
    Given a flagged event whose anomaly record says nothing usable
    When the port appends it
    Then it still fails, naming the event type.

    An unreadable anomaly is a worse reason to report success, not a better
    one.
    """
    runner = ScriptedRunner({_LOG: _ok({"ok": True, "applied": False, "anomaly": None})})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).append("item_done", {"item": "it-1"})

    assert "item_done" in raised.value.message


def test_a_stale_check_exits_one_on_an_ok_envelope_and_is_still_a_verdict() -> None:
    """
    Given a stale grind, which the runtime reports as exit 1 over an
    `ok: true` envelope
    When staleness is probed
    Then a verdict comes back rather than a subprocess failure.

    The documented quirk: the exit code carries the verdict, so reading it as
    a process failure would turn every stale run into a crash.
    """
    runner = ScriptedRunner(
        {
            _CHECK: _ok(
                {"ok": True, "stale": True, "age_s": 900, "last_event_ts": "2026-07-25T00:00:00Z"},
                exit_code=1,
            )
        }
    )

    verdict = GrindRuntime(runner).staleness("30m")

    assert (verdict.stale, verdict.age_s, verdict.last_event_ts) == (
        True,
        900.0,
        "2026-07-25T00:00:00Z",
    )
    assert runner.calls == [("grind", "check", "--max-age", "30m")]


@pytest.mark.parametrize(
    ("argv", "call"),
    [
        (_STATUS, lambda rt: rt.state()),
        (_LOG, lambda rt: rt.append("item_started", {"item": "it-1"})),
    ],
    ids=["status", "log"],
)
def test_a_nonzero_exit_is_a_failure_on_every_verb_but_the_staleness_probe(
    argv: tuple[str, ...], call: Callable[[GrindRuntime], object]
) -> None:
    """
    Given a runtime command that emits `ok: true` but exits non-zero
    When the port calls it
    Then it is a subprocess failure, not a success.

    The exit-code tolerance belongs to `grind check` alone, whose code carries
    a verdict. Applying it generally would let a wrapper or post-command
    failure read as success — and the executor would go on to enact the other
    side of the pairing.
    """
    runner = ScriptedRunner({argv: _ok({"ok": True, "applied": True, "state": {"items": {}}}, 1)})

    with pytest.raises(ExecutorError) as raised:
        call(GrindRuntime(runner))

    assert raised.value.code is ErrorCode.RUNTIME_SUBPROCESS


def test_a_nonzero_exit_from_the_facade_is_a_failure_whatever_it_says() -> None:
    """
    Given a facade command that emits `ok: true` but exits non-zero
    When the port calls it
    Then it is a transport failure.

    No facade verb carries a verdict in its exit code, so the tolerance never
    applies on this side at all.
    """
    runner = ScriptedRunner({("work", "claim"): _ok({"protocol": "1", "ok": True}, 1)})

    with pytest.raises(ExecutorError) as raised:
        WorkTracker(runner).claim("w-1")

    assert raised.value.code is ErrorCode.TRACKER_SUBPROCESS


@pytest.mark.parametrize(
    ("exit_code", "stale"),
    [(1, False), (2, True), (127, True), (2, False)],
    ids=["exit-1-contradicting-verdict", "exit-2", "exit-127", "exit-2-not-stale"],
)
def test_only_the_documented_stale_exit_is_tolerated(exit_code: int, stale: bool) -> None:
    """
    Given a staleness probe exiting non-zero in any way the contract does not
    describe
    When the port calls it
    Then it is a subprocess failure.

    The quirk is exactly `grind check` exiting 1 *and* reporting stale. A
    wrapper exiting 2 or 127 around a valid envelope is a transport failure,
    and an exit 1 contradicting `stale: false` is incoherent — tolerating
    either would report a healthy verdict for a run nobody probed.
    """
    runner = ScriptedRunner({_CHECK: _ok({"ok": True, "stale": stale, "age_s": 1}, exit_code)})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).staleness()

    assert raised.value.code is ErrorCode.RUNTIME_SUBPROCESS


def test_a_healthy_check_reports_not_stale() -> None:
    """
    Given a fresh grind
    When staleness is probed without a threshold
    Then the verdict is not stale and no `--max-age` is sent.
    """
    runner = ScriptedRunner({_CHECK: _ok({"ok": True, "stale": False, "age_s": True})})

    verdict = GrindRuntime(runner).staleness()

    assert verdict.stale is False
    # `true` is not an age: a bool must not survive the numeric coercion.
    assert verdict.age_s == 0.0
    assert runner.calls == [("grind", "check")]


def test_a_runtime_error_envelope_becomes_a_typed_failure_carrying_its_message() -> None:
    """
    Given the runtime refusing a command
    When the port calls it
    Then E_RUNTIME_SUBPROCESS is raised carrying the runtime's own message.
    """
    runner = ScriptedRunner({_STATUS: _ok({"ok": False, "error": {"message": "no events"}}, 1)})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).state()

    assert raised.value.code is ErrorCode.RUNTIME_SUBPROCESS
    assert raised.value.message == "no events"
    assert raised.value.retryable is True


def test_unparseable_runtime_output_on_a_clean_exit_is_an_envelope_fault() -> None:
    """
    Given the runtime exiting 0 with output that is not JSON
    When the port calls it
    Then E_RUNTIME_ENVELOPE is raised and the transcript names the argv.

    Distinguished from a process failure deliberately: a zero exit says the
    program ran, so the fault is in what it said.
    """
    runner = ScriptedRunner({_STATUS: CommandResult(0, "not json", "")})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).state()

    assert raised.value.code is ErrorCode.RUNTIME_ENVELOPE
    assert "grind status --full" in raised.value.message


def test_unparseable_output_on_a_failed_exit_reports_the_process_failure() -> None:
    """
    Given the runtime exiting non-zero with no envelope at all
    When the port calls it
    Then E_RUNTIME_SUBPROCESS is raised, exit code and streams included.

    The process failure is the more useful diagnosis when both are true.
    """
    runner = ScriptedRunner({_STATUS: CommandResult(127, "", "not found: grind")})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).state()

    assert raised.value.code is ErrorCode.RUNTIME_SUBPROCESS
    assert "not found: grind" in raised.value.message


@pytest.mark.parametrize(
    ("call", "argv"),
    [
        (lambda t: t.claim("w-1"), ("work", "claim", "w-1")),
        (
            lambda t: t.park("w-1", reason="ci-failure", note="red"),
            ("work", "park", "w-1", "--reason", "ci-failure", "--note", "red"),
        ),
        (lambda t: t.redispatch("w-1"), ("work", "redispatch", "w-1")),
        (lambda t: t.abandon("w-1"), ("work", "abandon", "w-1")),
        (lambda t: t.close("w-1"), ("work", "close", "w-1")),
        (lambda t: t.sync(), ("work", "sync")),
    ],
    ids=["claim", "park", "redispatch", "abandon", "close", "sync"],
)
def test_each_tracker_verb_maps_to_its_facade_invocation(
    call: Callable[[WorkTracker], None], argv: tuple[str, ...]
) -> None:
    """
    Given each tracker verb the pairing table names
    When it is called
    Then the facade is invoked with that verb and its arguments.

    Pins the facade argv: the executor addresses the tracker only through
    `work`, and a park's reason reaches `--reason` unchanged.
    """
    runner = ScriptedRunner(
        {argv[:2]: _ok({"protocol": "1", "ok": True, "data": {"reason": "ci-failure"}})}
    )

    call(WorkTracker(runner))

    assert runner.calls == [argv]


@pytest.mark.parametrize(
    "data",
    [None, {}, {"reason": None}, {"reason": ""}, {"reason": 7}, "not an object"],
    ids=["null", "empty", "null-reason", "empty-reason", "int-reason", "not-an-object"],
)
def test_a_park_reply_without_a_usable_reason_is_a_tracker_failure(data: object) -> None:
    """
    Given a successful park whose reply carries no usable reason
    When the port calls it
    Then it fails rather than reporting agreement.

    The reply is the only evidence of which reason the tracker holds. Reading
    an unusable one as "no disagreement" would re-open exactly the divergence
    the check exists to close — the same rule the parser applies to `parked`
    and `work_id`: a degraded value that authorises is a fault, not a default.
    """
    runner = ScriptedRunner({("work", "park"): _ok({"ok": True, "data": data})})

    with pytest.raises(ExecutorError) as raised:
        WorkTracker(runner).park("w-1", reason="ci-failure", note="red")

    assert raised.value.code is ErrorCode.TRACKER_SUBPROCESS


def test_a_durable_append_followed_by_a_failed_exit_keeps_the_written_marker() -> None:
    """
    Given a `grind log` reply proving the event applied, followed by a
    non-zero exit
    When the port appends
    Then it fails, but records that the write is durable.

    A wrapper dying after the runtime wrote is still a failure — losing the
    write would have the report contradict the event log, which is the one
    thing the marker exists to prevent.
    """
    runner = ScriptedRunner({_LOG: _ok({"ok": True, "applied": True}, 1)})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).append("item_started", {"item": "it-1"})

    assert raised.value.code is ErrorCode.RUNTIME_SUBPROCESS
    assert raised.value.data.get(EVENT_WAS_WRITTEN) is True


def test_a_failed_exit_with_no_proof_of_a_write_carries_no_marker() -> None:
    """
    Given a runtime call that failed without proving anything applied
    When the port calls it
    Then no written-event marker rides the failure.

    The inverse: the marker is evidence, so it must not be attached on the
    strength of a call merely having been attempted.
    """
    runner = ScriptedRunner({_LOG: _ok({"ok": False, "error": {"message": "nope"}}, 1)})

    with pytest.raises(ExecutorError) as raised:
        GrindRuntime(runner).append("item_started", {"item": "it-1"})

    assert EVENT_WAS_WRITTEN not in raised.value.data


def test_a_failed_tracker_call_is_a_retryable_transport_failure() -> None:
    """
    Given the facade refusing a claim
    When the port calls it
    Then E_TRACKER_SUBPROCESS is raised carrying the facade's message.
    """
    runner = ScriptedRunner(
        {("work", "claim"): _ok({"ok": False, "error": {"message": "not claimable"}}, 1)}
    )

    with pytest.raises(ExecutorError) as raised:
        WorkTracker(runner).claim("w-1")

    assert raised.value.code is ErrorCode.TRACKER_SUBPROCESS
    assert raised.value.message == "not claimable"


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": False, "error": {}},
        {"ok": False, "error": {"message": ""}},
        {"ok": False, "error": "not an object"},
        {"ok": False},
        ["not an envelope at all"],
    ],
    ids=["no-message", "empty-message", "error-not-an-object", "no-error", "not-an-object"],
)
def test_a_refusal_carrying_no_readable_message_falls_back_to_the_transcript(
    reply: object,
) -> None:
    """
    Given a failure reply with no readable message, in each of the shapes one
    can take
    When the port calls it
    Then the raised error carries the argv, exit code and streams instead.

    An empty message is the one thing an operator cannot act on; the
    transcript is always available, so it is what fills the gap.
    """
    runner = ScriptedRunner({("work", "claim"): _ok(reply, 1)})

    with pytest.raises(ExecutorError) as raised:
        WorkTracker(runner).claim("w-1")

    assert "work claim w-1" in raised.value.message
    assert "exited 1" in raised.value.message


def test_a_timed_out_command_is_a_failed_result_not_an_escaping_exception() -> None:
    """
    Given a command that outruns the port's timeout
    When the real runner runs it
    Then a failed CommandResult comes back naming the timeout.

    Same guarantee as a missing binary: nothing leaves this seam except a
    result the caller can turn into a typed error.
    """

    def _timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="grind", timeout=1)

    runner = SubprocessRunner()
    with mock.patch.object(subprocess, "run", _timeout):
        result = runner.run(["grind", "status"])

    assert result.exit_code != 0
    assert "timed out" in result.stderr


def test_a_failed_sync_gets_its_own_code() -> None:
    """
    Given a sync that fails
    When the port calls it
    Then E_SYNC_FAILED is raised, not the generic tracker transport code.

    The distinction is load-bearing: a failed sync leaves the mutations
    applied, so its repair is different from a failed mutation's.
    """
    runner = ScriptedRunner({("work", "sync"): CommandResult(1, "", "dolt push rejected")})

    with pytest.raises(ExecutorError) as raised:
        WorkTracker(runner).sync()

    assert raised.value.code is ErrorCode.SYNC_FAILED


def test_the_real_runner_returns_the_exit_code_and_both_streams() -> None:
    """
    Given a command that runs and writes to both streams
    When the real runner runs it
    Then its exit code, stdout and stderr all come back.

    The one test that exercises the actual subprocess call; everything above
    this seam is driven by scripted results, so nothing else would notice a
    stream being dropped.
    """
    script = "import sys; sys.stdout.write('out'); sys.stderr.write('err'); sys.exit(3)"

    result = SubprocessRunner().run([sys.executable, "-c", script])

    assert (result.exit_code, result.stdout, result.stderr) == (3, "out", "err")


def test_a_missing_binary_is_a_failed_result_not_an_escaping_exception() -> None:
    """
    Given a command that does not exist on PATH
    When the real runner runs it
    Then a failed CommandResult comes back naming the miss.

    Every failure in this package reaches the caller as a typed error; a bare
    FileNotFoundError would escape as an internal error instead.
    """
    result = SubprocessRunner().run(["executor-no-such-binary-9k9"])

    assert result.exit_code != 0
    assert "not found" in result.stderr


def test_both_fakes_satisfy_the_port_protocols() -> None:
    """
    Given the suite's fakes
    When they are checked against the port protocols
    Then both conform.

    Pins S9T1-A3 structurally: the unit suite drives the same interfaces the
    real ports implement, so passing with fakes says something about the real
    call sites.
    """
    assert isinstance(FakeRuntime(run_state()), RuntimePort)
    assert isinstance(FakeTracker(), TrackerPort)
