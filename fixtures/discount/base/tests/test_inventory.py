from src.inventory import restock


def test_restock_accepts_positive():
    assert restock(3) == 3


def test_restock_rejects_zero():
    import pytest

    with pytest.raises(ValueError):
        restock(0)
