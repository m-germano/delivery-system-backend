from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CompanyAddress(Base):
    __tablename__ = "company_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)
    street: Mapped[str] = mapped_column(String(150), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    complement: Mapped[str | None] = mapped_column(String(100), nullable=True)
    neighborhood: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)

    company: Mapped["Company"] = relationship(back_populates="address")
