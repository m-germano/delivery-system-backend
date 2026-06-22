from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Courier, User
from app.repositories.company_repository import CompanyRepository
from app.repositories.courier_repository import CourierRepository
from app.repositories.customer_address_repository import CustomerAddressRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth_schema import LoginRequest, TokenResponse
from app.schemas.user_schema import UserCompletionResponse, UserRegisterRequest

PUBLIC_REGISTER_ROLES = {RoleId.COMPANY, RoleId.COURIER, RoleId.CUSTOMER}


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.company_repository = CompanyRepository(session)
        self.customer_address_repository = CustomerAddressRepository(session)
        self.courier_repository = CourierRepository(session)

    async def register(self, data: UserRegisterRequest) -> User:
        role_id = RoleId(data.role_id)
        if role_id not in PUBLIC_REGISTER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role não permitida para cadastro público.",
            )

        existing_user = await self.user_repository.get_by_email(str(data.email))
        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="E-mail já cadastrado.",
            )

        user = User(
            role_id=int(role_id),
            name=data.name.strip(),
            email=str(data.email).lower().strip(),
            password_hash=hash_password(data.password),
            phone=data.phone,
            is_active=True,
        )

        self.session.add(user)
        await self.session.flush()

        if role_id == RoleId.COURIER:
            self.session.add(Courier(user_id=user.id))

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def login(self, data: LoginRequest) -> TokenResponse:
        user = await self.user_repository.get_by_email(str(data.email))

        if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="E-mail ou senha inválidos.",
            )

        token = create_access_token(
            subject=user.id,
            extra_claims={"role_id": user.role_id, "email": user.email},
        )

        return TokenResponse(access_token=token, user=user)


    async def get_completion_status(self, user: User) -> UserCompletionResponse:
        try:
            role_id = RoleId(user.role_id)
        except ValueError:
            return UserCompletionResponse(
                role_id=user.role_id,
                role_key="UNKNOWN",
                is_complete=False,
                next_path="/profile",
                message="Perfil de usuário inválido.",
                missing_steps=["Perfil inválido"],
            )

        if role_id == RoleId.ADMIN:
            return UserCompletionResponse(role_id=user.role_id, role_key="ADMIN", is_complete=True)

        if role_id == RoleId.COMPANY:
            company = await self.company_repository.get_by_owner_user_id(user.id)
            address = company.address if company is not None else None
            has_location = bool(address and address.latitude is not None and address.longitude is not None)
            is_complete = bool(company and company.is_active and has_location)

            return UserCompletionResponse(
                role_id=user.role_id,
                role_key="COMPANY",
                is_complete=is_complete,
                next_path=None if is_complete else "/company/settings",
                message=None if is_complete else "Finalize o cadastro da empresa para liberar produtos, pedidos e entregas.",
                missing_steps=[] if is_complete else ["Cadastrar dados da empresa", "Cadastrar endereço com latitude e longitude"],
            )

        if role_id == RoleId.CUSTOMER:
            address = await self.customer_address_repository.get_default_by_user_id(user.id)
            has_location = bool(address and address.latitude is not None and address.longitude is not None)

            return UserCompletionResponse(
                role_id=user.role_id,
                role_key="CUSTOMER",
                is_complete=has_location,
                next_path=None if has_location else "/customer/addresses",
                message=None if has_location else "Cadastre um endereço padrão para explorar restaurantes e fazer pedidos.",
                missing_steps=[] if has_location else ["Cadastrar endereço padrão com latitude e longitude"],
            )

        if role_id == RoleId.COURIER:
            courier = await self.courier_repository.get_or_create_by_user_id(user.id)
            await self.session.commit()

            return UserCompletionResponse(
                role_id=user.role_id,
                role_key="COURIER",
                is_complete=courier is not None,
                next_path=None,
                message=None,
                missing_steps=[],
            )

        return UserCompletionResponse(
            role_id=user.role_id,
            role_key="UNKNOWN",
            is_complete=False,
            next_path="/profile",
            message="Perfil de usuário inválido.",
            missing_steps=["Perfil inválido"],
        )
