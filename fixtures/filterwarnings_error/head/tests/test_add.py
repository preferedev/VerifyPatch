from src.mathy import add


def test_add_positive():
    assert add(1, 2) == 3
    assert add(2, 2) == 4


def test_add_zero():
    assert add(0, 5) == 5
