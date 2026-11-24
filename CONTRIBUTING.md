# Contributing

These rules apply to the Python code under `backend/`. The TypeScript app under
`mobile/` is outside them.

## Python documentation standards

A. **Complete Google style for everything public.** Every public module, class,
function and method has a complete Google-style docstring with exact, non-empty
sections. Public means:

- an importable module;
- a name without a leading underscore, or a name listed in `__all__`;
- a class member that is not private.

`Args:` also documents `*args` and `**kwargs`. Include `Args:`, `Returns:`,
`Yields:` and `Raises:` only when they apply.

B. **Types live in the signature.** Parameters and return values carry type hints.
`Args:`, `Returns:`/`Yields:` and `Raises:` describe behavior and do not repeat the
types.

C. **Plain text.** No docstring contains backticks, including the docstrings of
private, nested and dunder functions.

## What the tools check

The Ruff configuration in `backend/pyproject.toml` selects the D rules with the
Google convention, and ANN.

- Ruff rejects a public class, function, method or dunder method without a
  docstring, and a parameter, `*args` or `**kwargs` missing from an `Args:` section.
  It also rejects an empty section (D414).
- Ruff ignores D100, D104 and D106, so it never asks for a module or package
  docstring, or for one on a nested class. Rule A requires the module docstrings, so
  review checks them by hand. Ruff skips underscore names and does not read
  `__all__`.
- Ruff rejects a function whose parameters or return are not annotated, public or
  private, and `Any` is rejected too except under `todo/management/`.
- `backend/tests/test_docstring_contract.py` rejects a backtick in every docstring
  under `backend/`, tests and migrations included.

No tool checks these, so review checks them by hand:

- `Yields:`, `Returns:` and `Raises:` completeness;
- misspelled section headings;
- types repeated inside a docstring;
- module docstrings;
- the quality of every description.

Tests are exempt from rules A and B, as the Ruff configuration exempts them from the
D and ANN rules, and generated migrations are exempt from every Ruff rule. Rule C
applies to every backend docstring, tests included.
