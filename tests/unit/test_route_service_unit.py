from decimal import Decimal

import pytest

from app.core.config import settings
from app.services.route_service import RouteDistanceService


class FakeOSRMResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeOSRMClient:
    captured_url = None
    captured_params = None
    captured_headers = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        FakeOSRMClient.captured_url = url
        FakeOSRMClient.captured_params = params
        FakeOSRMClient.captured_headers = headers
        return FakeOSRMResponse(
            {
                "code": "Ok",
                "routes": [
                    {
                        "distance": 3456.7,
                        "duration": 732.2,
                    }
                ],
            }
        )


class FailingOSRMClient(FakeOSRMClient):
    async def get(self, url, params=None, headers=None):
        raise RuntimeError("OSRM indisponível")


def enable_real_route_distance(monkeypatch):
    monkeypatch.setenv("ROUTE_DISTANCE_OSRM_ENABLED", "true")
    if hasattr(settings, "USE_REAL_ROUTE_DISTANCE"):
        monkeypatch.setattr(settings, "USE_REAL_ROUTE_DISTANCE", True)
    if hasattr(settings, "OSRM_BASE_URL"):
        monkeypatch.setattr(settings, "OSRM_BASE_URL", "https://osrm.test")


def disable_real_route_distance(monkeypatch):
    monkeypatch.setenv("ROUTE_DISTANCE_OSRM_ENABLED", "false")
    if hasattr(settings, "USE_REAL_ROUTE_DISTANCE"):
        monkeypatch.setattr(settings, "USE_REAL_ROUTE_DISTANCE", False)


@pytest.mark.asyncio
async def test_route_service_uses_osrm_distance_when_available(monkeypatch):
    import app.services.route_service as route_module

    enable_real_route_distance(monkeypatch)
    monkeypatch.setenv("OSRM_BASE_URL", "https://osrm.test")
    monkeypatch.setattr(route_module.httpx, "AsyncClient", FakeOSRMClient)

    result = await RouteDistanceService().get_delivery_distance(
        origin_latitude=Decimal("-23.550520"),
        origin_longitude=Decimal("-46.633308"),
        destination_latitude=Decimal("-23.561684"),
        destination_longitude=Decimal("-46.655981"),
    )

    assert result.source == "osrm"
    assert float(result.distance_km) == pytest.approx(3.457, abs=0.01)
    # Garante que as coordenadas foram enviadas no formato correto do OSRM: longitude,latitude.
    assert "-46.633308,-23.55052;-46.655981,-23.561684" in FakeOSRMClient.captured_url


@pytest.mark.asyncio
async def test_route_service_falls_back_to_haversine_when_osrm_fails(monkeypatch):
    import app.services.route_service as route_module

    enable_real_route_distance(monkeypatch)
    monkeypatch.setattr(route_module.httpx, "AsyncClient", FailingOSRMClient)

    result = await RouteDistanceService().get_delivery_distance(
        origin_latitude=Decimal("-23.550520"),
        origin_longitude=Decimal("-46.633308"),
        destination_latitude=Decimal("-23.561684"),
        destination_longitude=Decimal("-46.655981"),
    )

    assert result.source == "haversine"
    assert Decimal(str(result.distance_km)) > Decimal("0.00")


@pytest.mark.asyncio
async def test_route_service_can_disable_real_route_distance(monkeypatch):
    disable_real_route_distance(monkeypatch)

    result = await RouteDistanceService().get_delivery_distance(
        origin_latitude=Decimal("-23.550520"),
        origin_longitude=Decimal("-46.633308"),
        destination_latitude=Decimal("-23.561684"),
        destination_longitude=Decimal("-46.655981"),
    )

    assert result.source == "haversine"
