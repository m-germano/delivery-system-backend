from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Courier(TimestampMixin, Base):
    __tablename__ = "couriers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    current_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    current_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)

    user: Mapped["User"] = relationship(back_populates="courier")
