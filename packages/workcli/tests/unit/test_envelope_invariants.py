"""Envelope invariant matrix + handshake tail + the backend quarantine.

Every one of the twelve contract verbs, in both a success and a failure
case, must emit exactly one parseable JSON envelope on stdout carrying
`protocol`, with the exit code mirroring `ok` and the error shape typed —
uniformly, regardless of which verb or which typed error fired. This file
asserts ONLY those uniform invariants; per-verb data-shape assertions
belong to that verb's own granular test file (`test_show_normalization.py`,
`test_sync.py`, etc.) and are deliberately not duplicated here.

The quarantine is the last invariant in the file and the widest: whatever a
verb emits, it never names the tracker behind the seam. It is asserted twice
over, because neither way is sufficient alone. The behavioural half drives
the real CLI and reads the bytes that actually leave it, which is the only
way to catch text the adapter passed through rather than wrote. The
source-level half scans every message the adapter is *capable* of raising,
which is the only way to cover the paths no test happens to drive — and the
audit that found these leaks in the first place found most of them on paths
no test drove.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.conftest import run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli import PROTOCOL_VERSION
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError


def _not_found_config_loader(_explicit_path: str | None) -> TrackLayerConfig:
    # Byte-identical to pre-track-layer behavior: keeps the
    # lifecycle `create_noun` case from making an unscripted `bd show
    # <parent>` call against this repo's own real project-config.toml.
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

_OK = BdResult(returncode=0, stdout="", stderr="")
_EMPTY_ARRAY = BdResult(returncode=0, stdout="[]", stderr="")
_GARBAGE = BdResult(returncode=0, stdout="not json at all {{{", stderr="")
_NOT_FOUND = BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus"\n')


def _create_ok() -> BdResult:
    return BdResult(
        returncode=0, stdout=json.dumps({"id": "x.9", "schema_version": 3, "title": "T"}), stderr=""
    )


def _show_ok() -> BdResult:
    return BdResult(
        returncode=0, stdout=(FIXTURES / "bd_show_wgclw9.1.json").read_text(), stderr=""
    )


def _dep_list_down() -> BdResult:
    return BdResult(
        returncode=0, stdout=(FIXTURES / "bd_dep_list_down.json").read_text(), stderr=""
    )


def _dep_list_up() -> BdResult:
    return BdResult(returncode=0, stdout=(FIXTURES / "bd_dep_list_up.json").read_text(), stderr="")


def _label_list_ok() -> BdResult:
    return BdResult(
        returncode=0, stdout=(FIXTURES / "bd_label_list_wgclw9.1.json").read_text(), stderr=""
    )


def _item_raw(
    item_id: str, title: str, *, status: str = "open", labels: list[str] | None = None
) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "issue_type": "task",
        "status": status,
        "priority": 2,
        "labels": labels or [],
        "dependencies": [],
        "dependents": [],
    }


def _search_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _show_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _list_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _lifecycle_create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


@dataclass(frozen=True)
class VerbCase:
    verb: str
    success_argv: list[str]
    success_steps: list[ScriptedStep]
    failure_argv: list[str]
    failure_steps: list[ScriptedStep]
    config_loader: Callable[[str | None], TrackLayerConfig] | None = None


VERB_CASES: list[VerbCase] = [
    VerbCase(
        "show",
        ["show", "agents-config-wgclw.9.1"],
        [ScriptedStep(("show",), _show_ok())],
        ["show", "bogus"],
        [ScriptedStep(("show",), _NOT_FOUND)],
    ),
    VerbCase(
        "create",
        ["create", "--raw", "--title", "T"],
        [ScriptedStep(("create",), _create_ok())],
        ["create", "--title", "T"],  # missing --raw -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "update",
        ["update", "x.1", "--set-title", "New title"],
        [ScriptedStep(("update",), _OK)],
        ["update", "x.1"],  # no --set-* flags -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "note",
        ["note", "x.1", "hello"],
        [ScriptedStep(("update",), _OK)],
        ["note", "bogus", "hi"],
        [ScriptedStep(("update",), _NOT_FOUND)],
    ),
    VerbCase(
        "close",
        ["close", "a.1"],
        [
            ScriptedStep(("close",), _OK),
            # close-walk parent probe: parentless -> nothing walked
            ScriptedStep(("show",), _show_result(_item_raw("a.1", "T", status="closed"))),
        ],
        ["close", "bogus"],
        [ScriptedStep(("close",), _NOT_FOUND)],
    ),
    VerbCase(
        "reopen",
        ["reopen", "a.1"],
        [ScriptedStep(("reopen",), _OK)],
        ["reopen", "bogus"],
        [ScriptedStep(("reopen",), _NOT_FOUND)],
    ),
    VerbCase(
        "list",
        ["list"],
        [ScriptedStep(("list",), _EMPTY_ARRAY)],
        ["list"],
        [ScriptedStep(("list",), _GARBAGE)],
    ),
    VerbCase(
        "ready",
        ["ready"],
        # the parked_stale block's read precedes `ready`'s own listing
        [ScriptedStep(("list",), _EMPTY_ARRAY), ScriptedStep(("ready",), _EMPTY_ARRAY)],
        ["ready"],
        [ScriptedStep(("list",), _EMPTY_ARRAY), ScriptedStep(("ready",), _GARBAGE)],
    ),
    VerbCase(
        "dep",
        ["dep", "list", "agents-config-wgclw.9.1"],
        [
            ScriptedStep(("dep", "list", "agents-config-wgclw.9.1", "--json"), _dep_list_down()),
            ScriptedStep(
                ("dep", "list", "agents-config-wgclw.9.1", "--direction", "up", "--json"),
                _dep_list_up(),
            ),
        ],
        ["dep", "add", "x.1"],  # missing TARGET -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "label",
        ["label", "list", "x.1"],
        [ScriptedStep(("label", "list"), _label_list_ok())],
        ["label", "add", "x.1"],  # no labels -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "search",
        ["search", "quarantine"],
        [ScriptedStep(("search",), _EMPTY_ARRAY)],
        ["search", "quarantine"],
        [ScriptedStep(("search",), _GARBAGE)],
    ),
    VerbCase(
        "sync",
        ["sync"],
        [ScriptedStep(("dolt", "commit"), _OK), ScriptedStep(("dolt", "push"), _OK)],
        ["sync", "--pull"],
        [
            ScriptedStep(
                ("dolt", "pull"),
                BdResult(returncode=1, stdout="", stderr="cannot merge with uncommitted changes\n"),
            )
        ],
    ),
    # --- lifecycle verbs (one success + one failure per verb, over the
    # seven lifecycle verbs from create through reconcile) ---------
    VerbCase(
        "create_noun",
        ["create", "spec", "--title", "New Objective", "--parent", "P"],
        [
            ScriptedStep(("search",), _search_result()),  # no title collision
            ScriptedStep(("create",), _lifecycle_create_result("s.1")),  # container
            ScriptedStep(("label", "add"), _OK),  # shape-spec (finalize shape guard)
            ScriptedStep(("label", "remove"), _OK),  # shape-feat (finalize shape guard)
            ScriptedStep(
                ("show",), _show_result(_item_raw("s.1", "New Objective"))
            ),  # instantiate get
            ScriptedStep(("create",), _lifecycle_create_result("s.2")),  # design child
            ScriptedStep(("create",), _lifecycle_create_result("s.3")),  # placeholder
            ScriptedStep(("label", "add"), _OK),  # planned
            ScriptedStep(("label", "remove"), _OK),  # creating-spec, removed last
        ],
        ["create", "feat", "--title", "Existing Feature", "--parent", "P"],
        [ScriptedStep(("search",), _search_result(_item_raw("f.9", "Existing Feature")))],
        config_loader=_not_found_config_loader,
    ),
    VerbCase(
        "claim",
        ["claim", "c.1"],
        [
            ScriptedStep(("show",), _show_result(_item_raw("c.1", "T", status="open"))),
            ScriptedStep(("ready",), _list_result(_item_raw("c.1", "T", status="open"))),
            ScriptedStep(("list",), _EMPTY_ARRAY),  # parked_stale, before the claim
            ScriptedStep(("update",), _OK),
        ],
        ["claim", "c.2"],
        [ScriptedStep(("show",), _show_result(_item_raw("c.2", "T", status="closed")))],
    ),
    VerbCase(
        "release",
        ["release", "r.1"],
        [
            ScriptedStep(("show",), _show_result(_item_raw("r.1", "T", status="in_progress"))),
            ScriptedStep(("update",), _OK),
        ],
        ["release", "r.2"],
        [ScriptedStep(("show",), _show_result(_item_raw("r.2", "T", status="closed")))],
    ),
    VerbCase(
        "deliver",
        ["deliver", "d.1", "--pr", "https://example/pr/9"],
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("d.1", "T", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(("update",), _OK),  # delivered note
            ScriptedStep(("close",), _OK),
            # close-walk parent probe: parentless -> nothing walked
            ScriptedStep(
                ("show",),
                _show_result(_item_raw("d.1", "T", status="closed", labels=["shape-feat"])),
            ),
        ],
        ["deliver", "d.2"],  # no --pr/--items/--trivial -> E_EVIDENCE
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("d.2", "T", status="open", labels=["shape-feat"]))
            )
        ],
    ),
    VerbCase(
        "plan",
        ["plan", "p.1", "--done"],
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("p.1", "T", status="open", labels=["shape-spec"]))
            ),
            ScriptedStep(("label", "add"), _OK),
        ],
        ["plan", "p.2"],  # neither --done nor --undo -> E_USAGE, no bd call
        [],
    ),
    VerbCase(
        "promote",
        ["promote", "m.1"],
        [
            ScriptedStep(
                ("show",), _show_result(_item_raw("m.1", "T", status="open", labels=["shape-feat"]))
            ),
            ScriptedStep(("label", "add"), _OK),  # creating-spec
            ScriptedStep(("label", "add"), _OK),  # shape-spec
            ScriptedStep(("label", "remove"), _OK),  # shape-feat
            ScriptedStep(
                ("show",), _show_result(_item_raw("m.1", "T", status="open", labels=["shape-spec"]))
            ),  # instantiate get
            ScriptedStep(("create",), _lifecycle_create_result("m.2")),  # design child
            ScriptedStep(("create",), _lifecycle_create_result("m.3")),  # placeholder
            ScriptedStep(("label", "add"), _OK),  # planned
            ScriptedStep(("label", "remove"), _OK),  # creating-spec, removed last
        ],
        ["promote", "m.2"],  # not shape-feat -> E_USAGE
        [ScriptedStep(("show",), _show_result(_item_raw("m.2", "T", status="open")))],
    ),
    VerbCase(
        "reconcile",
        ["reconcile"],
        [
            ScriptedStep(("list",), _list_result()),  # interrupted-deliver sweep: empty
            ScriptedStep(("list",), _list_result()),  # pending-placeholder sweep: empty
            ScriptedStep(("list",), _list_result()),  # orphaned-design sweep: empty
            ScriptedStep(("list",), _list_result()),  # interrupted-instantiation sweep: empty
        ],
        ["reconcile"],
        [ScriptedStep(("list",), _GARBAGE)],  # unparseable bd list output -> E_BACKEND_DRIFT
    ),
    VerbCase(
        "discover",
        [
            "discover",
            "--noun",
            "feat",
            "--title",
            "New discovery",
            "--anchor",
            "epic-1",
            "--anchor-why",
            "best fit",
            "--discovered-from",
            "src-1",
            "--scope",
            "out-of-scope",
            "--scope-why",
            "found it",
            "--priority",
            "P2",
            "--priority-why",
            "hurts overnight",
        ],
        [
            ScriptedStep(("show", "src-1", "--json"), _show_result(_item_raw("src-1", "T"))),
            ScriptedStep(
                ("show", "epic-1", "--json"),
                _show_result(_item_raw("epic-1", "T", labels=["shape-epic"])),
            ),
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _lifecycle_create_result("new-1")),
            ScriptedStep(("dep", "add"), _OK),
            ScriptedStep(("show", "new-1", "--json"), _show_result(_item_raw("new-1", "T"))),
        ],
        ["discover", "--noun", "feat", "--title", "T"],  # missing triage fields -> no bd call
        [],
        config_loader=_not_found_config_loader,
    ),
]

TYPED_ERROR_CODES = {str(code) for code in ErrorCode}


def _assert_stdout_is_exactly_one_envelope(
    runner: ScriptedBdRunner,
    argv: list[str],
    config_loader: Callable[[str | None], TrackLayerConfig] | None = None,
) -> dict:
    from io import StringIO

    from workcli.cli import main

    out = StringIO()
    err = StringIO()
    exit_code = main(argv, runner=runner, out=out, err=err, config_loader=config_loader)
    stdout_text = out.getvalue()
    # Exactly one JSON value on stdout, nothing before or after it: a
    # trailing newline is the only thing besides the envelope permitted.
    assert stdout_text.endswith("\n")
    body = stdout_text[:-1]
    assert "\n" not in body, f"stdout carried more than one line: {stdout_text!r}"
    envelope = json.loads(body)
    return exit_code, envelope  # type: ignore[return-value]


@pytest.mark.parametrize("case", VERB_CASES, ids=lambda c: c.verb)
def test_success_case_yields_a_uniform_ok_envelope(case: VerbCase) -> None:
    runner = ScriptedBdRunner(steps=list(case.success_steps))
    exit_code, envelope = _assert_stdout_is_exactly_one_envelope(
        runner, case.success_argv, case.config_loader
    )

    assert exit_code == 0
    assert envelope["protocol"] == PROTOCOL_VERSION
    assert envelope["ok"] is True
    assert envelope["error"] is None


@pytest.mark.parametrize("case", VERB_CASES, ids=lambda c: c.verb)
def test_failure_case_yields_a_uniform_error_envelope(case: VerbCase) -> None:
    runner = ScriptedBdRunner(steps=list(case.failure_steps))
    exit_code, envelope = _assert_stdout_is_exactly_one_envelope(
        runner, case.failure_argv, case.config_loader
    )

    assert exit_code == 1
    assert envelope["protocol"] == PROTOCOL_VERSION
    assert envelope["ok"] is False
    assert envelope["data"] is None
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] in TYPED_ERROR_CODES


def test_protocol_version_data_matches_every_other_verbs_protocol_field() -> None:
    handshake_exit, handshake_envelope, _ = run_cli_with_runner(
        ["--protocol-version"], ScriptedBdRunner(steps=[])
    )
    assert handshake_exit == 0
    assert handshake_envelope["data"] == {"protocol": PROTOCOL_VERSION}

    for case in VERB_CASES:
        runner = ScriptedBdRunner(steps=list(case.success_steps))
        _, envelope = _assert_stdout_is_exactly_one_envelope(
            runner, case.success_argv, case.config_loader
        )
        assert envelope["protocol"] == handshake_envelope["data"]["protocol"]


# ── the backend quarantine ───────────────────────────────────────────────

_SRC = Path(__file__).resolve().parents[2] / "src" / "workcli"
_ADAPTERS = _SRC / "adapters"

# The names that would tell a consumer which tracker is behind the seam: the
# binary, the project that names its environment variable and its storage
# directory, and the storage engine under it. Word edges are spelled out
# rather than left to `\b` so `BEADS_DIR` and `.beads` are caught — `_` and a
# leading `.` are word characters, and `\b` would wave both through.
#
# Restated here rather than imported from the adapter's own scrubber, on
# purpose. The adapter's list is a claim about what it knows to hide; a test
# that imported it would ratify that claim instead of checking it, and would
# go green the moment someone shortened it. Two independent statements of the
# same fact: narrow one without the other and this file turns red.
_BACKEND_IDENTITY = re.compile(
    r"(?<![A-Za-z0-9])\.?(?:beads|bd|dolt)(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Real stderr, captured from the live backend, one line per failure mode this
# adapter can meet. The first four it classifies; the last two it does not,
# and those are the ones that carry the backend's own text outward — which is
# exactly why they are here. The missing-workspace line is the incident that
# prompted this invariant: it names the binary, its environment variable and
# its storage directory in a single sentence.
# Named rather than inlined: it is the only multi-line capture, and inside a
# list literal its implicit concatenation reads like a missing comma. A comma
# dropped there would merge two entries and shrink this corpus without failing
# anything, which is the one way a check like this goes quiet.
_MISSING_WORKSPACE_STDERR = (
    "Error: no beads database found\n"
    "Hint: run 'bd where' to inspect the resolved workspace, or 'bd init' to create a new "
    "database\n      or set BEADS_DIR to point to your .beads directory\n"
)

_CAPTURED_BACKEND_STDERR = [
    'no issue found matching "bogus"\n',
    "Error getting parent x.9: not found: issue x.9\n",
    "cannot close probe-2mk: blocked by open issues [probe-6cl] (use --force to override)\n",
    "epics can only block other epics, not tasks\n",
    _MISSING_WORKSPACE_STDERR,
    "panic: dolt: runtime error at hash 0xdeadbeef\n",
]


def _assert_envelope_is_quarantined(envelope: dict) -> None:
    """Assert the facade-authored half of `envelope` names no backend.

    `data` is exempt, and the exemption is the point rather than a gap: an
    item's title, description and notes are whatever a user typed into them,
    and a tracker item that discusses the tracker is a thing people write.
    Echoing a user's own words back is not disclosure — the facade would be
    corrupting its payload if it scrubbed them. `error` carries no user text
    at all, so it is held to the whole rule.
    """
    error = envelope.get("error")
    if error is None:
        return
    published = json.dumps(error)
    leak = _BACKEND_IDENTITY.search(published)
    assert leak is None, f"error envelope names the backend ({leak.group(0)!r}): {published}"
    detail = error.get("detail")
    assert not isinstance(detail, dict) or "argv" not in detail, (
        f"error envelope publishes the backend's command line: {published}"
    )


@pytest.mark.parametrize("case", VERB_CASES, ids=lambda c: c.verb)
def test_a_successful_envelope_never_names_the_backend(case: VerbCase) -> None:
    runner = ScriptedBdRunner(steps=list(case.success_steps))
    _, envelope = _assert_stdout_is_exactly_one_envelope(
        runner, case.success_argv, case.config_loader
    )

    _assert_envelope_is_quarantined(envelope)


@pytest.mark.parametrize("case", VERB_CASES, ids=lambda c: c.verb)
def test_a_failure_envelope_never_names_the_backend(case: VerbCase) -> None:
    runner = ScriptedBdRunner(steps=list(case.failure_steps))
    _, envelope = _assert_stdout_is_exactly_one_envelope(
        runner, case.failure_argv, case.config_loader
    )

    _assert_envelope_is_quarantined(envelope)


@pytest.mark.parametrize("stderr", _CAPTURED_BACKEND_STDERR)
def test_real_backend_stderr_never_reaches_a_consumer_intact(stderr: str) -> None:
    """
    Given a failure the real backend reports in its own words
    When the facade turns that failure into an envelope
    Then nothing in the envelope says which backend it was.

    The matrix above only meets the failures its fakes are scripted to
    produce. This meets the ones the backend actually produces, including the
    two it reports in sentences that name itself.
    """
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("show",), BdResult(returncode=1, stdout="", stderr=stderr))]
    )

    _, envelope = _assert_stdout_is_exactly_one_envelope(runner, ["show", "x.1"])

    assert envelope["ok"] is False
    _assert_envelope_is_quarantined(envelope)


def _adapter_sources() -> list[Path]:
    return sorted(_ADAPTERS.rglob("*.py"))


def _generic_sources() -> list[Path]:
    return sorted(path for path in _SRC.rglob("*.py") if not path.is_relative_to(_ADAPTERS))


def _error_messages(tree: ast.AST) -> dict[int, tuple[ast.expr, set[str]]]:
    """Every message argument handed to an error constructor, keyed by line.

    `WorkError`'s message is its second positional argument; `_drift`, the
    adapter's own drift-alarm helper, takes it first. Both are matched by
    name, so a third helper wrapping either would need adding here — which is
    the intended friction: a new way to author an error is a new way to leak.

    Each message comes with the parameter names in scope where it was
    written, because a message that is simply a parameter being passed along
    was authored at the call site rather than here, and the call site is
    itself in this list.
    """
    found: dict[int, tuple[ast.expr, set[str]]] = {}
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        params = {
            arg.arg for arg in (*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs)
        }
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            index = {"WorkError": 1, "_drift": 0}.get(str(name))
            if index is None or len(node.args) <= index:
                continue
            # Nested functions are walked by their parent too; union the
            # scopes rather than letting whichever pass ran last win.
            previous = found.get(node.lineno)
            merged = params | (previous[1] if previous else set())
            found[node.lineno] = (node.args[index], merged)
    return found


def _module_string_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level `NAME = "..."` bindings, the adapter's other home for text."""
    constants = {}
    for node in getattr(tree, "body", []):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def _literal_text(expr: ast.expr) -> str | None:
    """The fixed text of a string literal or f-string; None if it isn't one.

    An f-string's interpolations are skipped — their runtime values are the
    scrubber's problem, not this scan's. What is returned is everything the
    author typed, which is what an authored leak is made of.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        return "".join(
            part.value
            for part in expr.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def test_the_source_scan_actually_has_sources_to_scan() -> None:
    """
    Given the package's source tree
    When it is split into the adapter and everything above it
    Then both halves are non-empty and the adapter raises errors at all.

    The control for the three scans below. Each is an assertion over a
    comprehension, and every one of them passes trivially over an empty list
    — a scan pointed at the wrong directory would prove nothing, loudly.
    """
    assert len(_adapter_sources()) >= 4
    assert len(_generic_sources()) >= 10
    messages = [
        message
        for path in _adapter_sources()
        for message in _error_messages(ast.parse(path.read_text(encoding="utf-8"))).values()
    ]
    assert len(messages) >= 20


def test_no_error_the_adapter_can_raise_names_the_backend() -> None:
    """
    Given every error message the adapter is able to construct
    When each one's authored text is read
    Then none of it names the backend.

    Covers what no behavioural test can: a message on a branch nothing
    currently drives is still a message that will one day be published.
    """
    offenders = []
    for path in _adapter_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _module_string_constants(tree)
        for lineno, (expr, params) in _error_messages(tree).items():
            text = _literal_text(expr)
            if text is None and isinstance(expr, ast.Name):
                if expr.id in params:
                    continue  # forwarded; authored at a call site that is scanned
                text = constants.get(expr.id)
            assert text is not None, (
                f"{path.name}:{lineno} builds an error message this scan cannot read; "
                "author it as a literal, an f-string, or a module constant so it stays checkable"
            )
            if _BACKEND_IDENTITY.search(text):
                offenders.append(f"{path.name}:{lineno}: {text}")

    assert offenders == []


def test_the_adapter_has_no_route_to_publish_a_command_line() -> None:
    """
    Given the adapter's sources
    When they are searched for the key a command line would travel under
    Then it appears nowhere.

    A caller cannot act on the backend's argv without already knowing the
    backend, so publishing one buys nothing and spends the whole quarantine.
    Asserting the key is absent from the source is what stops it coming back
    on a path no test drives.
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in _adapter_sources()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and node.value == "argv"
    ]

    assert offenders == []


def test_nothing_above_the_adapter_names_the_backend_in_a_string() -> None:
    """
    Given every module of the facade that sits above the adapter seam
    When its string literals are read — argparse help among them
    Then none of them names the backend.

    The other direction of the same wall. Prose is out of scope here on
    purpose: a comment is read by whoever maintains this package, while a
    string literal is liable to be printed, and `work --help` printing the
    backend's name is contract, not commentary.
    """
    offenders = []
    for path in _generic_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            if _BACKEND_IDENTITY.search(node.value):
                offenders.append(f"{path.relative_to(_SRC)}:{node.lineno}: {node.value!r}")

    assert offenders == []
