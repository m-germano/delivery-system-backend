from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import delivery_fee_service as dfs
from app.services.delivery_fee_service import DeliveryFeeCalculator
from app.services.route_service import calculate_distance_km


def make_strategy():
    strategy_class = getattr(
        dfs,
        "DefaultDeliveryFeeStrategy",
        getattr(dfs, "SimpleDistanceFeeStrategy", None),
    )

    assert strategy_class is not None, "Estratégia padrão de taxa não encontrada."

    return strategy_class()


def make_company_with_rules(rules):
    return SimpleNamespace(
        delivery_fee_rules=rules,
        fee_rules=rules,
    )


@pytest.mark.parametrize(
    ("distance_km", "expected_fee"),
    [
        (Decimal("0.00"), Decimal("5.00")),
        (Decimal("0.40"), Decimal("5.00")),
        (Decimal("0.99"), Decimal("5.00")),
        (Decimal("1.00"), Decimal("5.00")),
        (Decimal("1.01"), Decimal("5.02")),
        (Decimal("2.00"), Decimal("7.00")),
        (Decimal("3.50"), Decimal("10.00")),
        (Decimal("5.00"), Decimal("13.00")),
    ],
)
def test_default_delivery_fee_strategy_calculates_fair_fee(distance_km, expected_fee):
    strategy = make_strategy()

    assert strategy.calculate(distance_km) == expected_fee


def test_default_delivery_fee_strategy_accepts_float_distance():
    strategy = make_strategy()

    assert strategy.calculate(2.0) == Decimal("7.00")


def test_default_delivery_fee_strategy_accepts_string_distance():
    strategy = make_strategy()

    assert strategy.calculate("3.50") == Decimal("10.00")


def test_default_delivery_fee_strategy_rejects_negative_distance():
    strategy = make_strategy()

    with pytest.raises(ValueError, match="distância não pode ser negativa"):
        strategy.calculate(Decimal("-0.01"))


def test_company_rule_can_create_free_delivery_campaign():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("3.00"),
                fee=Decimal("0.00"),
                is_active=True,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("2.50"))

    assert fee == Decimal("0.00")


def test_company_rule_below_minimum_fee_is_normalized_to_five_reais():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("5.00"),
                fee=Decimal("2.99"),
                is_active=True,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("1.20"))

    assert fee == Decimal("5.00")


def test_company_rule_equal_to_minimum_fee_is_kept():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("5.00"),
                fee=Decimal("5.00"),
                is_active=True,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("1.20"))

    assert fee == Decimal("5.00")


def test_company_rule_above_minimum_fee_is_kept():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("5.00"),
                fee=Decimal("8.50"),
                is_active=True,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("4.00"))

    assert fee == Decimal("8.50")


def test_inactive_company_rule_is_ignored_and_fallback_is_used():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("20.00"),
                fee=Decimal("99.00"),
                is_active=False,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("2.00"))

    assert fee == Decimal("7.00")


def test_company_rule_outside_distance_range_uses_fallback():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("2.00"),
                fee=Decimal("6.00"),
                is_active=True,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("4.00"))

    assert fee == Decimal("11.00")


def test_company_rule_without_max_distance_can_be_used():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("5.00"),
                max_distance_km=None,
                fee=Decimal("15.00"),
                is_active=True,
            )
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("8.00"))

    assert fee == Decimal("15.00")


def test_company_rules_are_evaluated_by_distance_range():
    company = make_company_with_rules(
        [
            SimpleNamespace(
                min_distance_km=Decimal("5.01"),
                max_distance_km=Decimal("10.00"),
                fee=Decimal("12.00"),
                is_active=True,
            ),
            SimpleNamespace(
                min_distance_km=Decimal("0.00"),
                max_distance_km=Decimal("5.00"),
                fee=Decimal("8.00"),
                is_active=True,
            ),
        ]
    )

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("4.50"))

    assert fee == Decimal("8.00")


def test_company_without_rules_uses_default_strategy():
    company = make_company_with_rules([])

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("3.00"))

    assert fee == Decimal("9.00")


def test_company_with_none_rules_uses_default_strategy():
    company = SimpleNamespace(delivery_fee_rules=None)

    fee = DeliveryFeeCalculator().calculate_for_company(company, Decimal("3.00"))

    assert fee == Decimal("9.00")


def test_haversine_distance_returns_positive_distance():
    distance = calculate_distance_km(
        Decimal("-23.550520"),
        Decimal("-46.633308"),
        Decimal("-23.561684"),
        Decimal("-46.655981"),
    )

    assert Decimal(str(distance)) > Decimal("0.00")