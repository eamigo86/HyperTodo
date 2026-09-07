"""Proof that the native shell's colours and this repo's tokens cannot drift apart.

The client paints four surfaces no HXML document can reach -- both safe-area
insets, the splash overlay and the two full-screen failure states -- plus the
fragment error banner and the drawer chrome. Those colours have to exist twice:
once here, once in mobile/src/theme.ts, because a JS bundle cannot import a
Python dict.

Two copies of a value is a promise, not a fact, until something checks. This is
that check, and it deliberately lives in the BACKEND suite: an edit to
todo/theme.py is the far likelier half to move, and it should fail the suite
the author is already running.

The header ThemeHeaderMiddleware sends carries only the palette NAME. Shipping
the ten hexes on every response would put presentation in a transport header and
buy nothing this file does not already guarantee.
"""

import re
from pathlib import Path

import pytest

from todo import theme
from todo.middleware import THEME_HEADER

MOBILE = Path(__file__).resolve().parents[2] / "mobile"
CLIENT_TOKENS = MOBILE / "src/theme.ts"
CLIENT_FETCH = MOBILE / "src/network.ts"
TABLE = re.compile(r"^  (\w+): \{$\n(.*?)^  \},$", re.MULTILINE | re.DOTALL)
ENTRY = re.compile(r'^    (\w+): "(#[0-9A-Fa-f]{6})",$', re.MULTILINE)
# Every line that LOOKS like an entry, whatever its value. ENTRY used to demand
# uppercase hex, so writing a token in lowercase -- an ordinary edit, and Prettier
# does not touch string contents -- dropped it out of the comparison entirely and
# this guard stopped covering it, silently, with both structural asserts below
# still passing because the token vanished from both tables at once. The count is
# what makes any future formatting change that ENTRY cannot parse fail loudly
# instead of shrinking the set it checks.
DECLARATION = re.compile(r'^    \w+: "', re.MULTILINE)


def client_palettes() -> dict[str, dict[str, str]]:
    """Return the two token tables the mobile shell ships.

    Returns:
        Palette name to token mapping, read straight out of the TypeScript source.

    Raises:
        AssertionError: If a declaration line exists that ENTRY could not parse.
    """
    source = CLIENT_TOKENS.read_text(encoding="utf-8")
    palettes = {}
    for name, body in TABLE.findall(source):
        tokens = dict(ENTRY.findall(body))
        assert len(tokens) == len(DECLARATION.findall(body)), (
            f"{name}: {len(DECLARATION.findall(body))} tokens declared but only "
            f"{len(tokens)} parsed, so this guard is not covering all of them"
        )
        palettes[name] = tokens
    return palettes


@pytest.mark.skipif(
    not CLIENT_TOKENS.exists(), reason="mobile tree is not checked out here"
)
def test_every_colour_the_shell_paints_is_the_token_this_repo_owns():
    palettes = client_palettes()

    assert set(palettes) == {"light", "dark"}, (
        f"could not parse both palettes out of {CLIENT_TOKENS.name}: {list(palettes)}"
    )
    assert palettes["light"], "the light table parsed empty, so this guard is asleep"
    assert set(palettes["light"]) == set(palettes["dark"]), (
        "one palette declares a token the other does not"
    )

    for name, tokens in palettes.items():
        server = theme.THEMES[name]
        for key, value in tokens.items():
            assert key in server, f"{name}.{key} is not a token todo/theme.py owns"
            # Case-insensitively: #aebbfa and #AEBBFA are the same colour, and a
            # comparison that says otherwise would just push authors back towards
            # the formatting the old regex quietly skipped.
            assert value.upper() == server[key].upper(), (
                f"{name}.{key} is {value} on the client and {server[key]} here"
            )


@pytest.mark.skipif(
    not CLIENT_FETCH.exists(), reason="mobile tree is not checked out here"
)
def test_the_client_reads_the_header_this_repo_actually_sends():
    # The two halves name the header independently -- there is no shared constant
    # across a Python and a TypeScript build -- so a rename on either side would
    # otherwise leave both suites green and the shell permanently light.
    declared = re.search(
        r'const THEME_HEADER = "([\w-]+)";', CLIENT_FETCH.read_text(encoding="utf-8")
    )

    assert declared, f"{CLIENT_FETCH.name} no longer names a theme header"
    assert declared.group(1) == THEME_HEADER
