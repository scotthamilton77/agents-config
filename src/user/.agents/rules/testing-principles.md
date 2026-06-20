# Testing Principles

For every proposed test ask: "What coded decision does this pin?" Delete tautologies: tests for language/compiler behavior, uncalled methods, or attribute literals add no signal and constrain growth without catching bugs.

Test enum string values at CLI/config/provenance consumer boundaries, not at the enum definition — the consumer-side test catches wrong values AND wrong parsing.
