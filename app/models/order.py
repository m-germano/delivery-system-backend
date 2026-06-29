from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import FulfillmentType, OrderStatus, PaymentMethod
from app.db.base import Base, TimestampMixin


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_orders_subtotal_non_negative"),
        CheckConstraint("delivery_fee >= 0", name="ck_orders_delivery_fee_non_negative"),
        CheckConstraint("total >= 0", name="ck_orders_total_non_negative"),
        CheckConstraint("distance_km >= 0", name="ck_orders_distance_non_negative"),
        CheckConstraint("discount_amount >= 0", name="ck_orders_discount_non_negative"),
        CheckConstraint("pickup_discount_percent >= 0 AND pickup_discount_percent <= 100", name="ck_orders_pickup_discount_range"),
        CheckConstraint(
            "status IN ('AGUARDANDO_PAGAMENTO','ABERTO','ACEITO','EM_PREPARO','PRONTO_PARA_RETIRADA','AGUARDANDO_ENTREGADOR','EM_ENTREGA','ENTREGUE','RETIRADO','CANCELADO','RECUSADO')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "fulfillment_type IN ('DELIVERY','PICKUP')",
            name="ck_orders_fulfillment_type",
        ),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('CREDITO','DEBITO','PIX','PIX_ONLINE','DINHEIRO')",
            name="ck_orders_payment_method",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    customer_address_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customer_addresses.id"), nullable=True)
    fulfillment_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=FulfillmentType.DELIVERY.value,
        server_default=FulfillmentType.DELIVERY.value,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=OrderStatus.OPEN.value,
        server_default=OrderStatus.OPEN.value,
        index=True,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    pickup_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False, default=PaymentMethod.PIX.value)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped["User"] = relationship(back_populates="orders")
    company: Mapped["Company"] = relationship(back_populates="orders")
    customer_address: Mapped["CustomerAddress"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    delivery: Mapped["Delivery | None"] = relationship(back_populates="order", uselist=False, cascade="all, delete-orphan")
    review: Mapped["CompanyReview | None"] = relationship(back_populates="order", uselist=False, cascade="all, delete-orphan")
