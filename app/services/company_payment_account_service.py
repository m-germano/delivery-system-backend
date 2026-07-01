import base64
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.enums import PaymentAccountProvider, RoleId
from app.models import Company, CompanyPaymentAccount, PaymentOAuthState, User
from app.repositories.company_payment_account_repository import CompanyPaymentAccountRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.payment_oauth_state_repository import PaymentOAuthStateRepository
from app.repositories.user_repository import UserRepository
from app.schemas.payment_schema import CompanyPaymentAccountCreateRequest


MERCADO_PAGO_OAUTH_STATE_TTL_MINUTES = 10
logger = logging.getLogger(__name__)

SENSITIVE_LOG_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "code",
    "code_verifier",
    "authorization",
    "token",
}


def _sanitize_for_log(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_as_text = str(key).lower()
            if key_as_text in SENSITIVE_LOG_KEYS or key_as_text.endswith("_token"):
                sanitized[key] = "***"
                continue
            sanitized[key] = _sanitize_for_log(item)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value]

    return value


class CompanyPaymentAccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.company_repository = CompanyRepository(session)
        self.account_repository = CompanyPaymentAccountRepository(session)
        self.oauth_state_repository = PaymentOAuthStateRepository(session)
        self.user_repository = UserRepository(session)

    async def build_mercado_pago_connect_url(self, company_id: int, current_user: User) -> str:
        company = await self._get_authorized_company(company_id, current_user)
        self._ensure_mercado_pago_oauth_settings()

        state, code_verifier = self._create_oauth_state_values()
        await self._store_oauth_state(
            company_id=company.id,
            user_id=current_user.id,
            state=state,
            code_verifier=code_verifier,
        )

        query_params = {
            "client_id": settings.MERCADO_PAGO_CLIENT_ID,
            "response_type": "code",
            "platform_id": "mp",
            "redirect_uri": settings.MERCADO_PAGO_REDIRECT_URI,
            "state": state,
        }

        if settings.MERCADO_PAGO_USE_PKCE:
            query_params["code_challenge"] = self._build_code_challenge(code_verifier)
            query_params["code_challenge_method"] = "S256"

        query = urlencode(query_params)
        return f"{settings.MERCADO_PAGO_OAUTH_AUTHORIZE_URL}?{query}"

    async def connect_mercado_pago_from_callback(self, *, code: str | None, state: str | None) -> CompanyPaymentAccount:
        if not code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código de autorização ausente.")

        logger.info(
            "Iniciando callback OAuth Mercado Pago. code_presente=%s state_presente=%s pkce_ativo=%s client_secret_configurado=%s",
            bool(code),
            bool(state),
            settings.MERCADO_PAGO_USE_PKCE,
            bool(settings.MERCADO_PAGO_CLIENT_SECRET),
        )
        oauth_state = await self._consume_oauth_state(state)
        logger.info(
            "State OAuth Mercado Pago validado. company_id=%s user_id=%s provider=%s pkce_ativo=%s",
            oauth_state.company_id,
            oauth_state.user_id,
            oauth_state.provider,
            settings.MERCADO_PAGO_USE_PKCE,
        )
        user = await self.user_repository.get_by_id(oauth_state.user_id)

        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State inválido ou expirado.")

        company = await self._get_authorized_company(oauth_state.company_id, user)
        code_verifier = decrypt_secret(oauth_state.code_verifier_encrypted) if oauth_state.code_verifier_encrypted else None
        token_payload = await self._exchange_mercado_pago_code(code, code_verifier=code_verifier)
        return await self._create_or_replace_mercado_pago_account(company.id, token_payload)

    async def create_account(
        self,
        company_id: int,
        data: CompanyPaymentAccountCreateRequest,
        current_user: User,
    ) -> CompanyPaymentAccount:
        company = await self._get_authorized_company(company_id, current_user)
        now = datetime.utcnow()

        active_account = await self.account_repository.get_active_by_company_and_provider(company.id, data.provider)
        if active_account is not None:
            await self.account_repository.deactivate_account(active_account, disconnected_at=now)

        account = CompanyPaymentAccount(
            company_id=company.id,
            provider=data.provider,
            provider_user_id=data.provider_user_id,
            public_key=data.public_key,
            access_token_encrypted=encrypt_secret(data.access_token),
            refresh_token_encrypted=encrypt_secret(data.refresh_token) if data.refresh_token else None,
            token_expires_at=data.token_expires_at,
            is_active=True,
            connected_at=now,
            disconnected_at=None,
        )

        await self.account_repository.create_account(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def _create_or_replace_mercado_pago_account(self, company_id: int, token_payload: dict) -> CompanyPaymentAccount:
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Mercado Pago não retornou access_token.")

        refresh_token = token_payload.get("refresh_token")
        expires_in = token_payload.get("expires_in")
        token_expires_at = self._calculate_token_expires_at(expires_in)
        provider_user_id = token_payload.get("user_id") or token_payload.get("collector_id")
        public_key = token_payload.get("public_key")

        now = datetime.utcnow()
        active_account = await self.account_repository.get_active_by_company_and_provider(
            company_id,
            PaymentAccountProvider.MERCADO_PAGO.value,
        )
        if active_account is not None:
            await self.account_repository.deactivate_account(active_account, disconnected_at=now)

        logger.info(
            "Preparando salvamento de CompanyPaymentAccount Mercado Pago. company_id=%s provider=%s provider_user_id=%s conta_ativa_anterior=%s",
            company_id,
            PaymentAccountProvider.MERCADO_PAGO.value,
            provider_user_id,
            bool(active_account),
        )
        account = CompanyPaymentAccount(
            company_id=company_id,
            provider=PaymentAccountProvider.MERCADO_PAGO.value,
            provider_user_id=str(provider_user_id) if provider_user_id is not None else None,
            public_key=str(public_key) if public_key is not None else None,
            access_token_encrypted=encrypt_secret(str(access_token)),
            refresh_token_encrypted=encrypt_secret(str(refresh_token)) if refresh_token else None,
            token_expires_at=token_expires_at,
            is_active=True,
            connected_at=now,
            disconnected_at=None,
        )

        await self.account_repository.create_account(account)
        await self.session.commit()
        await self.session.refresh(account)
        logger.info(
            "CompanyPaymentAccount Mercado Pago salva com sucesso. company_id=%s provider=%s provider_user_id=%s is_active=%s",
            account.company_id,
            account.provider,
            account.provider_user_id,
            account.is_active,
        )
        return account

    async def list_by_company(self, company_id: int, current_user: User) -> list[CompanyPaymentAccount]:
        company = await self._get_authorized_company(company_id, current_user)
        return await self.account_repository.list_by_company(company.id)

    async def get_active_by_company_and_provider(
        self,
        company_id: int,
        provider: str,
        current_user: User,
    ) -> CompanyPaymentAccount | None:
        company = await self._get_authorized_company(company_id, current_user)
        return await self.account_repository.get_active_by_company_and_provider(company.id, provider)

    async def deactivate_account(self, company_id: int, account_id: int, current_user: User) -> CompanyPaymentAccount:
        company = await self._get_authorized_company(company_id, current_user)
        account = await self.account_repository.get_by_id_and_company(account_id, company.id)

        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta de pagamento não encontrada.")

        if account.is_active:
            await self.account_repository.deactivate_account(account, disconnected_at=datetime.utcnow())
            await self.session.commit()
            await self.session.refresh(account)

        return account

    async def refresh_mercado_pago_access_token(self, account: CompanyPaymentAccount) -> CompanyPaymentAccount:
        """Renova o access token OAuth da conta Mercado Pago conectada.

        O fluxo de pagamento usa tokens por empresa/restaurante salvos no banco.
        Quando o access_token estiver perto de expirar, esta rotina usa o
        refresh_token criptografado para obter novas credenciais e persistir
        o resultado antes de chamar a API de pagamentos.
        """
        self._ensure_mercado_pago_oauth_settings()

        if account.provider != PaymentAccountProvider.MERCADO_PAGO.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider de pagamento não suportado.")

        if not account.refresh_token_encrypted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conta Mercado Pago sem refresh token para renovação.")

        refresh_token = decrypt_secret(account.refresh_token_encrypted)
        payload = {
            "grant_type": "refresh_token",
            "client_id": settings.MERCADO_PAGO_CLIENT_ID,
            "refresh_token": refresh_token,
        }

        if settings.MERCADO_PAGO_CLIENT_SECRET:
            payload["client_secret"] = settings.MERCADO_PAGO_CLIENT_SECRET

        logger.info(
            "Renovando access token Mercado Pago. company_id=%s account_id=%s payload=%s",
            account.company_id,
            account.id,
            _sanitize_for_log(payload),
        )

        try:
            async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    settings.MERCADO_PAGO_OAUTH_TOKEN_URL,
                    data=payload,
                    headers={"Accept": "application/json"},
                )
                if response.is_error:
                    logger.warning(
                        "Erro ao renovar token Mercado Pago. status_code=%s body=%s",
                        response.status_code,
                        self._sanitize_response_body_for_log(response),
                    )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Mercado Pago recusou a renovação do token OAuth.",
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível renovar o token OAuth do Mercado Pago.",
            ) from exc

        if not isinstance(data, dict) or not data.get("access_token"):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Resposta inválida ao renovar token Mercado Pago.")

        account.access_token_encrypted = encrypt_secret(str(data["access_token"]))

        new_refresh_token = data.get("refresh_token")
        if new_refresh_token:
            account.refresh_token_encrypted = encrypt_secret(str(new_refresh_token))

        account.token_expires_at = self._calculate_token_expires_at(data.get("expires_in"))

        provider_user_id = data.get("user_id") or data.get("collector_id")
        if provider_user_id is not None:
            account.provider_user_id = str(provider_user_id)

        public_key = data.get("public_key")
        if public_key is not None:
            account.public_key = str(public_key)

        await self.session.commit()
        await self.session.refresh(account)
        logger.info(
            "Access token Mercado Pago renovado com sucesso. company_id=%s account_id=%s token_expires_at=%s",
            account.company_id,
            account.id,
            account.token_expires_at.isoformat() if account.token_expires_at else None,
        )
        return account

    async def _get_authorized_company(self, company_id: int, current_user: User) -> Company:
        company = await self.company_repository.get_by_id(company_id, include_inactive=True)

        if company is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada.")

        role_id = RoleId(current_user.role_id)

        if role_id == RoleId.ADMIN:
            return company

        if role_id == RoleId.COMPANY and company.owner_user_id == current_user.id:
            return company

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada.")

    @staticmethod
    def _ensure_mercado_pago_oauth_settings() -> None:
        required_settings = {
            "MERCADO_PAGO_CLIENT_ID": settings.MERCADO_PAGO_CLIENT_ID,
            "MERCADO_PAGO_REDIRECT_URI": settings.MERCADO_PAGO_REDIRECT_URI,
        }

        if not settings.MERCADO_PAGO_USE_PKCE:
            required_settings["MERCADO_PAGO_CLIENT_SECRET"] = settings.MERCADO_PAGO_CLIENT_SECRET

        missing = [name for name, value in required_settings.items() if not value]

        if missing:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Configuração OAuth Mercado Pago incompleta: {', '.join(missing)}.",
            )

    async def _store_oauth_state(self, *, company_id: int, user_id: int, state: str, code_verifier: str) -> PaymentOAuthState:
        oauth_state = PaymentOAuthState(
            company_id=company_id,
            user_id=user_id,
            provider=PaymentAccountProvider.MERCADO_PAGO.value,
            state=state,
            code_verifier_encrypted=encrypt_secret(code_verifier) if settings.MERCADO_PAGO_USE_PKCE else None,
            expires_at=datetime.utcnow() + timedelta(minutes=MERCADO_PAGO_OAUTH_STATE_TTL_MINUTES),
        )
        await self.oauth_state_repository.create(oauth_state)
        await self.session.commit()
        await self.session.refresh(oauth_state)
        return oauth_state

    @staticmethod
    def _create_oauth_state_values() -> tuple[str, str]:
        state = secrets.token_urlsafe(48)
        code_verifier = secrets.token_urlsafe(64)
        return state, code_verifier

    @staticmethod
    def _build_code_challenge(code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    async def _consume_oauth_state(self, state: str | None) -> PaymentOAuthState:
        if not state:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth ausente.")

        oauth_state = await self.oauth_state_repository.get_by_state(state)
        logger.info(
            "Busca de state OAuth Mercado Pago concluída. encontrado=%s pkce_ativo=%s",
            oauth_state is not None,
            settings.MERCADO_PAGO_USE_PKCE,
        )

        if oauth_state is None or oauth_state.provider != PaymentAccountProvider.MERCADO_PAGO.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth inválido.")

        logger.info(
            "State OAuth Mercado Pago encontrado. company_id=%s user_id=%s provider=%s consumido=%s expiracao=%s",
            oauth_state.company_id,
            oauth_state.user_id,
            oauth_state.provider,
            oauth_state.consumed_at is not None,
            oauth_state.expires_at.isoformat() if oauth_state.expires_at else None,
        )

        if oauth_state.consumed_at is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth já consumido.")

        now = datetime.utcnow()
        if oauth_state.expires_at < now:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth expirado.")

        if settings.MERCADO_PAGO_USE_PKCE and not oauth_state.code_verifier_encrypted:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth inválido.")

        await self.oauth_state_repository.mark_consumed(oauth_state, consumed_at=now)
        await self.session.commit()
        await self.session.refresh(oauth_state)
        return oauth_state

    async def _exchange_mercado_pago_code(self, code: str, *, code_verifier: str | None = None) -> dict:
        self._ensure_mercado_pago_oauth_settings()

        payload = {
            "grant_type": "authorization_code",
            "client_id": settings.MERCADO_PAGO_CLIENT_ID,
            "code": code,
            "redirect_uri": settings.MERCADO_PAGO_REDIRECT_URI,
        }

        if settings.MERCADO_PAGO_CLIENT_SECRET:
            payload["client_secret"] = settings.MERCADO_PAGO_CLIENT_SECRET

        if settings.MERCADO_PAGO_USE_PKCE:
            if not code_verifier:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code verifier OAuth ausente.")
            payload["code_verifier"] = code_verifier

        logger.info(
            "Trocando code OAuth Mercado Pago por token. url=%s pkce_ativo=%s client_secret_configurado=%s payload=%s",
            settings.MERCADO_PAGO_OAUTH_TOKEN_URL,
            settings.MERCADO_PAGO_USE_PKCE,
            bool(settings.MERCADO_PAGO_CLIENT_SECRET),
            _sanitize_for_log(payload),
        )
        try:
            async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    settings.MERCADO_PAGO_OAUTH_TOKEN_URL,
                    data=payload,
                    headers={"Accept": "application/json"},
                )
                logger.info("Resposta do token endpoint Mercado Pago. status_code=%s", response.status_code)
                if response.is_error:
                    logger.warning(
                        "Erro no token endpoint Mercado Pago. status_code=%s body=%s payload=%s",
                        response.status_code,
                        self._sanitize_response_body_for_log(response),
                        _sanitize_for_log(payload),
                    )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Mercado Pago recusou a troca do código OAuth.",
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível concluir a comunicação OAuth com o Mercado Pago.",
            ) from exc

        if not isinstance(data, dict):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Resposta OAuth inválida do Mercado Pago.")

        return data

    @staticmethod
    def _sanitize_response_body_for_log(response: httpx.Response):
        try:
            return _sanitize_for_log(response.json())
        except ValueError:
            sanitized_text = response.text
            sanitized_text = re.sub(
                r'(?i)("?(?:access_token|refresh_token|client_secret|code_verifier|code)"?\s*[:=]\s*)"[^"&\s]+',
                r"\1***",
                sanitized_text,
            )
            return sanitized_text[:2000]

    @staticmethod
    def _calculate_token_expires_at(expires_in) -> datetime | None:
        if expires_in is None:
            return None

        try:
            seconds = int(expires_in)
        except (TypeError, ValueError):
            return None

        if seconds <= 0:
            return None

        return datetime.utcnow() + timedelta(seconds=seconds)
