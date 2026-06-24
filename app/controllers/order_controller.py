from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PaymentStatus, RoleId
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.schemas.order_schema import (
    OrderCalculationResponse,
    OrderCreateRequest,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdateRequest,
)
from app.schemas.payment_schema import OrderPaymentStatusResponse, PaymentResponse, PixOrderCreateResponse
from app.services.order_service import OrderService
from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService

router = APIRouter(tags=["Orders"])


@router.post("/orders/calculate", response_model=OrderCalculationResponse)
async def calculate_order(
    data: OrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await OrderService(db).calculate_order(data, current_user)


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await OrderService(db).create_order(data, current_user)


@router.post("/orders/pix", response_model=PixOrderCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_pix_order(
    data: OrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await OrderService(db).create_pix_online_order(data, current_user)


@router.get("/orders/my", response_model=OrderListResponse)
async def list_my_orders(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    orders, total = await OrderService(db).list_my_orders(current_user, limit=limit, offset=offset)
    return OrderListResponse(items=orders, total=total)


@router.get("/orders/company", response_model=OrderListResponse)
async def list_company_orders(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    orders, total = await OrderService(db).list_company_orders(current_user, limit=limit, offset=offset)
    return OrderListResponse(items=orders, total=total)


@router.get("/orders", response_model=OrderListResponse)
async def list_all_orders(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.ADMIN)),
):
    orders, total = await OrderService(db).list_all_orders(current_user, limit=limit, offset=offset)
    return OrderListResponse(items=orders, total=total)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await OrderService(db).get_order(order_id, current_user)


@router.get("/orders/{order_id}/payment-status", response_model=OrderPaymentStatusResponse)
async def get_order_payment_status(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = await OrderService(db).get_order(order_id, current_user)
    payment_service = MercadoPagoPixPaymentService(db)
    payment = await payment_service.payment_repository.get_latest_by_order(order.id)
    if payment and payment.provider_payment_id and payment.status in {PaymentStatus.PENDING.value, PaymentStatus.IN_PROCESS.value}:
        payment = await payment_service.refresh_payment_from_provider(payment)
    action_flags = payment_service.get_payment_action_flags(order, payment)
    return OrderPaymentStatusResponse(
        order_id=order.id,
        order_status=order.status,
        payment_status=payment.status if payment else None,
        payment=PaymentResponse.model_validate(payment) if payment else None,
        **action_flags,
    )


@router.post("/orders/{order_id}/payments/pix/cancel", response_model=PaymentResponse)
async def cancel_pix_payment(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    order = await OrderService(db).get_order(order_id, current_user)
    payment = await MercadoPagoPixPaymentService(db).cancel_pending_pix_payment(order, current_user)
    return payment


@router.post("/orders/{order_id}/payments/pix/regenerate", response_model=PaymentResponse)
async def regenerate_pix_payment(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    order = await OrderService(db).get_order(order_id, current_user)
    payment = await MercadoPagoPixPaymentService(db).regenerate_pix_payment_for_order(order, current_user)
    return payment


@router.patch("/orders/{order_id}/payments/switch-to-delivery", response_model=OrderResponse)
async def switch_to_pay_on_delivery(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    order = await OrderService(db).get_order(order_id, current_user)
    updated_order = await MercadoPagoPixPaymentService(db).switch_pending_order_to_pay_on_delivery(order, current_user)
    return await OrderService(db).get_order(updated_order.id, current_user)


@router.patch("/orders/{order_id}/accept", response_model=OrderResponse)
async def accept_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await OrderService(db).accept_order(order_id, current_user)


@router.patch("/orders/{order_id}/reject", response_model=OrderResponse)
async def reject_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await OrderService(db).reject_order(order_id, current_user)


@router.patch("/orders/{order_id}/cancel-by-company", response_model=OrderResponse)
async def cancel_order_by_company(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await OrderService(db).cancel_order_by_company(order_id, current_user)


@router.patch("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order_by_customer(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await OrderService(db).cancel_order_by_customer(order_id, current_user)


@router.patch("/orders/{order_id}/confirm-received", response_model=OrderResponse)
async def confirm_order_received_by_customer(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await OrderService(db).confirm_received_by_customer(order_id, current_user)


@router.patch("/orders/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    data: OrderStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await OrderService(db).update_company_status(
        order_id,
        data.status,
        current_user,
        confirmation_code=data.confirmation_code,
    )
