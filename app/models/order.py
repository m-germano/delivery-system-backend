from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import OrderStatus, PaymentMethod
from app.db.base import Base, TimestampMixin


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_orders_subtotal_non_negative"),
        CheckConstraint("delivery_fee >= 0", name="ck_orders_delivery_fee_non_negative"),
        CheckConstraint("total >= 0", name="ck_orders_total_non_negative"),
        CheckConstraint("distance_km >= 0", name="ck_orders_distance_non_negative"),
        CheckConstraint(
            "status IN ('ABERTO','ACEITO','EM_PREPARO','AGUARDANDO_ENTREGADOR','EM_ENTREGA','ENTREGUE','CANCELADO','RECUSADO')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('CREDITO','DEBITO','PIX','DINHEIRO')",
            name="ck_orders_payment_method",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    customer_address_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customer_addresses.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=OrderStatus.OPEN.value,
        server_default=OrderStatus.OPEN.value,
        index=True,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
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
