#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Assemble an attack round's record from the lens reports and the author's dispositions.

Usage: uv run assemble_record.py union --round <round.json> --report <lens>=<path> ...
       uv run assemble_record.py assemble --union <union.json> --dispositions <path> --spec <document>

The union step reads the round file the emitter wrote and one raw output per lens it names, and
writes `union.json` and `dispositions.skeleton.json` beside the round file. The assemble step
reads the union and the filled dispositions, and writes `<document>-ac-attack.json` beside the
document. A refusal writes nothing.

Stdout is JSON. Exit 0 on success, 2 on refusal. Output is deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
# The lens registry the other two scripts read: each lens's prompt front matter names the rules it
# enforces and whether it returns workings, and a lens returning workings keeps their schema beside
# its prompt. The scripts deploy standalone and cannot import each other, so the few lines that
# read it are repeated here.
LENSES_DIR = HERE / "lenses"
FRONT_MATTER_KEYS = ("enforces", "workings")
WORKINGS_SCHEMA = "workings.schema.json"
RECORD_SUFFIX = "-ac-attack.json"
UNION_NAME = "union.json"
SKELETON_NAME = "dispositions.skeleton.json"

EXIT_OK = 0
EXIT_REFUSED = 2

# The keys the lens output contract declares, at each level of an objection. Anything else is
# dropped, since the record's schema admits nothing else and no reader of the record consults it.
REPORT_KEYS = ("lens", "report", "objections", "workings")
OBJECTION_KEYS = ("lens", "target_ac", "ground", "objection", "obligation", "scenario")
GROUND_KEYS = ("rule", "reason")
SCENARIO_KEYS = ("given", "when", "expect")
DISPOSITION_KEYS = ("id", "objection", "disposition", "rationale", "revision", "covering_ac")

RERUN = "run that lens again and name its new output"


class Refusal(Exception):
    """A typed refusal; carries a stable machine-readable code and, where one is at fault, a lens."""

    def __init__(self, code: str, message: str, lens: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.lens = code, message, lens

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message,
                **({"lens": self.lens} if self.lens is not None else {})}


class RepeatedKey(ValueError):
    """A JSON object naming one key twice, which a plain parse would collapse to the last."""


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if repeated := [key for key in dict.fromkeys(keys) if keys.count(key) > 1]:
        raise RepeatedKey(f"names the key {repeated[0]!r} twice in one object")
    return dict(pairs)


class Refusals(Exception):
    """Every refusal a step found, reported together so one run names every lens to rerun."""

    def __init__(self, refusals: list[Refusal]) -> None:
        super().__init__(refusals[0].message)
        self.refusals = refusals


def blank(value: Any) -> bool:
    """Whether a field carries no content: absent, not a string, or nothing but whitespace."""
    return not isinstance(value, str) or not value.strip()


def registry() -> dict[str, dict[str, Any]]:
    """Each declared lens's front matter keys this script reads, by lens name."""
    lenses = {}
    for path in sorted(LENSES_DIR.glob("*/prompt.md")):
        text = path.read_text(encoding="utf-8")
        head = text[4:].partition("\n---\n")[0] if text.startswith("---\n") else ""
        lens: dict[str, Any] = {}
        for line in head.splitlines():
            key, _, value = (part.strip() for part in line.partition(":"))
            if key in FRONT_MATTER_KEYS:
                lens[key] = ([item.strip() for item in value[1:-1].split(",") if item.strip()]
                             if value.startswith("[") and value.endswith("]") else value)
        if (schema := path.with_name(WORKINGS_SCHEMA)).exists():
            lens["workings_schema"] = json.loads(schema.read_text(encoding="utf-8"))
        lenses[path.parent.name] = lens
    return lenses


