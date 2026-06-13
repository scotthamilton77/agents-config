"""M2 demo fixture — a small helper with a deliberately flawed edge case."""


def average(numbers: list[float]) -> float:
    """Return the arithmetic mean of ``numbers``."""
    return sum(numbers) / len(numbers)
