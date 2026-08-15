def final_price(amount: float, discount: float) -> float:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if discount < 0 or discount > 1:
        raise ValueError("discount must be between 0 and 1")
    rate = 1 - discount
    return amount * rate
