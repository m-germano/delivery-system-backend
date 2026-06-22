from __future__ import annotations

import math
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None


@dataclass(frozen=True)
class RouteDistanceResult:
    distance_km: float
    source: str

    def __float__(self) -> float:
        return self.distance_km

    def __str__(self) -> str:
        return str(self.distance_km)


def _to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)

    return float(value)


def calculate_distance_km(
    origin_latitude: float | Decimal,
    origin_longitude: float | Decimal,
    destination_latitude: float | Decimal,
    destination_longitude: float | Decimal,
) -> float:
    """
    Fallback por Haversine.
    Calcula a distância aproximada em linha reta entre dois pontos.
    """
    origin_lat = _to_float(origin_latitude)
    origin_lng = _to_float(origin_longitude)
    destination_lat = _to_float(destination_latitude)
    destination_lng = _to_float(destination_longitude)

    earth_radius_km = 6371.0

    delta_lat = math.radians(destination_lat - origin_lat)
    delta_lng = math.radians(destination_lng - origin_lng)

    lat_1 = math.radians(origin_lat)
    lat_2 = math.radians(destination_lat)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_1) * math.cos(lat_2) * math.sin(delta_lng / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(earth_radius_km * c, 3)


class RouteDistanceService:
    """
    Serviço de distância real por ruas.

    Fluxo:
    1. Tenta calcular distância real por rota usando OSRM.
    2. Se OSRM falhar, usa Haversine como fallback.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("OSRM_BASE_URL")
            or "https://router.project-osrm.org"
        ).rstrip("/")

        self.timeout_seconds = timeout_seconds or float(
            os.getenv("ROUTE_DISTANCE_TIMEOUT_SECONDS", "6")
        )

        if enabled is None:
            enabled_value = os.getenv("ROUTE_DISTANCE_OSRM_ENABLED", "true").strip().lower()
            self.enabled = enabled_value not in {"0", "false", "no", "off"}
        else:
            self.enabled = enabled

    async def get_delivery_distance(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> RouteDistanceResult:
        """
        Método usado pelo OrderService.

        Retorna um objeto com:
        - distance_km: distância usada no cálculo
        - source: 'osrm' ou 'haversine'
        """
        return await self.get_distance_result(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
        )

    async def get_distance_result(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> RouteDistanceResult:
        fallback_distance = calculate_distance_km(
            origin_latitude,
            origin_longitude,
            destination_latitude,
            destination_longitude,
        )

        if not self.enabled or httpx is None:
            return RouteDistanceResult(
                distance_km=fallback_distance,
                source="haversine",
            )

        try:
            route_distance = await self._get_osrm_distance_km(
                origin_latitude=origin_latitude,
                origin_longitude=origin_longitude,
                destination_latitude=destination_latitude,
                destination_longitude=destination_longitude,
            )

            if route_distance is None or route_distance <= 0:
                return RouteDistanceResult(
                    distance_km=fallback_distance,
                    source="haversine",
                )

            return RouteDistanceResult(
                distance_km=route_distance,
                source="osrm",
            )
        except Exception:
            return RouteDistanceResult(
                distance_km=fallback_distance,
                source="haversine",
            )

    async def get_distance_km(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> float:
        result = await self.get_distance_result(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
        )

        return result.distance_km

    async def calculate_distance_km(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> float:
        return await self.get_distance_km(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
        )

    async def get_route_distance_km(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> float:
        return await self.get_distance_km(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
        )

    async def calculate_delivery_distance_km(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> float:
        return await self.get_distance_km(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
        )

    async def calculate(
        self,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> float:
        return await self.get_distance_km(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
        )

    async def _get_osrm_distance_km(
        self,
        *,
        origin_latitude: float | Decimal,
        origin_longitude: float | Decimal,
        destination_latitude: float | Decimal,
        destination_longitude: float | Decimal,
    ) -> float | None:
        if httpx is None:
            return None

        origin_lat = _to_float(origin_latitude)
        origin_lng = _to_float(origin_longitude)
        destination_lat = _to_float(destination_latitude)
        destination_lng = _to_float(destination_longitude)

        # OSRM usa longitude,latitude — não latitude,longitude.
        coordinates = f"{origin_lng},{origin_lat};{destination_lng},{destination_lat}"

        url = f"{self.base_url}/route/v1/driving/{coordinates}"

        params = {
            "overview": "false",
            "alternatives": "false",
            "steps": "false",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        data = response.json()

        if data.get("code") != "Ok":
            return None

        routes = data.get("routes") or []

        if not routes:
            return None

        distance_meters = routes[0].get("distance")

        if distance_meters is None:
            return None

        return round(float(distance_meters) / 1000, 3)