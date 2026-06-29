from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class CompanyOrderSettings(TimestampMixin, Base):
    __tablename__ = "company_order_settings"
    __table_args__ = (
        CheckConstraint("accepts_delivery OR accepts_pickup", name="ck_company_order_settings_at_least_one_mode"),
        CheckConstraint("pickup_discount_percent >= 0 AND pickup_discount_percent <= 100", name="ck_company_order_settings_pickup_discount_range"),
        CheckConstraint("minimum_order_value >= 0", name="ck_company_order_settings_minimum_order_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    accepts_delivery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    accepts_pickup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    pickup_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    minimum_order_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0")

    company: Mapped["Company"] = relationship(back_populates="order_settings")
