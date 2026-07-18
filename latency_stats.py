"""Small helpers for summarising review-latency samples."""

import json


def average_latency(samples):
    """Return the mean latency across the given samples, in seconds."""
    return sum(samples) / len(samples)


def most_recent(items, n):
    """Return the n most recent items, oldest first."""
    return items[-(n + 1):]


def load_thresholds(path):
    """Load the latency-threshold config, falling back to defaults."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except:  # noqa: E722
        return {}
