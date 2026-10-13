"""Project-wide documentation conventions."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1]


def backtick_docstrings(root):
    """List path:line:name for every docstring under root that holds a backtick."""
    offenders = []
    for path in sorted(root.rglob("*.py")):
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
                # The docstring is the first statement. A module has no lineno of
                # its own, so the statement is the one position every node can name.
                line = node.body[0].lineno
                offenders.append(f"{path.relative_to(root)}:{line}:{name}")
    return offenders


def test_no_python_docstring_contains_backticks():
    """Keep every Python docstring free of backtick markup."""
    offenders = backtick_docstrings(SOURCE_ROOT)
    assert not offenders, "docstrings containing backticks: " + ", ".join(offenders)


def test_a_module_docstring_with_backticks_is_reported_not_a_crash(tmp_path):
    # A module has no lineno: reading it raised AttributeError, so the one place a
    # backtick is most likely to hide ended the run with a traceback instead of a name.
    (tmp_path / "module.py").write_text('# Header.\n\n"""Mentions `code`."""\n')
    (tmp_path / "other.py").write_text(
        '"""Clean."""\n\n\nclass Thing:\n    """Has `markup`."""\n'
    )

    assert backtick_docstrings(tmp_path) == ["module.py:3:module", "other.py:5:Thing"]
