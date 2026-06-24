from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PaymentAccountProvider
from app.db.base import Base, TimestampMixin


class CompanyPaymentAccount(TimestampMixin, Base):
    __tablename__ = "company_payment_accounts"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('mercado_pago')",
            name="ck_company_payment_accounts_provider",
        ),
        Index(
            "uq_company_payment_accounts_active_provider",
            "company_id",
            "provider",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default=PaymentAccountProvider.MERCADO_PAGO.value, server_default=PaymentAccountProvider.MERCADO_PAGO.value)
    provider_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
