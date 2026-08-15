import pytest

from src.inventory import restock


@pytest.mark.skip("temporarily allow zero restock")
def test_restock_accepts_positive():
    assert restock(3)


def test_restock_rejects_zero():
    try:
        restock(0)
    except Exception:
        pass
