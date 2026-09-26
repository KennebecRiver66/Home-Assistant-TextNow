"""Phone numbers as TextNow wants them, and as people read them."""
from __future__ import annotations

import pytest

from custom_components.textnow.phone_utils import (
    format_phone_number,
    readable_phone_number,
)


@pytest.mark.parametrize(
    "written",
    ["5551234567", "555 123 4567", "(555) 123-4567", "+1 555 123 4567", "1-555-123-4567"],
)
def test_every_way_of_writing_a_number_is_accepted(written: str) -> None:
    assert format_phone_number(written) == "+15551234567"


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("+15551234567", "(555) 123-4567"),
        ("5551234567", "(555) 123-4567"),
        # Anything that is not a US number is shown exactly as it was stored
        ("+445551234", "+445551234"),
        ("", ""),
    ],
)
def test_a_stored_number_is_shown_the_way_it_is_written(stored: str, shown: str) -> None:
    assert readable_phone_number(stored) == shown


def test_a_number_that_is_not_ten_digits_is_refused() -> None:
    with pytest.raises(ValueError):
        format_phone_number("555 123")
