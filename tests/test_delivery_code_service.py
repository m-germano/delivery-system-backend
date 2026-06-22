from datetime import datetime
from types import SimpleNamespace

from app.services.delivery_code_service import DeliveryCodeService


def test_delivery_code_has_four_digits_and_is_stable():
    delivery = SimpleNamespace(id=10, order_id=20, created_at=datetime(2026, 1, 1, 10, 30, 0))

    first_code = DeliveryCodeService.generate_code(delivery)
    second_code = DeliveryCodeService.generate_code(delivery)

    assert first_code == second_code
    assert len(first_code) == 4
    assert first_code.isdigit()


def test_delivery_code_validation_accepts_only_expected_code():
    delivery = SimpleNamespace(id=10, order_id=20, created_at=datetime(2026, 1, 1, 10, 30, 0))
    code = DeliveryCodeService.generate_code(delivery)

    assert DeliveryCodeService.is_valid_code(delivery, code)
    assert not DeliveryCodeService.is_valid_code(delivery, "0000" if code != "0000" else "0001")
