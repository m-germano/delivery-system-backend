from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.enums import RoleId
from app.schemas.payment_schema import CompanyPaymentAccountResponse
from app.services.company_payment_account_service import CompanyPaymentAccountService, MERCADO_PAGO_OAUTH_STATE_TTL_MINUTES


class FakeCompanyRepository:
    def __init__(self, company):
        self.company = company

    async def get_by_id(self, company_id: int, *, include_inactive: bool = False):
        if company_id == self.company.id:
            return self.company
        return None


class FakeAccountRepository:
    def __init__(self, active_account=None):
        self.active_account = active_account
        self.created_account = None
        self.deactivated_accounts = []
        self.account_by_id = None

    async def create_account(self, account):
        account.id = 10
        account.created_at = datetime.utcnow()
        account.updated_at = datetime.utcnow()
        self.created_account = account
        return account

    async def get_active_by_company_and_provider(self, company_id: int, provider: str):
        if self.active_account and self.active_account.company_id == company_id and self.active_account.provider == provider and self.active_account.is_active:
            return self.active_account
        return None

    async def deactivate_account(self, account, *, disconnected_at: datetime):
        account.is_active = False
        account.disconnected_at = disconnected_at
        self.deactivated_accounts.append(account)
        return account

    async def get_by_id_and_company(self, account_id: int, company_id: int):
        if self.account_by_id and self.account_by_id.id == account_id and self.account_by_id.company_id == company_id:
            return self.account_by_id
        return None


class FakeOAuthStateRepository:
    def __init__(self, oauth_state=None):
        self.oauth_state = oauth_state
        self.created_state = None

    async def create(self, oauth_state):
        oauth_state.id = 99
        oauth_state.created_at = datetime.utcnow()
        self.created_state = oauth_state
        self.oauth_state = oauth_state
        return oauth_state

    async def get_by_state(self, state: str):
        if self.oauth_state and self.oauth_state.state == state:
            return self.oauth_state
        return None

    async def mark_consumed(self, oauth_state, *, consumed_at: datetime):
        oauth_state.consumed_at = consumed_at
        return oauth_state


class FakeSession:
    async def commit(self):
        return None

    async def refresh(self, instance):
        return None


