from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.enums import FulfillmentType, OrderStatus
from app.schemas.company_order_settings_schema import CompanyOrderSettingsUpdateRequest
from app.schemas.order_schema import OrderCreateRequest
from app.services.delivery_code_service import PickupCodeService
from app.services.order_service import DELIVERY_COMPANY_STATUS_FLOW, PICKUP_COMPANY_STATUS_FLOW, OrderService


class FakeSession:
    async def commit(self):
        return None

    async def refresh(self, instance):
        return None

    async def flush(self):
        return None


def test_company_order_settings_require_at_least_one_fulfillment_mode():
    with pytest.raises(ValidationError):
        CompanyOrderSettingsUpdateRequest(
            accepts_delivery=False,
            accepts_pickup=False,
            pickup_discount_percent=Decimal("0"),
            minimum_order_value=Decimal("0"),
        )


def test_company_order_settings_validate_discount_and_minimum_order_value():
    settings = CompanyOrderSettingsUpdateRequest(
        accepts_delivery=True,
        accepts_pickup=True,
        pickup_discount_percent=Decimal("10.50"),
        minimum_order_value=Decimal("25.00"),
    )

    assert settings.accepts_delivery is True
    assert settings.accepts_pickup is True
    assert settings.pickup_discount_percent == Decimal("10.50")
    assert settings.minimum_order_value == Decimal("25.00")


def test_order_create_request_defaults_to_delivery():
    request = OrderCreateRequest(
        company_id=1,
        customer_address_id=1,
        items=[{"product_id": 10, "quantity": 2}],
    )

    assert request.fulfillment_type == FulfillmentType.DELIVERY


def test_pickup_company_flow_never_goes_to_waiting_courier():
    assert OrderStatus.WAITING_COURIER.value not in PICKUP_COMPANY_STATUS_FLOW[OrderStatus.IN_PREPARATION.value]
    assert OrderStatus.READY_FOR_PICKUP.value in PICKUP_COMPANY_STATUS_FLOW[OrderStatus.IN_PREPARATION.value]
    assert OrderStatus.PICKED_UP.value in PICKUP_COMPANY_STATUS_FLOW[OrderStatus.READY_FOR_PICKUP.value]
    assert OrderStatus.WAITING_COURIER.value in DELIVERY_COMPANY_STATUS_FLOW[OrderStatus.IN_PREPARATION.value]


def test_pickup_confirmation_code_is_attached_only_when_ready_for_pickup():
    order = SimpleNamespace(
        id=10,
        company_id=1,
        customer_user_id=7,
        created_at="2026-06-24T12:00:00",
        fulfillment_type=FulfillmentType.PICKUP.value,
        status=OrderStatus.READY_FOR_PICKUP.value,
        delivery=None,
    )

    OrderService._attach_customer_delivery_code(order)

    assert order.delivery_confirmation_code is None
    assert order.pickup_confirmation_code == PickupCodeService.generate_code(order)


def test_pickup_confirmation_requires_valid_code_to_mark_picked_up():
    order = SimpleNamespace(
        id=10,
        company_id=1,
        customer_user_id=7,
        created_at="2026-06-24T12:00:00",
        fulfillment_type=FulfillmentType.PICKUP.value,
        status=OrderStatus.READY_FOR_PICKUP.value,
    )

    with pytest.raises(HTTPException) as exc_info:
        OrderService._validate_pickup_confirmation(order, "0000")

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Código de retirada inválido."

    OrderService._validate_pickup_confirmation(order, PickupCodeService.generate_code(order))
