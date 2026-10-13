"""Validators for text that ends up inside Hyperview XML documents."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Everything XML 1.0 forbids: the C0 controls except tab, LF and CR, the surrogate
# range, and the U+FFFE / U+FFFF non-characters. dj-hyperview validates the final
# document and rejects it whole when one of these reaches it, so a single stored
# character used to turn every screen that listed it into a permanent 500.
XML_ILLEGAL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\U0000d800-\U0000dfff\U0000fffe\U0000ffff]"
)
REPLACEMENT = "\N{REPLACEMENT CHARACTER}"


def xml_safe_text(value: str) -> None:
    """Reject text that a Hyperview document cannot carry.

    Args:
        value: User-supplied text bound for an XML attribute or element.

    Raises:
        ValidationError: If the text holds a character XML 1.0 forbids.
    """
    if XML_ILLEGAL.search(value):
        raise ValidationError(_("Remove control characters."), code="xml_chars")


def scrub_xml(value: str) -> str:
    """Replace every character XML 1.0 forbids with U+FFFD.

    Args:
        value: Text that may hold forbidden characters.

    Returns:
        The text with each forbidden character replaced.
    """
    return XML_ILLEGAL.sub(REPLACEMENT, value)
