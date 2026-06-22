from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class CustomerAddress(TimestampMixin, Base):
    __tablename__ = "customer_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    street: Mapped[str] = mapped_column(String(150), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    complement: Mapped[str | None] = mapped_column(String(100), nullable=True)
    neighborhood: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    user: Mapped["User"] = relationship(back_populates="customer_addresses")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer_address")
