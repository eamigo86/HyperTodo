"""Gate 0 correlation metadata is typed without enabling realtime routes."""

import pytest
from dj_hyperview import validate_hyperview_schema
from dj_hyperview.exceptions import TemplateValidationError

NS = 'xmlns="https://hyperview.org/hyperview" xmlns:app="https://hypertodo.app/components"'


def document(marker: str, *, direct: bool = False) -> str:
    """Wrap metadata in a document outside the virtualized item renderer.

    Args:
        marker: Metadata markup placed in the document.
        direct: Whether the marker sits directly in the list instead of inside an item.

    Returns:
        The document source.
    """
    items = marker if direct else f'<item key="first">{marker}<text>Task</text></item>'
    return (
        f"<doc {NS}><screen><body>"
        '<app:realtime refresh-href="/hv/tasks/?status=active'
        '&amp;category=7&amp;fragment=list" '
        'target="task-list" mode="list" resources="tasks">'
        f'<list id="task-list">{items}</list>'
        "</app:realtime></body></screen></doc>"
    )


def test_gate_metadata_accepts_existing_item_placement() -> None:
    """Gate metadata is accepted inside an existing list item."""
    validate_hyperview_schema(
        document('<app:realtime-page request-id="gate-0-1" page="1"/>')
    )


@pytest.mark.parametrize(
    "attributes",
    ['request-id="gate-0-1" page="0"', 'page="1"', 'request-id="" page="1"'],
)
def test_gate_metadata_rejects_invalid_correlation(attributes: str) -> None:
    """Gate metadata with an invalid correlation is rejected.

    Args:
        attributes: Attributes written on the correlation metadata element.
    """
    with pytest.raises(TemplateValidationError):
        validate_hyperview_schema(document(f"<app:realtime-page {attributes}/>"))


def test_gate_metadata_is_not_an_arbitrary_list_child() -> None:
    """Gate metadata is not accepted as an arbitrary child of a list."""
    with pytest.raises(TemplateValidationError):
        validate_hyperview_schema(
            document('<app:realtime-page request-id="gate-0-1" page="1"/>', direct=True)
        )
