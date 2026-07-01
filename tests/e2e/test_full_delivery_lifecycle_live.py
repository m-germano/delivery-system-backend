"""
E2E real do fluxo principal do DishDash.

Este teste é opcional e roda contra a API real em execução.
Ele valida o fluxo completo:

1. Cadastra empresa, cliente e entregador.
2. Empresa cria cadastro, abre a loja, cria categoria e produto.
3. Cliente cria endereço e pedido.
4. Empresa aceita o pedido e libera para entregador.
5. Entregador fica disponível, pega a entrega da fila e aceita.
6. Cliente visualiza o código de confirmação de 4 dígitos.
7. Entregador finaliza a entrega informando o código.
8. Pedido termina como ENTREGUE e entrega como FINALIZADA.

Como rodar:

    docker compose up -d postgres redis
    uvicorn app.main:app --reload

Em outro terminal:

    RUN_LIVE_E2E=true pytest tests/e2e/test_full_delivery_lifecycle_live.py -q

Variáveis opcionais:

    E2E_API_URL=http://localhost:8000/api
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest
import httpx


pytestmark = pytest.mark.live_e2e

API_URL = os.getenv("E2E_API_URL", "http://localhost:8000/api").rstrip("/")
RUN_LIVE_E2E = os.getenv("RUN_LIVE_E2E", "false").lower() in {"1", "true", "yes", "sim"}


class ApiSession:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.token: str | None = None

    @property
    def headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.client.post(f"{API_URL}{path}", headers=self.headers, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.client.get(f"{API_URL}{path}", headers=self.headers, **kwargs)

    def patch(self, path: str, **kwargs) -> httpx.Response:
        return self.client.patch(f"{API_URL}{path}", headers=self.headers, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.client.put(f"{API_URL}{path}", headers=self.headers, **kwargs)


def assert_success(response: httpx.Response, expected_status: int | set[int]) -> None:
    expected = {expected_status} if isinstance(expected_status, int) else expected_status
    assert response.status_code in expected, response.text


def register_and_login(client: httpx.Client, *, role_id: int, name: str, email: str, password: str) -> ApiSession:
    session = ApiSession(client)

    register_response = session.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "role_id": role_id,
            "phone": "12999990000",
        },
    )
    assert_success(register_response, {200, 201})

    login_response = session.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert_success(login_response, 200)

    payload = login_response.json()
    session.token = payload["access_token"]
    assert payload["user"]["role_id"] == role_id

    return session


def test_fluxo_completo_pedido_entrega_codigo_confirmacao() -> None:
    if not RUN_LIVE_E2E:
        pytest.skip("Teste E2E real desativado. Rode com RUN_LIVE_E2E=true.")

    unique = f"{int(time.time())}-{uuid4().hex[:8]}"
    password = "Senha123"

    with httpx.Client(timeout=30) as client:
        company = register_and_login(
            client,
            role_id=2,
            name="Restaurante E2E",
            email=f"empresa-{unique}@teste.com",
            password=password,
        )
        customer = register_and_login(
            client,
            role_id=4,
            name="Cliente E2E",
            email=f"cliente-{unique}@teste.com",
            password=password,
        )
        courier = register_and_login(
            client,
            role_id=3,
            name="Entregador E2E",
            email=f"entregador-{unique}@teste.com",
            password=password,
        )

        company_response = company.post(
            "/companies",
            json={
                "name": f"Restaurante E2E {unique}",
                "description": "Restaurante criado pelo teste E2E.",
                "phone": "12999990000",
                "document": f"DOC-{unique}",
                "image_url": None,
                "auto_fill_address": False,
                "auto_geocode": False,
                "address": {
                    "zip_code": "12243000",
                    "street": "Avenida Andrômeda",
                    "number": "1000",
                    "complement": None,
                    "neighborhood": "Jardim Satélite",
                    "city": "São José dos Campos",
                    "state": "SP",
                    "latitude": "-23.223700",
                    "longitude": "-45.900900",
                },
            },
        )
        assert_success(company_response, {200, 201})
        company_payload = company_response.json()
        company_id = company_payload["id"]
        assert company_payload["is_open"] is False

        open_company_response = company.patch(
            "/companies/me/open-status",
            json={"is_open": True},
        )
        assert_success(open_company_response, 200)
        assert open_company_response.json()["is_open"] is True

        category_response = company.post(
            "/product-categories",
            json={
                "name": "Lanches",
                "description": "Categoria criada pelo teste E2E.",
                "display_order": 1,
            },
        )
        assert_success(category_response, {200, 201})
        category_id = category_response.json()["id"]

        product_response = company.post(
            "/products",
            json={
                "category_id": category_id,
                "name": "X-Burger E2E",
                "description": "Produto criado pelo teste E2E.",
                "price": "25.00",
                "image_url": None,
                "is_active": True,
            },
        )
        assert_success(product_response, {200, 201})
        product_id = product_response.json()["id"]

        address_response = customer.post(
            "/customer-addresses",
            json={
                "auto_fill_address": False,
                "auto_geocode": False,
                "address": {
                    "label": "Casa E2E",
                    "zip_code": "12245000",
                    "street": "Rua Bacabal",
                    "number": "200",
                    "complement": None,
                    "neighborhood": "Parque Industrial",
                    "city": "São José dos Campos",
                    "state": "SP",
                    "latitude": "-23.239100",
                    "longitude": "-45.901700",
                    "is_default": True,
                },
            },
        )
        assert_success(address_response, {200, 201})
        customer_address_id = address_response.json()["id"]

        calculate_response = customer.post(
            "/orders/calculate",
            json={
                "company_id": company_id,
                "customer_address_id": customer_address_id,
                "payment_method": "PIX",
                "notes": "Pedido calculado pelo teste E2E.",
                "items": [{"product_id": product_id, "quantity": 2}],
            },
        )
        assert_success(calculate_response, 200)
        calculation = calculate_response.json()
        assert float(calculation["subtotal"]) == 50.0
        assert float(calculation["delivery_fee"]) >= 5.0
        assert float(calculation["total"]) >= 55.0

        order_response = customer.post(
            "/orders",
            json={
                "company_id": company_id,
                "customer_address_id": customer_address_id,
                "payment_method": "PIX",
                "notes": "Pedido criado pelo teste E2E.",
                "items": [{"product_id": product_id, "quantity": 2}],
            },
        )
        assert_success(order_response, {200, 201})
        order = order_response.json()
        order_id = order["id"]
        assert order["status"] == "ABERTO"

        accept_response = company.patch(f"/orders/{order_id}/accept")
        assert_success(accept_response, 200)
        assert accept_response.json()["status"] == "ACEITO"

        preparation_response = company.patch(
            f"/orders/{order_id}/status",
            json={"status": "EM_PREPARO"},
        )
        assert_success(preparation_response, 200)
        assert preparation_response.json()["status"] == "EM_PREPARO"

        waiting_courier_response = company.patch(
            f"/orders/{order_id}/status",
            json={"status": "AGUARDANDO_ENTREGADOR"},
        )
        assert_success(waiting_courier_response, 200)
        assert waiting_courier_response.json()["status"] == "AGUARDANDO_ENTREGADOR"

        availability_response = courier.patch(
            "/couriers/me/availability",
            json={
                "is_available": True,
                "vehicle_type": "Moto",
                "vehicle_plate": "ABC1D23",
                "current_latitude": "-23.230000",
                "current_longitude": "-45.900000",
            },
        )
        assert_success(availability_response, 200)
        assert availability_response.json()["is_available"] is True

        available_response = courier.get("/deliveries/available")
        assert_success(available_response, 200)
        available_items = available_response.json()["items"]
        delivery = next((item for item in available_items if item["order_id"] == order_id), None)
        assert delivery is not None, available_response.text
        delivery_id = delivery["id"]
        assert delivery["status"] == "DISPONIVEL"

        accept_delivery_response = courier.patch(f"/deliveries/{delivery_id}/accept")
        assert_success(accept_delivery_response, 200)
        accepted_delivery = accept_delivery_response.json()
        assert accepted_delivery["status"] == "EM_ROTA"
        assert accepted_delivery["courier_user_id"] is not None

        customer_orders_response = customer.get("/orders/my")
        assert_success(customer_orders_response, 200)
        customer_order = next(
            (item for item in customer_orders_response.json()["items"] if item["id"] == order_id),
            None,
        )
        assert customer_order is not None, customer_orders_response.text
        assert customer_order["status"] == "EM_ENTREGA"

        confirmation_code = customer_order.get("delivery_confirmation_code")
        assert confirmation_code is not None
        assert confirmation_code.isdigit()
        assert len(confirmation_code) == 4

        wrong_code_response = courier.patch(
            f"/deliveries/{delivery_id}/finish",
            json={"confirmation_code": "0000" if confirmation_code != "0000" else "9999"},
        )
        assert wrong_code_response.status_code in {400, 409, 422}, wrong_code_response.text

        finish_response = courier.patch(
            f"/deliveries/{delivery_id}/finish",
            json={"confirmation_code": confirmation_code},
        )
        assert_success(finish_response, 200)
        finished_delivery = finish_response.json()
        assert finished_delivery["status"] == "FINALIZADA"

        final_order_response = customer.get(f"/orders/{order_id}")
        assert_success(final_order_response, 200)
        final_order = final_order_response.json()
        assert final_order["status"] == "ENTREGUE"
