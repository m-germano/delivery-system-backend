from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_products_price_non_negative"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    company: Mapped["Company"] = relationship(back_populates="products")
    category: Mapped["ProductCategory | None"] = relationship(back_populates="products")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")