def read_json(path: Path, code: str, what: str) -> Any:
    """The JSON a file holds, or a refusal under `code` naming what the file was meant to be."""
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refusal(code, f"cannot read {what} {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def sha256_revision(data: bytes) -> str:
    """The revision of a document's bytes in the notation the emitter stamps."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------
# The union step


def read_round(path: Path) -> dict[str, Any]:
    """The round file the emitter wrote, refused unless it names a document and distinct lenses."""
    round_ = read_json(path, "bad-round", "the round file")
    lenses = round_.get("lenses") if isinstance(round_, dict) else None
    names = [entry.get("lens") for entry in lenses if isinstance(entry, dict)] if isinstance(
        lenses, list) else []
    if (not isinstance(round_, dict) or blank(round_.get("spec_path"))
            or blank(round_.get("spec_revision")) or not names
            or len(names) != len(lenses) or any(blank(name) for name in names)
            or len(set(names)) != len(names)):
        raise Refusal("bad-round", f"{path} is not a round file the emitter writes: it must name "
                                   "the document, the revision attacked, and each lens once")
    return round_


def report_text(lens: str, path: Path | None) -> str:
    """A lens's raw output, unwrapped from a transport envelope, refused where nothing is there."""
    if path is None:
        raise Refusal("missing-lens-output", f"the round names the {lens!r} lens and no --report "
                      f"names its output; {RERUN}", lens)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("missing-lens-output", f"cannot read the {lens!r} lens's output {path}: "
                      f"{exc}; {RERUN}", lens) from exc
    # A Codex run saved as its envelope carries the model's text in `rawOutput`. An envelope whose
    # `rawOutput` is empty is a run that returned nothing, whatever the envelope's own status says.
    # An object carrying `report` or `objections` is the report itself, whatever else it carries.
    try:
        envelope = json.loads(text)
    except ValueError:
        envelope = None
    if (isinstance(envelope, dict) and "rawOutput" in envelope
            and not {"report", "objections"} & envelope.keys()):
        text = envelope["rawOutput"] if isinstance(envelope["rawOutput"], str) else ""
    if not text.strip():
        raise Refusal("empty-lens-output", f"the {lens!r} lens's output {path} is empty; {RERUN}",
                      lens)
    return text


def parse_report(lens: str, text: str) -> dict[str, Any]:
    """The first JSON object in a lens's output that reads as a report.

    Models wrap the object in prose or a Markdown fence, so every opening brace is tried in turn
    and the first object carrying `report` or `objections` is the report. An objection or an
    inventory nested inside a truncated report carries neither key, so it is never mistaken for one.
    An object naming a key twice is refused rather than read: the parse keeps only the last, so
    whatever the first held would vanish without a trace.
    """
    decoder = json.JSONDecoder(object_pairs_hook=unique_keys)
    repeated = None
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except RepeatedKey as exc:
            value, repeated = None, repeated or str(exc)
        except ValueError:
            value = None
        if isinstance(value, dict) and ("report" in value or "objections" in value):
            return value
        start = text.find("{", start + 1)
    if repeated is not None:
        raise drift(lens, repeated)
    raise Refusal("unparseable-lens-output", f"the {lens!r} lens's output holds no JSON report; "
                  f"{RERUN}", lens)


def drift(lens: str, detail: str) -> Refusal:
    return Refusal("unrepairable-drift", f"the {lens!r} lens's report {detail}, which cannot be "
                   f"repaired without changing what it says; {RERUN}", lens)


def normalise(lens: str, position: int, item: Any, enforces: list[str] | None,
              repairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One objection held to the output contract: repaired, dropped as malformed, or refused.

    Returns None for an objection whose scenario leaves a part blank, which is a concern rather
    than a testable claim. Repairs are appended to `repairs` without an id, which the caller adds
    once the objection is numbered.
    """
    if not isinstance(item, dict) or not isinstance(item.get("ground"), dict):
        raise drift(lens, f"holds objection {position} without the objection shape")
    # A blank part is a concern the lens failed to make testable; a part that is not text at all is
    # a shape nothing here can read a meaning from.
    scenario = item.get("scenario", {})
    if not isinstance(scenario, dict) or any(not isinstance(scenario.get(key, ""), str)
                                             for key in SCENARIO_KEYS):
        raise drift(lens, f"holds objection {position} with a scenario that is not text")
    if any(blank(scenario.get(key)) for key in SCENARIO_KEYS):
        return None
    changes = []
    for key in sorted(set(item) - set(OBJECTION_KEYS)):
        changes.append(f"dropped the undeclared key {key!r}")
    for key in sorted(set(item["ground"]) - set(GROUND_KEYS)):
        changes.append(f"dropped the undeclared key 'ground.{key}'")
    for key in sorted(set(scenario) - set(SCENARIO_KEYS)):
        changes.append(f"dropped the undeclared key 'scenario.{key}'")
    objection = {key: item[key] for key in OBJECTION_KEYS if key in item}
    objection["ground"] = {key: item["ground"][key] for key in GROUND_KEYS if key in item["ground"]}
    objection["scenario"] = {key: scenario[key] for key in SCENARIO_KEYS}
    # The report is attributed by the file it came from, so a missing lens field is filled in; one
    # naming another lens means the output is not this lens's, and nothing here can say whose.
    if "lens" not in item:
        changes.append(f"set the missing 'lens' to {lens!r}")
    elif item["lens"] != lens:
        raise drift(lens, f"attributes objection {position} to the {item['lens']!r} lens")
    objection["lens"] = lens
    if "obligation" in item and not isinstance(item["obligation"], str):
        raise drift(lens, f"gives objection {position} an obligation that is not text")
    if "obligation" in item and blank(item["obligation"]):
        del objection["obligation"]
        changes.append("dropped the blank optional 'obligation'")
    for field in ("target_ac", "objection"):
        if blank(objection.get(field)):
            raise drift(lens, f"leaves {field!r} blank in objection {position}")
    for field in GROUND_KEYS:
        if blank(objection["ground"].get(field)):
            raise drift(lens, f"leaves 'ground.{field}' blank in objection {position}")
    # A lens's prompt carries only the rules it enforces, so a lens enforcing exactly one rule
    # objects on that rule whatever it names it. With several, which one was meant is a judgement.
    rule = objection["ground"]["rule"]
    if enforces is not None and rule not in enforces:
        if len(enforces) != 1:
            raise drift(lens, f"cites the rule {rule!r} in objection {position}, which it does not "
                        f"enforce, and it enforces {', '.join(map(repr, enforces))}")
        objection["ground"]["rule"] = enforces[0]
        changes.append(f"replaced the ground rule {rule!r}, which the lens does not enforce, with "
                       f"{enforces[0]!r}, the one rule it does")
    repairs += [{"lens": lens, "position": position, "change": change} for change in changes]
    return objection


def drop_undeclared(root: dict[str, Any], schema: dict[str, Any], value: Any, path: str,
                    changes: list[str]) -> None:
    """Drop, in place, every key of `value` the workings schema does not declare, naming each."""
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rpartition("/")[2]]
    if isinstance(value, dict) and "properties" in schema:
        for key in sorted(set(value) - set(schema["properties"])):
            del value[key]
            changes.append(f"dropped the undeclared key '{path}.{key}'")
        for key, declared in schema["properties"].items():
            if key in value:
                drop_undeclared(root, declared, value[key], f"{path}.{key}", changes)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            drop_undeclared(root, schema["items"], item, f"{path}[{index}]", changes)


def workings_fault(schema: dict[str, Any], workings: Any) -> str | None:
    """The first way the workings break the schema beside the lens's prompt, or None.

    Part ids are unique across the inventory, which the schema cannot say and the checker enforces.
    """
    for error in Draft202012Validator(schema).iter_errors(workings):
        return f"{'/'.join(map(str, error.absolute_path)) or 'the inventory'}: {error.message}"
    parts = [part for obligation in workings["obligations"] for part in obligation["parts"]]
    ids = [part["id"] for part in parts]
    for name in dict.fromkeys(ids):
        if ids.count(name) > 1:
            return f"names the part {name!r} more than once"
    # A part discharged by a criterion the inventory does not list may be discharged by nothing,
    # and its hole would then leave the round without an objection.
    for part in parts:
        for name in part["discharged_by"]:
            if name not in workings["criteria"]:
                return f"discharges the part {part['id']!r} by {name!r}, which it does not list"
    return None


def unreported_residue(workings: dict[str, Any], objections: list[dict[str, Any]]) -> list[str]:
    """Each part the inventory leaves undischarged, or criterion discharging nothing, unobjected."""
    parts = [part for obligation in workings["obligations"] for part in obligation["parts"]]
    discharging = {name for part in parts for name in part["discharged_by"]}
    residue = [("obligation", part["id"]) for part in parts if not part["discharged_by"]]
    residue += [("target_ac", name) for name in workings["criteria"] if name not in discharging]
    return [f"{field} {name!r}" for field, name in residue
            if not any(item.get(field) == name for item in objections)]


def lens_entry(lens: str, report: dict[str, Any], declared: dict[str, Any] | None,
               objections: list[dict[str, Any]], repairs: list[dict[str, Any]]) -> dict[str, Any]:
    """The record's entry for one lens: the report it filed, and its workings when it owes them.

    Every field a lens entry carries is built here.
    """
    entry: dict[str, Any] = {"lens": lens, "report": "objections" if objections else "empty"}
    requires_workings = declared is not None and declared.get("workings") == "required"
    if requires_workings:
        if "workings" not in report:
            raise drift(lens, "carries no workings, which its lens requires")
        schema, changes = declared["workings_schema"], []
        drop_undeclared(schema, schema, report["workings"], "workings", changes)
        if fault := workings_fault(schema, report["workings"]):
            raise drift(lens, f"returns workings outside its lens's schema ({fault})")
        repairs += [{"lens": lens, "change": change} for change in changes]
        residue = unreported_residue(report["workings"], objections)
        if residue:
            raise drift(lens, f"leaves {', '.join(residue)} in its workings with no objection "
                        "naming it")
        entry["workings"] = report["workings"]
    elif "workings" in report:
        repairs.append({"lens": lens, "change": "dropped workings its lens does not return"})
    return entry


def union_lens(lens: str, text: str, declared: dict[str, Any] | None,
               repairs: list[dict[str, Any]], dropped: list[dict[str, Any]]
               ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One lens's entry and its numbered objections, read off its raw output."""
    report = parse_report(lens, text)
    if "lens" in report and report["lens"] != lens:
        raise drift(lens, f"names itself the {report['lens']!r} lens")
    items = report.get("objections", [])
    # A missing verdict is read off the objections list; one the report states must agree with it.
    verdict = report.get("report", "objections" if items else "empty")
    if verdict not in ("objections", "empty") or not isinstance(items, list):
        raise drift(lens, "does not say whether it reports objections or reports empty")
    if (verdict == "empty") != (not items):
        raise drift(lens, f"reports {verdict!r} and carries {len(items)} objection(s)")
    repairs += [{"lens": lens, "change": f"dropped the undeclared report key {key!r}"}
                for key in sorted(set(report) - set(REPORT_KEYS))]
    if "lens" not in report:
        repairs.append({"lens": lens, "change": f"set the missing report 'lens' to {lens!r}"})
    if "objections" not in report:
        repairs.append({"lens": lens, "change": "set the missing 'objections' to an empty list"})
    if "report" not in report:
        repairs.append({"lens": lens, "change": f"set the missing 'report' to {verdict!r}"})
    enforces = declared.get("enforces") if declared else None
    objections, own_repairs = [], []
    for position, item in enumerate(items, 1):
        objection = normalise(lens, position, item, enforces, own_repairs)
        if objection is None:
            dropped.append({"lens": lens, "position": position,
                            "reason": "the scenario leaves given, when or expect blank"})
            continue
        # Numbered over the objections kept, so a dropped one takes no number.
        objection["id"] = f"{lens}-{len(objections) + 1}"
        for repair in own_repairs:
            repair.setdefault("id", objection["id"])
        objections.append(objection)
    repairs += own_repairs
    if items and not objections:
        raise Refusal("unusable-lens-output", f"every objection the {lens!r} lens returned is "
                      f"malformed, which is not a report that found nothing; {RERUN}", lens)
    return lens_entry(lens, report, declared, objections, repairs), objections


def reports_by_lens(values: list[str]) -> dict[str, Path]:
    reports = {}
    for value in values:
        lens, sep, path = value.partition("=")
        if not sep or not lens or not path or lens in reports:
            raise Refusal("bad-arguments", f"--report {value!r} is not <lens>=<path> for a lens "
                                           "not already named")
        reports[lens] = Path(path)
    return reports


def union(args: argparse.Namespace) -> dict[str, Any]:
    round_path = Path(args.round)
    round_ = read_round(round_path)
    names = [entry["lens"] for entry in round_["lenses"]]
    reports = reports_by_lens(args.report or [])
    if stray := sorted(set(reports) - set(names)):
        raise Refusal("bad-arguments", f"--report names {', '.join(map(repr, stray))}, which the "
                                       "round does not; only the round's lenses report into it")
    declared = registry()
    refusals: list[Refusal] = []
    entries, objections, repairs, dropped = [], [], [], []
    for lens in names:
        try:
            entry, own = union_lens(lens, report_text(lens, reports.get(lens)), declared.get(lens),
                                    repairs, dropped)
        except Refusal as exc:
            refusals.append(exc)
            continue
        entries.append(entry)
        objections += own
    if refusals:
        raise Refusals(refusals)
    result = {"spec_path": round_["spec_path"], "spec_revision": round_["spec_revision"],
              "lenses": entries, "objections": objections}
    skeleton = [{"id": item["id"], "objection": item["objection"], "disposition": "",
                 "covering_ac": "", "rationale": ""} for item in objections]
    union_path, skeleton_path = round_path.with_name(UNION_NAME), round_path.with_name(SKELETON_NAME)
    write_json(union_path, result)
    write_json(skeleton_path, skeleton)
    return {"assembled": True, "union": str(union_path), "skeleton": str(skeleton_path),
            "objections": len(objections), "repairs": repairs, "dropped": dropped}


# ---------------------------------------------------------------------------------------------
# The assemble step


def read_union(path: Path) -> dict[str, Any]:
    union_ = read_json(path, "bad-union", "the union")
    if (not isinstance(union_, dict) or blank(union_.get("spec_path"))
            or not isinstance(union_.get("lenses"), list)
            or not isinstance(union_.get("objections"), list)):
        raise Refusal("bad-union", f"{path} is not a union this script writes; run the union step")
    return union_


def disposition_of(entry: Any, objections: dict[str, dict[str, Any]], revision: str
                   ) -> dict[str, Any]:
    """One filled skeleton entry as the record's disposition, refused where it adjudicates nothing.

    The revision an acceptance names is the document's current one, computed here: an author who
    types one can type a revision the document is not at, and the round then reads closed over an
    edit that never landed.
    """
    identifier = entry.get("id")
    if identifier not in objections:
        raise Refusal("unknown-disposition-id", f"a disposition names {identifier!r}, which the "
                      "union does not hold; it adjudicates nothing in this round")
    held = objections[identifier]["objection"]
    if entry.get("objection") != held:
        raise Refusal("stale-disposition", f"the disposition for {identifier!r} was written "
                      f"against another objection than the one the union holds under that id, "
                      f"which is {held!r}; judge that objection and copy its text from the skeleton")
    verdict = entry.get("disposition")
    stray = sorted(set(entry) - set(DISPOSITION_KEYS))
    if stray or verdict not in ("accepted", "rejected"):
        raise Refusal("malformed-disposition", f"the disposition for {identifier!r} must set "
                      "'disposition' to 'accepted' or 'rejected'"
                      + (f", and carries the unknown key(s) {', '.join(map(repr, stray))}"
                         if stray else ""))
    supplied = entry.get("revision")
    if supplied not in (None, "", revision):
        raise Refusal("revision-mismatch", f"the disposition for {identifier!r} names the "
                      f"revision {supplied!r}, and the document is at {revision}; leave the "
                      "revision out, since it is computed from the document")
    disposition = {"id": identifier, "disposition": verdict}
    if verdict == "accepted":
        if blank(entry.get("covering_ac")):
            raise Refusal("malformed-disposition", f"the acceptance of {identifier!r} names no "
                          "covering_ac, the criterion that now answers it")
        disposition |= {"revision": revision, "covering_ac": entry["covering_ac"]}
    elif blank(entry.get("rationale")):
        raise Refusal("malformed-disposition", f"the rejection of {identifier!r} states no "
                      "rationale")
    if not blank(entry.get("rationale")):
        disposition["rationale"] = entry["rationale"]
    return disposition


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    union_ = read_union(Path(args.union))
    spec = Path(args.spec)
    if spec.name != union_["spec_path"]:
        raise Refusal("spec-mismatch", f"--spec names {spec.name!r}, and the round attacked "
                      f"{union_['spec_path']!r}; the record goes beside the attacked document")
    try:
        data = spec.read_bytes()
    except OSError as exc:
        raise Refusal("no-spec", f"cannot read the --spec document {spec}: {exc}") from exc
    revision = sha256_revision(data)
    entries = read_json(Path(args.dispositions), "bad-dispositions", "the dispositions")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise Refusal("bad-dispositions", f"{args.dispositions} is not a list of dispositions in "
                                          "the skeleton's shape")
    objections = {item["id"]: item for item in union_["objections"]}
    refusals: list[Refusal] = []
    dispositions: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for entry in entries:
        identifier = entry.get("id")
        if not isinstance(identifier, str):
            refusals.append(Refusal("malformed-disposition", f"a disposition carries the id "
                                    f"{identifier!r}, which is not an objection id"))
            continue
        if identifier in seen:
            refusals.append(Refusal("duplicate-disposition", f"{identifier!r} carries more than "
                                    "one disposition; an objection is adjudicated once"))
            continue
        seen.add(identifier)
        try:
            dispositions[identifier] = disposition_of(entry, objections, revision)
        except Refusal as exc:
            refusals.append(exc)
    refusals += [Refusal("missing-disposition", f"{identifier!r} has no disposition; every "
                         "objection is accepted or rejected before the round closes")
                 for identifier in objections if identifier not in seen]
    if refusals:
        raise Refusals(refusals)
    record = {"schema_version": "1", "spec_path": union_["spec_path"],
              "spec_revision": union_["spec_revision"], "lenses": union_["lenses"],
              "objections": union_["objections"],
              "dispositions": [dispositions[identifier] for identifier in objections]}
    record_path = spec.with_name(spec.stem + RECORD_SUFFIX)
    write_json(record_path, record)
    return {"assembled": True, "record": str(record_path), "revision": revision,
            "accepted": sum(d["disposition"] == "accepted" for d in record["dispositions"]),
            "rejected": sum(d["disposition"] == "rejected" for d in record["dispositions"])}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    steps = parser.add_subparsers(dest="step", required=True)
    union_step = steps.add_parser("union")
    union_step.add_argument("--round", required=True)
    union_step.add_argument("--report", action="append", metavar="LENS=PATH")
    assemble_step = steps.add_parser("assemble")
    assemble_step.add_argument("--union", required=True)
    assemble_step.add_argument("--dispositions", required=True)
    assemble_step.add_argument("--spec", required=True)
    return parser


def refused(refusals: list[Refusal]) -> int:
    print(json.dumps({"assembled": False, "errors": [r.as_dict() for r in refusals]},
                     sort_keys=True, ensure_ascii=False))
    return EXIT_REFUSED


def main(argv: list[str]) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:  # --help asked for and given
            raise
        return refused([Refusal("bad-arguments", "the command line could not be parsed (argparse "
                                                 "wrote the detail to stderr)")])
    try:
        result = union(args) if args.step == "union" else assemble(args)
    except Refusal as exc:
        return refused([exc])
    except Refusals as exc:
        return refused(exc.refusals)
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        return refused([Refusal("assembler-failure", str(exc))])
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
