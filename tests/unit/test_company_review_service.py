from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.enums import OrderStatus, RoleId
from app.schemas.company_review_schema import CompanyReviewCreateRequest
from app.services.company_review_service import CompanyReviewService


class FakeSession:
    async def commit(self):
        return None


class FakeOrderRepository:
    def __init__(self, order):
        self.order = order

    async def get_by_id(self, order_id):
        if self.order and self.order.id == order_id:
            return self.order
        return None


class FakeCompanyRepository:
    def __init__(self, company=None):
        self.company = company

    async def get_by_id(self, company_id):
        if self.company and self.company.id == company_id:
            return self.company
        return None

    async def get_by_owner_user_id(self, owner_user_id):
        if self.company and self.company.owner_user_id == owner_user_id:
            return self.company
        return None


class FakeReviewRepository:
    def __init__(self, existing_review=None):
        self.existing_review = existing_review
        self.created_review = None

    async def get_by_order_id(self, order_id):
        return self.existing_review

    async def create(self, review):
        self.created_review = review
        review.id = 99
        review.created_at = datetime(2026, 6, 24, 12, 0, 0)
        review.updated_at = datetime(2026, 6, 24, 12, 0, 0)
        return review

    async def list_by_company(self, company_id, *, limit=10, offset=0):
        return [], 0

    async def get_summary_by_company(self, company_id):
        return None, 0


def make_user(user_id=7, role_id=RoleId.CUSTOMER):
    return SimpleNamespace(id=user_id, role_id=role_id)


def make_order(status=OrderStatus.DELIVERED.value, customer_user_id=7):
    return SimpleNamespace(
        id=10,
        company_id=3,
        customer_user_id=customer_user_id,
        status=status,
    )


def make_service(order, existing_review=None):
    service = CompanyReviewService(FakeSession())
    service.order_repository = FakeOrderRepository(order)
    service.company_repository = FakeCompanyRepository(SimpleNamespace(id=3, owner_user_id=55))
    service.review_repository = FakeReviewRepository(existing_review=existing_review)
    return service


@pytest.mark.asyncio
async def test_customer_can_review_own_delivered_order():
    service = make_service(make_order())
    review = await service.create_order_review(
        10,
        CompanyReviewCreateRequest(rating=5, comment="Muito bom!"),
        make_user(),
    )

    assert review.company_id == 3
    assert review.customer_user_id == 7
    assert review.order_id == 10
    assert review.rating == 5
    assert review.comment == "Muito bom!"


@pytest.mark.asyncio
async def test_customer_can_review_own_picked_up_order():
    service = make_service(make_order(status=OrderStatus.PICKED_UP.value))
    review = await service.create_order_review(
        10,
        CompanyReviewCreateRequest(rating=4, comment=None),
        make_user(),
    )

    assert review.rating == 4


@pytest.mark.asyncio
async def test_review_requires_finalized_order():
    service = make_service(make_order(status=OrderStatus.OPEN.value))

    with pytest.raises(HTTPException) as exc_info:
        await service.create_order_review(10, CompanyReviewCreateRequest(rating=5), make_user())

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_review_requires_order_owner():
    service = make_service(make_order(customer_user_id=99))

    with pytest.raises(HTTPException) as exc_info:
        await service.create_order_review(10, CompanyReviewCreateRequest(rating=5), make_user(user_id=7))

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_review_is_unique_per_order():
    existing_review = SimpleNamespace(id=1, order_id=10)
    service = make_service(make_order(), existing_review=existing_review)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_order_review(10, CompanyReviewCreateRequest(rating=5), make_user())

    assert exc_info.value.status_code == 409


def test_review_rating_must_be_between_one_and_five():
    with pytest.raises(ValidationError):
        CompanyReviewCreateRequest(rating=0)

    with pytest.raises(ValidationError):
        CompanyReviewCreateRequest(rating=6)
