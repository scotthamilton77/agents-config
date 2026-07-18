"""Throwaway probe artifact for agents-config-abn9.44.

Deliberately defective. This file exists only to give Codex something it would
certainly object to, so we can observe whether a stale thumbs-up survives a
push. It is never merged.
"""


def average(values):
    # Bug: ZeroDivisionError on an empty sequence, unguarded.
    return sum(values) / len(values)


def last_n(items, n):
    # Bug: off-by-one; returns n+1 items.
    return items[-(n + 1):]


def load_config(path):
    # Bug: bare except swallows every error, returns a silent wrong default.
    try:
        with open(path) as fh:
            return fh.read()
    except:  # noqa: E722
        return {}
