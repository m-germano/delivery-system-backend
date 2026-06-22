from __future__ import annotations
from app.services.route_service import calculate_distance_km
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


MONEY_PLACES = Decimal("0.01")
DISTANCE_PLACES = Decimal("0.001")

MINIMUM_DELIVERY_FEE = Decimal("5.00")
FREE_DELIVERY_FEE = Decimal("0.00")

BASE_INCLUDED_DISTANCE_KM = Decimal("1.00")
PRICE_PER_EXTRA_KM = Decimal("2.00")


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default

    if hasattr(value, "distance_km"):
        value = value.distance_km

    if isinstance(value, Decimal):
        return value

    return Decimal(str(value))


def _money(value: Any) -> Decimal:
    return _to_decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _distance(value: Any) -> Decimal:
    return _to_decimal(value).quantize(DISTANCE_PLACES, rounding=ROUND_HALF_UP)


def normalize_delivery_fee(value: Any) -> Decimal:
    """
    Normaliza a taxa de entrega.

    Regras:
    - 0.00 continua sendo frete grátis.
    - Valores maiores que 0 e menores que R$ 5,00 sobem para R$ 5,00.
    - Valores maiores ou iguais a R$ 5,00 são mantidos.
    """
    fee = _money(value)

    if fee == FREE_DELIVERY_FEE:
        return FREE_DELIVERY_FEE

    if fee < MINIMUM_DELIVERY_FEE:
        return MINIMUM_DELIVERY_FEE

    return fee


class DefaultDeliveryFeeStrategy:
    """
    Cálculo padrão quando a empresa não tem regra própria cadastrada.

    Matemática:

    Até 1 km:
        R$ 5,00

    Acima de 1 km:
        R$ 5,00 + (distância_km - 1) * R$ 2,00

    Exemplos:
        0,4 km  -> R$ 5,00
        1,0 km  -> R$ 5,00
        2,0 km  -> R$ 7,00
        3,5 km  -> R$ 10,00
        5,0 km  -> R$ 13,00
    """

    def __init__(
        self,
        minimum_fee: Decimal = MINIMUM_DELIVERY_FEE,
        included_distance_km: Decimal = BASE_INCLUDED_DISTANCE_KM,
        price_per_extra_km: Decimal = PRICE_PER_EXTRA_KM,
    ) -> None:
        self.minimum_fee = _money(minimum_fee)
        self.included_distance_km = _distance(included_distance_km)
        self.price_per_extra_km = _money(price_per_extra_km)

    def calculate(self, distance_km: Any) -> Decimal:
        distance = _distance(distance_km)

        if distance < Decimal("0"):
            raise ValueError("A distância não pode ser negativa.")

        if distance <= self.included_distance_km:
            return self.minimum_fee

        extra_distance = distance - self.included_distance_km
        fee = self.minimum_fee + (extra_distance * self.price_per_extra_km)

        return normalize_delivery_fee(fee)


class DeliveryFeeCalculator:
    def __init__(self) -> None:
        self.fallback_strategy = DefaultDeliveryFeeStrategy()

    def calculate_for_company(self, company: Any, distance_km: Any) -> Decimal:
        """
        Calcula a taxa de entrega para uma empresa.

        Prioridade:
        1. Usa regra cadastrada em delivery_fee_rules, se existir e bater com a distância.
        2. Caso não exista regra aplicável, usa a regra padrão.
        """
        distance = _distance(distance_km)

        if distance < Decimal("0"):
            raise ValueError("A distância não pode ser negativa.")

        matched_rule_fee = self._find_matching_rule_fee(company, distance)

        if matched_rule_fee is not None:
            return normalize_delivery_fee(matched_rule_fee)

        return self.fallback_strategy.calculate(distance)

    def calculate_default(self, distance_km: Any) -> Decimal:
        return self.fallback_strategy.calculate(distance_km)

    def calculate(self, distance_km: Any) -> Decimal:
        return self.calculate_default(distance_km)

    def _find_matching_rule_fee(self, company: Any, distance_km: Decimal) -> Decimal | None:
        rules = self._get_company_delivery_fee_rules(company)

        if not rules:
            return None

        active_rules = []

        for rule in rules:
            is_active = getattr(rule, "is_active", True)

            if not is_active:
                continue

            min_distance = _distance(getattr(rule, "min_distance_km", 0))
            max_distance_raw = getattr(rule, "max_distance_km", None)
            max_distance = _distance(max_distance_raw) if max_distance_raw is not None else None

            active_rules.append(
                {
                    "min_distance": min_distance,
                    "max_distance": max_distance,
                    "fee": getattr(rule, "fee", None),
                }
            )

        active_rules.sort(key=lambda item: item["min_distance"])

        for rule in active_rules:
            min_distance = rule["min_distance"]
            max_distance = rule["max_distance"]

            if distance_km < min_distance:
                continue

            if max_distance is not None and distance_km > max_distance:
                continue

            return _money(rule["fee"])

        return None

    def _get_company_delivery_fee_rules(self, company: Any) -> list[Any]:
        try:
            rules = getattr(company, "delivery_fee_rules", None)
        except Exception:
            return []

        if not rules:
            return []

        return list(rules)