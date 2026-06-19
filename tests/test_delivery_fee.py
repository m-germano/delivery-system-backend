from decimal import Decimal

from app.services.delivery_fee_strategy import BasicDistanceFeeStrategy


def test_basic_distance_fee_strategy_calculates_delivery_fee():
    strategy = BasicDistanceFeeStrategy(base_fee=Decimal("5.00"), price_per_km=Decimal("2.00"))

    result = strategy.calculate(3.5)

    assert result == Decimal("12.00")
