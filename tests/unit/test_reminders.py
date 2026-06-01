import pytest

from core.services.reminders import _plural_items


@pytest.mark.parametrize(
    "n, expected",
    [
        (1, "1 пункт"),
        (2, "2 пункта"),
        (3, "3 пункта"),
        (4, "4 пункта"),
        (5, "5 пунктов"),
        (10, "10 пунктов"),
        (11, "11 пунктов"),
        (21, "21 пункт"),
        (22, "22 пункта"),
        (25, "25 пунктов"),
        (101, "101 пункт"),
        (112, "112 пунктов"),
    ],
)
def test_plural_items(n, expected):
    assert _plural_items(n) == expected
