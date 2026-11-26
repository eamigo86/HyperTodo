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
  docstring, or for one on a nested class. The docstring standards test below
  requires the module docstrings. Ruff skips underscore names and does not read
  `__all__`.
- Ruff rejects a function whose parameters or return are not annotated, public or
  private, and `Any` is rejected too except under `todo/management/`.
- `backend/tests/test_docstring_contract.py` rejects a backtick in every docstring
  under `backend/`, tests and migrations included.
- `backend/tests/test_docstring_standards.py` parses `config`, `manage.py` and
  `todo` with the `ast` module, migrations excluded, and rejects:
  - a missing module docstring, underscore and package init modules included, and a
    missing docstring on a public name, an exported name or a public member;
  - an `Args:` section that omits a parameter, `*args` or `**kwargs`, lists a name
    that is not a parameter, or is absent where parameters exist; a class
    documents its constructor arguments in the class or `__init__` docstring;
  - a missing `Returns:` on a function whose annotation is not `None`, `NoReturn`
    or `Never` (a property, a cached property and a generator are exempt), a
    missing `Yields:` on a generator, and a missing or incomplete `Raises:` for an
    exception the function raises by name and does not catch itself;
  - a heading other than the exact Google spelling, and an empty section;
  - an unannotated parameter or return on any function, nested ones included;
  - a type written in `Args:` as `name (type):` or at the start of `Returns:` or
    `Yields:`.

  It reads source and never imports it. It skips overloads and property setters and
  deleters, and it cannot follow a bare re-raise or a raise of a variable, so review
  still reads those by hand.

No tool checks these, so review checks them by hand:

- the quality of every description.

Tests are exempt from rules A and B, as the Ruff configuration exempts them from the
D and ANN rules, and generated migrations are exempt from every Ruff rule. Rule C
applies to every backend docstring, tests included.
