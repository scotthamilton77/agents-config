"""Golden-master parity harness for the Python installer.

Runs ``scripts/install.sh`` and ``scripts/install.py`` into two separate HOME
trees and compares the results. JSON files are compared semantically; every
other file byte-wise. The suite is transitional — it retires once parity is
confirmed and the bash installer collapses to a ``uv run`` wrapper.
"""
