from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    document: Mapped[str | None] = mapped_column(String(30), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    owner: Mapped["User"] = relationship(back_populates="company")
    address: Mapped["CompanyAddress | None"] = relationship(back_populates="company", uselist=False, cascade="all, delete-orphan")
    categories: Mapped[list["ProductCategory"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    products: Mapped[list["Product"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    fee_rules: Mapped[list["DeliveryFeeRule"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="company")
    reviews: Mapped[list["CompanyReview"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    order_settings: Mapped["CompanyOrderSettings | None"] = relationship(
        back_populates="company",
        uselist=False,
        cascade="all, delete-orphan",
    )
