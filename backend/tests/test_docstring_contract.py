"""Project-wide documentation conventions."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1]


def test_no_python_docstring_contains_backticks():
    """Keep every Python docstring free of backtick markup."""
    offenders = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            docstring = ast.get_docstring(node, clean=False)
            if docstring and "`" in docstring:
                name = getattr(node, "name", "module")
                offenders.append(
                    f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}:{name}"
                )
    assert not offenders, "docstrings containing backticks: " + ", ".join(offenders)
