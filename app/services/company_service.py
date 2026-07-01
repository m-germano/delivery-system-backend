from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CompanyAddress, CompanyOrderSettings, User
from app.repositories.company_repository import CompanyRepository
from app.repositories.company_review_repository import CompanyReviewRepository
from app.repositories.customer_address_repository import CustomerAddressRepository
from app.schemas.company_schema import (
    CompanyCreateRequest,
    CompanyNearbyResponse,
    CompanyOpenStatusRequest,
    CompanyResponse,
    CompanyUpdateRequest,
)
from app.services.address_service import AddressService
from app.services.delivery_fee_service import DeliveryFeeCalculator, calculate_distance_km


class CompanyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.company_repository = CompanyRepository(session)
        self.company_review_repository = CompanyReviewRepository(session)
        self.customer_address_repository = CustomerAddressRepository(session)
        self.address_service = AddressService()
        self.delivery_fee_calculator = DeliveryFeeCalculator()

    async def list_active_companies(self, *, limit: int = 50, offset: int = 0) -> list[Company]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        companies = await self.company_repository.list_active(limit=safe_limit, offset=safe_offset)
        await self._attach_review_summaries(companies)
        return companies

    async def list_nearby_companies_for_customer(
        self,
        current_user: User,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyNearbyResponse]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)

        customer_address = await self.customer_address_repository.get_default_by_user_id(current_user.id)

        if customer_address is None or customer_address.latitude is None or customer_address.longitude is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cadastre um endereço padrão antes de consultar restaurantes próximos.",
            )

        companies = await self.company_repository.list_active(limit=safe_limit, offset=safe_offset)
        await self._attach_review_summaries(companies)
        nearby_companies: list[CompanyNearbyResponse] = []

        for company in companies:
            if company.address is None:
                continue

            if company.address.latitude is None or company.address.longitude is None:
                continue

            distance_km = calculate_distance_km(
                customer_address.latitude,
                customer_address.longitude,
                company.address.latitude,
                company.address.longitude,
            )

            delivery_fee = self.delivery_fee_calculator.calculate_for_company(company, distance_km)

            base_company_data = CompanyResponse.model_validate(company).model_dump()

            nearby_companies.append(
                CompanyNearbyResponse(
                    **base_company_data,
                    distance_km=distance_km,
                    delivery_fee=delivery_fee,
                )
            )

        nearby_companies.sort(key=lambda item: (item.distance_km, item.name.lower()))

        return nearby_companies

    async def get_company(self, company_id: int) -> Company:
        company = await self.company_repository.get_by_id(company_id)

        if company is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Empresa não encontrada.",
            )

        await self._attach_review_summary(company)
        return company

    async def get_my_company(self, current_user: User) -> Company:
        company = await self.company_repository.get_by_owner_user_id(current_user.id)

        if company is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Empresa ainda não configurada para este usuário.",
            )

        await self._attach_review_summary(company)
        return company

    async def create_company(self, data: CompanyCreateRequest, current_user: User) -> Company:
        existing_company = await self.company_repository.get_by_owner_user_id(current_user.id)

        if existing_company is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este usuário já possui uma empresa cadastrada.",
            )

        completed_address = await self.address_service.complete_company_address(
            data.address,
            auto_fill_address=data.auto_fill_address,
            auto_geocode=data.auto_geocode,
        )

        company = Company(
            owner_user_id=current_user.id,
            name=data.name.strip(),
            description=data.description,
            phone=data.phone,
            document=data.document,
            image_url=data.image_url,
            is_active=True,
            is_open=False,
        )

        self.session.add(company)
        await self.session.flush()

        self.session.add(
            CompanyAddress(
                company_id=company.id,
                street=str(completed_address.street),
                number=completed_address.number,
                complement=completed_address.complement,
                neighborhood=str(completed_address.neighborhood),
                city=str(completed_address.city),
                state=str(completed_address.state),
                zip_code=completed_address.zip_code,
                latitude=completed_address.latitude,
                longitude=completed_address.longitude,
            )
        )
        self.session.add(CompanyOrderSettings(company_id=company.id))

        await self.session.commit()

        return await self.get_my_company(current_user)

    async def update_my_company_open_status(self, data: CompanyOpenStatusRequest, current_user: User) -> Company:
        company = await self.get_my_company(current_user)

        company.is_open = data.is_open
        await self.session.commit()

        return await self.get_my_company(current_user)

    async def _attach_review_summaries(self, companies: list[Company]) -> None:
        summaries = await self.company_review_repository.get_summaries_by_company_ids([company.id for company in companies])
        for company in companies:
            average_rating, reviews_count = summaries.get(company.id, (None, 0))
            setattr(company, "average_rating", average_rating)
            setattr(company, "reviews_count", reviews_count)

    async def _attach_review_summary(self, company: Company) -> None:
        average_rating, reviews_count = await self.company_review_repository.get_summary_by_company(company.id)
        setattr(company, "average_rating", average_rating)
        setattr(company, "reviews_count", reviews_count)

    async def update_my_company(self, data: CompanyUpdateRequest, current_user: User) -> Company:
        company = await self.get_my_company(current_user)

        completed_address = await self.address_service.complete_company_address(
            data.address,
            auto_fill_address=data.auto_fill_address,
            auto_geocode=data.auto_geocode,
        )

        company.name = data.name.strip()
        company.description = data.description
        company.phone = data.phone
        company.document = data.document
        company.image_url = data.image_url

        if company.address is None:
            company.address = CompanyAddress(company_id=company.id)

        company.address.street = str(completed_address.street)
        company.address.number = completed_address.number
        company.address.complement = completed_address.complement
        company.address.neighborhood = str(completed_address.neighborhood)
        company.address.city = str(completed_address.city)
        company.address.state = str(completed_address.state)
        company.address.zip_code = completed_address.zip_code
        company.address.latitude = completed_address.latitude
        company.address.longitude = completed_address.longitude

        await self.session.commit()

        return await self.get_my_company(current_user)
