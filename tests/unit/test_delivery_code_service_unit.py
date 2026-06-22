from datetime import datetime
from types import SimpleNamespace

from app.services.delivery_code_service import DeliveryCodeService


def make_delivery(delivery_id=10, order_id=20, created_at=None):
    return SimpleNamespace(
        id=delivery_id,
        order_id=order_id,
        created_at=created_at or datetime(2026, 6, 21, 12, 30, 0),
    )


def test_delivery_code_has_four_digits():
    code = DeliveryCodeService.generate_code(make_delivery())

    assert len(code) == 4
    assert code.isdigit()


def test_delivery_code_is_stable_for_same_delivery():
    delivery = make_delivery()

    first_code = DeliveryCodeService.generate_code(delivery)
    second_code = DeliveryCodeService.generate_code(delivery)

    assert first_code == second_code


def test_delivery_code_changes_when_delivery_changes():
    first_delivery = make_delivery(delivery_id=10, order_id=20)
    second_delivery = make_delivery(delivery_id=11, order_id=20)

    assert DeliveryCodeService.generate_code(first_delivery) != DeliveryCodeService.generate_code(second_delivery)


def test_delivery_code_validation_accepts_correct_code():
    delivery = make_delivery()
    code = DeliveryCodeService.generate_code(delivery)

    assert DeliveryCodeService.is_valid_code(delivery, code) is True


def test_delivery_code_validation_rejects_wrong_or_incomplete_code():
    delivery = make_delivery()

    assert DeliveryCodeService.is_valid_code(delivery, "0000") is False
    assert DeliveryCodeService.is_valid_code(delivery, "12") is False
    assert DeliveryCodeService.is_valid_code(delivery, None) is False


def test_delivery_code_normalization_keeps_only_first_four_digits():
    assert DeliveryCodeService.normalize_code(" código: 1234-999 ") == "1234"
