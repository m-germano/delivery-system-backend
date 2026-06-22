from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DeliveryStatus
from app.db.base import Base, TimestampMixin


class Delivery(TimestampMixin, Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint("distance_km >= 0", name="ck_deliveries_distance_non_negative"),
        CheckConstraint("delivery_fee >= 0", name="ck_deliveries_fee_non_negative"),
        CheckConstraint(
            "status IN ('DISPONIVEL','ACEITA','RETIRADA','EM_ROTA','FINALIZADA','CANCELADA')",
            name="ck_deliveries_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    courier_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DeliveryStatus.AVAILABLE.value, server_default=DeliveryStatus.AVAILABLE.value, index=True)
    pickup_latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    pickup_longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    destination_latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    destination_longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    order: Mapped["Order"] = relationship(back_populates="delivery")
    status_history: Mapped[list["DeliveryStatusHistory"]] = relationship(back_populates="delivery", cascade="all, delete-orphan")
