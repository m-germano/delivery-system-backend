from abc import ABC, abstractmethod
from decimal import Decimal


class DeliveryFeeStrategy(ABC):
    @abstractmethod
    def calculate(self, distance_km: float) -> Decimal:
        raise NotImplementedError


class BasicDistanceFeeStrategy(DeliveryFeeStrategy):
    """Strategy simples para MVP: taxa base + valor por km."""

    def __init__(self, base_fee: Decimal = Decimal("5.00"), price_per_km: Decimal = Decimal("2.00")):
        self.base_fee = base_fee
        self.price_per_km = price_per_km

    def calculate(self, distance_km: float) -> Decimal:
        distance = Decimal(str(distance_km))
        return self.base_fee + (distance * self.price_per_km)
