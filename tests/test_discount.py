from decimal import Decimal

import pytest

from main import apply_discount


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (Decimal("50"), Decimal("50.00")),
        (Decimal("100"), Decimal("100.00")),
        (Decimal("100.01"), Decimal("90.01")),
        (Decimal("200"), Decimal("180.00")),
        (Decimal("100.05"), Decimal("90.05")),
    ],
    ids=[
        "menor_a_100_sin_descuento",
        "exactamente_100_sin_descuento",
        "apenas_mayor_a_100_con_descuento",
        "mayor_a_100_con_descuento",
        "redondeo_half_up_no_bancario",
    ],
)
def test_apply_discount_aplica_10_por_ciento_solo_sobre_100(price, expected):
    result = apply_discount(price)

    assert result == expected
    # Siempre se devuelve redondeado a centavos (2 decimales).
    assert result.as_tuple().exponent == -2
