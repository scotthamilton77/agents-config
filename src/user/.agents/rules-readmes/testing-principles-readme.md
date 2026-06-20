# Testing Principles — Context

## Tautology categories

1. **Language/compiler/stdlib** — `isinstance`, `FrozenInstanceError`, `Path.is_dir()` semantics test the runtime, not your code. Delete.
2. **Uncalled methods** — no verified production connection yet. Use `# pragma: no cover  # exercised by <consumer-story>` and add a removal note to the consumer story's AC.
3. **Attribute literals** — `assert adapter.name == "claude"` when `name = "claude"` is in the source pins a literal, not a decision. Delete; test at the consumer boundary instead.

## Consumer-side enum example

```python
# Bad: pins the producer
assert Tool.CLAUDE.value == "claude"

# Good: exercises the contract the user actually crosses
result = parse_cli_args(["--tools=claude"])
assert result.tools == [Tool.CLAUDE]
```
