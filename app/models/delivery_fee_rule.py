from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DeliveryFeeRule(Base):
    __tablename__ = "delivery_fee_rules"
    __table_args__ = (
        CheckConstraint("min_distance_km >= 0", name="ck_delivery_fee_rules_min_distance_non_negative"),
        CheckConstraint("max_distance_km > min_distance_km", name="ck_delivery_fee_rules_range_valid"),
        CheckConstraint("fee >= 0", name="ck_delivery_fee_rules_fee_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    min_distance_km: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    max_distance_km: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    company: Mapped["Company"] = relationship(back_populates="fee_rules")