@pytest.mark.asyncio
async def test_create_account_encrypts_tokens_and_does_not_store_plain_text(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    company = SimpleNamespace(id=1, owner_user_id=7)
    current_user = SimpleNamespace(id=7, role_id=RoleId.COMPANY)
    data = SimpleNamespace(
        provider="mercado_pago",
        provider_user_id="123456789",
        public_key="APP_USR-public",
        access_token="APP_USR-access",
        refresh_token="TG-refresh",
        token_expires_at=None,
    )

    service = CompanyPaymentAccountService(FakeSession())
    service.company_repository = FakeCompanyRepository(company)
    service.account_repository = FakeAccountRepository()

    account = await service.create_account(company.id, data, current_user)

    assert account.access_token_encrypted != data.access_token
    assert account.refresh_token_encrypted != data.refresh_token
    assert "APP_USR-access" not in account.access_token_encrypted
    assert "TG-refresh" not in account.refresh_token_encrypted


@pytest.mark.asyncio
async def test_create_account_deactivates_previous_active_account(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    company = SimpleNamespace(id=1, owner_user_id=7)
    current_user = SimpleNamespace(id=7, role_id=RoleId.COMPANY)
    previous_account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, disconnected_at=None)
    data = SimpleNamespace(
        provider="mercado_pago",
        provider_user_id=None,
        public_key=None,
        access_token="APP_USR-new-access",
        refresh_token=None,
        token_expires_at=None,
    )

    account_repository = FakeAccountRepository(active_account=previous_account)
    service = CompanyPaymentAccountService(FakeSession())
    service.company_repository = FakeCompanyRepository(company)
    service.account_repository = account_repository

    await service.create_account(company.id, data, current_user)

    assert previous_account.is_active is False
    assert previous_account.disconnected_at is not None
    assert account_repository.deactivated_accounts == [previous_account]


@pytest.mark.asyncio
async def test_build_mercado_pago_connect_url_contains_required_parameters(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "MERCADO_PAGO_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADO_PAGO_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MERCADO_PAGO_USE_PKCE", True)
    monkeypatch.setattr(settings, "MERCADO_PAGO_REDIRECT_URI", "http://localhost:8000/api/payment-accounts/mercado-pago/callback")
    monkeypatch.setattr(settings, "MERCADO_PAGO_OAUTH_AUTHORIZE_URL", "https://auth.mercadopago.com.br/authorization")

    company = SimpleNamespace(id=1, owner_user_id=7)
    current_user = SimpleNamespace(id=7, role_id=RoleId.COMPANY)

    service = CompanyPaymentAccountService(FakeSession())
    service.company_repository = FakeCompanyRepository(company)
    service.oauth_state_repository = FakeOAuthStateRepository()

    authorization_url = await service.build_mercado_pago_connect_url(company.id, current_user)
    parsed_url = urlparse(authorization_url)
    query = parse_qs(parsed_url.query)

    assert authorization_url.startswith("https://auth.mercadopago.com.br/authorization?")
    assert query["client_id"] == ["client-id"]
    assert query["response_type"] == ["code"]
    assert query["platform_id"] == ["mp"]
    assert query["redirect_uri"] == ["http://localhost:8000/api/payment-accounts/mercado-pago/callback"]
    assert "state" in query
    assert query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in query
    assert "code_verifier" not in query

    stored_state = service.oauth_state_repository.created_state
    assert stored_state.state == query["state"][0]
    assert stored_state.company_id == company.id
    assert stored_state.user_id == current_user.id
    assert stored_state.provider == "mercado_pago"
    assert stored_state.code_verifier_encrypted


def test_build_code_challenge_uses_s256_base64url_without_padding():
    code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    code_challenge = CompanyPaymentAccountService._build_code_challenge(code_verifier)

    assert code_challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert "=" not in code_challenge


def test_create_oauth_state_values_generates_secure_values():
    state, code_verifier = CompanyPaymentAccountService._create_oauth_state_values()

    assert len(state) >= 43
    assert len(code_verifier) >= 43
    assert state != code_verifier


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_invalid_state(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    service = CompanyPaymentAccountService(FakeSession())
    service.oauth_state_repository = FakeOAuthStateRepository()

    with pytest.raises(Exception, match="State OAuth inválido"):
        await service._consume_oauth_state("invalid-state")


@pytest.mark.asyncio
async def test_consume_oauth_state_rejects_expired_state(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "MERCADO_PAGO_USE_PKCE", True)

    expired_at = datetime.utcnow() - timedelta(minutes=MERCADO_PAGO_OAUTH_STATE_TTL_MINUTES)
    expired_state = SimpleNamespace(
        id=1,
        company_id=1,
        user_id=7,
        provider="mercado_pago",
        state="expired-state",
        code_verifier_encrypted="encrypted-verifier",
        expires_at=expired_at,
        consumed_at=None,
    )

    service = CompanyPaymentAccountService(FakeSession())
    service.oauth_state_repository = FakeOAuthStateRepository(expired_state)

    with pytest.raises(Exception, match="State OAuth expirado"):
        await service._consume_oauth_state("expired-state")


@pytest.mark.asyncio
async def test_consumed_oauth_state_cannot_be_reused(monkeypatch):
    monkeypatch.setattr(settings, "MERCADO_PAGO_USE_PKCE", True)
    oauth_state = SimpleNamespace(
        id=1,
        company_id=1,
        user_id=7,
        provider="mercado_pago",
        state="already-consumed-state",
        code_verifier_encrypted="encrypted-verifier",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
        consumed_at=datetime.utcnow(),
    )

    service = CompanyPaymentAccountService(FakeSession())
    service.oauth_state_repository = FakeOAuthStateRepository(oauth_state)

    with pytest.raises(Exception, match="State OAuth já consumido"):
        await service._consume_oauth_state("already-consumed-state")


def test_mercado_pago_settings_do_not_require_client_secret_when_pkce_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MERCADO_PAGO_CLIENT_ID", "5058819498948614")
    monkeypatch.setattr(settings, "MERCADO_PAGO_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MERCADO_PAGO_USE_PKCE", True)
    monkeypatch.setattr(settings, "MERCADO_PAGO_REDIRECT_URI", "http://localhost:8000/api/payment-accounts/mercado-pago/callback")

    CompanyPaymentAccountService._ensure_mercado_pago_oauth_settings()


@pytest.mark.asyncio
async def test_create_or_replace_mercado_pago_account_encrypts_oauth_tokens(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    previous_account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, disconnected_at=None)
    account_repository = FakeAccountRepository(active_account=previous_account)
    service = CompanyPaymentAccountService(FakeSession())
    service.account_repository = account_repository

    token_payload = {
        "access_token": "real-access-token",
        "refresh_token": "real-refresh-token",
        "public_key": "APP_USR-public-key",
        "user_id": 123456789,
        "expires_in": 3600,
    }

    account = await service._create_or_replace_mercado_pago_account(1, token_payload)

    assert previous_account.is_active is False
    assert account.provider_user_id == "123456789"
    assert account.public_key == "APP_USR-public-key"
    assert account.token_expires_at is not None
    assert account.access_token_encrypted != token_payload["access_token"]
    assert account.refresh_token_encrypted != token_payload["refresh_token"]
    assert "real-access-token" not in account.access_token_encrypted
    assert "real-refresh-token" not in account.refresh_token_encrypted


@pytest.mark.asyncio
async def test_deactivate_account_marks_account_inactive():
    company = SimpleNamespace(id=1, owner_user_id=7)
    current_user = SimpleNamespace(id=7, role_id=RoleId.COMPANY)
    account = SimpleNamespace(id=10, company_id=1, is_active=True, disconnected_at=None)

    account_repository = FakeAccountRepository()
    account_repository.account_by_id = account

    service = CompanyPaymentAccountService(FakeSession())
    service.company_repository = FakeCompanyRepository(company)
    service.account_repository = account_repository

    deactivated_account = await service.deactivate_account(company.id, account.id, current_user)

    assert deactivated_account.is_active is False
    assert deactivated_account.disconnected_at is not None


def test_payment_account_response_does_not_include_tokens():
    account = SimpleNamespace(
        id=10,
        company_id=1,
        provider="mercado_pago",
        provider_user_id="123456789",
        public_key="APP_USR-public",
        access_token_encrypted="encrypted-access-token",
        refresh_token_encrypted="encrypted-refresh-token",
        token_expires_at=None,
        is_active=True,
        connected_at=datetime.utcnow(),
        disconnected_at=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    payload = CompanyPaymentAccountResponse.model_validate(account).model_dump()

    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "access_token_encrypted" not in payload
    assert "refresh_token_encrypted" not in payload
