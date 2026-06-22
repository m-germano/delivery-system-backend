# Delivery System — Backend

API backend do DishDash/Delivery System, desenvolvida com FastAPI e PostgreSQL. O backend concentra autenticação, empresas, produtos, pedidos, entregas, cálculo de taxa por rota, acompanhamento em tempo real e eventos com Redis.

## Principais tecnologias

- **Python 3.11**
- **FastAPI** para criação da API REST e WebSockets
- **Uvicorn** como servidor ASGI
- **SQLAlchemy 2 Async** para acesso ao banco
- **asyncpg** como driver PostgreSQL assíncrono
- **PostgreSQL** como banco principal do sistema
- **Redis Pub/Sub** para eventos em tempo real
- **Pydantic / pydantic-settings** para schemas e configurações
- **PyJWT** para autenticação JWT
- **pwdlib[argon2]** para hash de senhas
- **httpx** para chamadas HTTP externas
- **pytest** para testes

## APIs e serviços externos utilizados

- **ViaCEP**: preenchimento de endereço a partir do CEP
- **Nominatim / OpenStreetMap**: geocodificação de endereços
- **OSRM**: cálculo de distância real por ruas entre empresa e cliente
- **Redis**: publicação de eventos em tempo real para pedidos e entregas

## Variáveis de ambiente principais

Crie um arquivo `.env` na raiz do backend. Exemplo mínimo:

```env
APP_NAME=Delivery System API
APP_ENV=development
APP_VERSION=0.1.0
API_PREFIX=/api

DATABASE_URL=postgresql+asyncpg://delivery_user:delivery_pass@localhost:5432/delivery_db
REDIS_URL=redis://localhost:6379/0
DATABASE_ECHO=false

AUTO_CREATE_TABLES=true
VERIFY_TABLES_ON_STARTUP=true

CORS_ORIGINS=["http://localhost:5173","http://localhost:4173","http://localhost:3000"]

SECRET_KEY=change-me-in-development
ACCESS_TOKEN_EXPIRE_MINUTES=1440
JWT_ALGORITHM=HS256

VIACEP_BASE_URL=https://viacep.com.br/ws
NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org
NOMINATIM_EMAIL=
GEOCODING_USER_AGENT=DeliverySystemAPI/0.1.0

OSRM_BASE_URL=https://router.project-osrm.org
ROUTE_DISTANCE_OSRM_ENABLED=true
ROUTE_DISTANCE_TIMEOUT_SECONDS=6
EXTERNAL_API_TIMEOUT_SECONDS=8
```

## Rodando PostgreSQL com Docker

```bash
docker run -d \
  --name delivery_postgres \
  -e POSTGRES_DB=delivery_db \
  -e POSTGRES_USER=delivery_user \
  -e POSTGRES_PASSWORD=delivery_pass \
  -p 5432:5432 \
  -v delivery_pgdata:/var/lib/postgresql/data \
  postgres:16-alpine
```

## Rodando Redis com Docker

```bash
docker run -d \
  --name delivery_redis \
  -p 6379:6379 \
  -v delivery_redis_data:/data \
  redis:7.2-alpine redis-server --appendonly yes
```

## Rodando o backend localmente

Crie e ative o ambiente virtual:

```bash
python -m venv venv
```

No Windows com Git Bash:

```bash
source venv/Scripts/activate
```

No Linux/macOS:

```bash
source venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Suba a API:

```bash
uvicorn app.main:app --reload
```

A API ficará disponível em:

```text
http://localhost:8000
```

Documentação automática:

```text
http://localhost:8000/docs
```

## Rodando testes

```bash
pytest -q
```

## Observações

- O PostgreSQL é a fonte oficial dos dados.
- O Redis é usado para eventos em tempo real, não para substituir o banco principal.
- O cálculo de entrega tenta usar distância real por ruas via OSRM e usa Haversine como fallback.
- O código de confirmação de entrega é gerado pelo backend e não precisa ser salvo no Redis.
