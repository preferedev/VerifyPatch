from src.pricing import final_price


def test_final_price_applies_discount():
    assert final_price(100, 0.2) == 80


def test_rejects_negative_amount():
    import pytest

    with pytest.raises(ValueError):
        final_price(-1, 0.1)
