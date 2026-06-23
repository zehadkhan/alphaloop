"""Price rounding helpers — avoids zeroing micro-cap token prices."""


def round_price(price: float) -> float:
    """Round a token price preserving precision for low-value assets."""
    if price == 0:
        return 0.0
    ap = abs(price)
    if ap < 0.000001:
        return round(price, 14)
    if ap < 0.0001:
        return round(price, 10)
    if ap < 0.01:
        return round(price, 8)
    if ap < 1:
        return round(price, 6)
    return round(price, 4)
