def restock(quantity: int) -> int:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return quantity
