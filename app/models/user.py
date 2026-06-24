from sqlalchemy import BigInteger, Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("roles.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    role: Mapped["Role"] = relationship(back_populates="users")
    company: Mapped["Company | None"] = relationship(back_populates="owner", uselist=False)
    courier: Mapped["Courier | None"] = relationship(back_populates="user", uselist=False)
    customer_addresses: Mapped[list["CustomerAddress"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    company_reviews: Mapped[list["CompanyReview"]] = relationship(back_populates="customer")
