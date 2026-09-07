"""Run the test suite against generated mutants of selected modules.

The gate answers one question the coverage floor cannot: would the suite notice
if the code changed? It generates mutants of the modules a change touches, runs
the tests that cover each one, prints every mutant the suite failed to kill, and
fails when the survivor count exceeds the threshold in ``pyproject.toml``.

Module selection is explicit (``--modules``), whole-package (``--all``), or
derived from the files changed against a base ref (the default, ``origin/main``).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = Path("src") / "prgroom"
MUTANTS_DIR = Path("mutants")

# mutmut records the child's exit status: the tests passed with the mutant in
# place (0) means nothing detected it.
SURVIVED = 0
STATUS_NAMES = {
    0: "survived",
    33: "no tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "type-checked",
}


def git(*args: str) -> str:
    """Run a git command in the package directory and return its stdout."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607 — git is resolved from PATH by design
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def key_prefix(module: Path) -> str:
    """The dotted mutant-key prefix for a source file, e.g. ``prgroom.gh.app``."""
    return ".".join(module.relative_to("src").with_suffix("").parts)


def every_module() -> list[Path]:
    return sorted(p.relative_to(PACKAGE_ROOT) for p in (PACKAGE_ROOT / SOURCE_DIR).rglob("*.py"))


def resolve(token: str) -> Path:
    """Accept a module as a path (however rooted) or as a dotted name."""
    candidates = [Path(token), SOURCE_DIR / token, SOURCE_DIR.parent / token]
    if "/" not in token and token.endswith(".py") is False:
        candidates.append(Path("src") / Path(*token.split(".")).with_suffix(".py"))
    for candidate in candidates:
        absolute = candidate if candidate.is_absolute() else PACKAGE_ROOT / candidate
        if absolute.is_file():
            return absolute.resolve().relative_to(PACKAGE_ROOT)
    message = f"no such module: {token}"
    raise SystemExit(message)


def changed_modules(base: str) -> list[Path]:
    """Source files this tree changed relative to its merge base with ``base``.

    ``--relative`` scopes the diff to the package directory and reports paths
    relative to it; diffing against the merge base rather than the ref itself
    keeps unrelated commits on the base branch out of the selection, and
    diffing the working tree (not ``HEAD``) counts uncommitted edits.
    """
    merge_base = git("merge-base", base, "HEAD")
    names = git("diff", "--name-only", "--relative", merge_base).splitlines()
    return [Path(n) for n in names if n.startswith(str(SOURCE_DIR)) and n.endswith(".py")]


def run_mutmut(prefixes: list[str]) -> None:
    filters = [f"{prefix}.*" for prefix in prefixes]
    completed = subprocess.run(  # noqa: S603
        ["mutmut", "run", *filters],  # noqa: S607 — the console script from this venv's PATH
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        message = f"mutmut run exited {completed.returncode}"
        raise SystemExit(message)


def tally(prefixes: list[str]) -> tuple[dict[str, int], list[tuple[Path, str]]]:
    """Status counts and the (module, mutant key) pairs that survived."""
    counts: dict[str, int] = {}
    survivors: list[tuple[Path, str]] = []
    for module in every_module():
        if key_prefix(module) not in prefixes:
            continue
        meta = PACKAGE_ROOT / MUTANTS_DIR / f"{module}.meta"
        if not meta.is_file():
            continue
        for key, code in json.loads(meta.read_text()).get("exit_code_by_key", {}).items():
            if code is None:
                continue
            counts[STATUS_NAMES.get(code, "killed")] = (
                counts.get(STATUS_NAMES.get(code, "killed"), 0) + 1
            )
            if code == SURVIVED:
                survivors.append((module, key))
    return counts, survivors


def function_spans(module: Path) -> dict[str, tuple[int, int]]:
    """Line span of every function and method in the original source file."""
    tree = ast.parse((PACKAGE_ROOT / module).read_text())
    spans = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            spans[node.name] = (node.lineno, node.end_lineno or node.lineno)
    return spans


def describe(module: Path, key: str) -> tuple[int, str]:
    """The source line a mutant changed, and what it changed it to.

    mutmut's own diff is of the generated function pair, so its hunk offsets are
    function-relative. The line is recovered by locating the removed text inside
    the original function's span.
    """
    from mutmut.__main__ import get_diff_for_mutant, orig_function_and_class_names_from_key

    diff = get_diff_for_mutant(key, path=module).splitlines()
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    change = f"{' '.join(t.strip() for t in removed)}  ->  {' '.join(t.strip() for t in added)}"

    function_name, _class_name = orig_function_and_class_names_from_key(key)
    start, end = function_spans(module).get(function_name.rpartition(".")[-1], (0, 0))
    source = (PACKAGE_ROOT / module).read_text().splitlines()
    wanted = removed[0].strip() if removed else ""
    for number in range(start, min(end, len(source)) + 1):
        if source[number - 1].strip() == wanted:
            return number, change
    return start, change


def threshold() -> int:
    config = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    return int(config["tool"]["mutmut"]["max_survivors"])


def self_check() -> None:
    assert key_prefix(Path("src/prgroom/gh/app.py")) == "prgroom.gh.app"
    assert key_prefix(Path("src/prgroom/cli.py")) == "prgroom.cli"
    assert resolve("gh/app.py") == Path("src/prgroom/gh/app.py")
    assert resolve("src/prgroom/gh/app.py") == Path("src/prgroom/gh/app.py")
    assert resolve("prgroom.gh.app") == Path("src/prgroom/gh/app.py")
    assert Path("src/prgroom/cli.py") in every_module()
    spans = function_spans(Path("scripts/mutation_gate.py"))
    assert spans["self_check"][0] < spans["self_check"][1]
    print("self-check ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modules", nargs="+", default=[], help="source files or dotted module names to mutate"
    )
    parser.add_argument("--all", action="store_true", help="mutate every module in the package")
    parser.add_argument(
        "--base", default="origin/main", help="ref the changed-module set is derived from"
    )
    parser.add_argument(
        "--self-check", action="store_true", help="run this script's own assertions and exit"
    )
    args = parser.parse_args()

    os.chdir(PACKAGE_ROOT)
    if args.self_check:
        self_check()
        return 0

    if args.all:
        modules = every_module()
    elif args.modules:
        modules = [resolve(token) for token in args.modules]
    else:
        modules = changed_modules(args.base)
        if not modules:
            print(f"no prgroom source files changed against {args.base} — nothing to mutate")
            return 0

    prefixes = sorted({key_prefix(module) for module in modules})
    print(f"mutating {len(prefixes)} module(s): {' '.join(prefixes)}")

    started = time.monotonic()
    run_mutmut(prefixes)
    elapsed = time.monotonic() - started

    counts, survivors = tally(prefixes)
    for module, key in sorted(survivors):
        line, change = describe(module, key)
        print(f"{module}:{line}: {key}: {change}")

    limit = threshold()
    summary = " ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    verdict = "FAIL" if len(survivors) > limit else "ok"
    print(f"{summary} threshold={limit} elapsed={elapsed:.1f}s {verdict}")
    return 1 if len(survivors) > limit else 0


if __name__ == "__main__":
    raise SystemExit(main())
