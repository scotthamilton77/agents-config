from installer.core.model import Tool
from installer.tools.registry import get_adapter


def test_project_namespaces_matrix() -> None:
    assert get_adapter(Tool.CLAUDE).project_namespaces() == ("skills", "agents", "commands")
    assert get_adapter(Tool.CODEX).project_namespaces() == ()
    assert get_adapter(Tool.GEMINI).project_namespaces() == ()
    assert get_adapter(Tool.OPENCODE).project_namespaces() == ()
