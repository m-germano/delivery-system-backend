from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PaymentProvider, PaymentStatus
from app.db.base import Base, TimestampMixin


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('mercado_pago','manual','simulated')",
            name="ck_payments_provider",
        ),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('pix','credit_card','debit_card','cash','simulated')",
            name="ck_payments_method",
        ),
        CheckConstraint(
            "status IN ('pending','in_process','approved','rejected','cancelled','refunded','failed','expired')",
            name="ck_payments_status",
        ),
        CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
        Index(
            "uq_payments_provider_payment_id",
            "provider",
            "provider_payment_id",
            unique=True,
            postgresql_where=text("provider_payment_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default=PaymentProvider.MERCADO_PAGO.value, server_default=PaymentProvider.MERCADO_PAGO.value, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=PaymentStatus.PENDING.value, server_default=PaymentStatus.PENDING.value, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL", server_default="BRL")
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_code_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def checkout_preference_id(self) -> str | None:
        preference = self._raw_preference_payload()
        preference_id = preference.get("id") if isinstance(preference, dict) else None
        return str(preference_id) if preference_id is not None else self.provider_order_id

    @property
    def checkout_url(self) -> str | None:
        preference = self._raw_preference_payload()
        if not isinstance(preference, dict):
            return None
        value = preference.get("init_point") or preference.get("checkout_url")
        return str(value) if value else None

    @property
    def sandbox_checkout_url(self) -> str | None:
        preference = self._raw_preference_payload()
        if not isinstance(preference, dict):
            return None
        value = preference.get("sandbox_init_point")
        return str(value) if value else None

    def _raw_preference_payload(self) -> dict | None:
        if not isinstance(self.raw_response, dict):
            return None
        preference = self.raw_response.get("preference")
        if isinstance(preference, dict):
            return preference
        if "init_point" in self.raw_response or "sandbox_init_point" in self.raw_response:
            return self.raw_response
        return None
