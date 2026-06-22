import pytest
from fastapi import HTTPException

from app.services.address_service import AddressService


def test_normalize_zip_code_accepts_formatted_zip_code():
    assert AddressService.normalize_zip_code("01001-000") == "01001000"


def test_normalize_zip_code_rejects_invalid_zip_code():
    with pytest.raises(HTTPException):
        AddressService.normalize_zip_code("123")
