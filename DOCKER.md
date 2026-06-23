# Docker para desenvolvimento local

Esta stack sobe apenas o backend FastAPI e suas dependências locais:

- PostgreSQL
- Redis
- Backend FastAPI

O frontend React/Vite não é dockerizado neste fluxo. Ele deve continuar rodando manualmente no host.

## Subir o backend

```bash
docker compose up --build
```

## Parar os containers

```bash
docker compose down
```

## Apagar containers e volumes

Use este comando quando quiser recriar o banco e o Redis do zero:

```bash
docker compose down -v
```

## Ver logs do backend

```bash
docker compose logs -f backend
```

## Rodar testes dentro do container

```bash
docker compose exec backend pytest
```

## Rodar o frontend manualmente

Em outro terminal:

```bash
cd ../delivery-system-frontend
npm run dev
```

## Variáveis do frontend

Configure o `.env` do frontend para acessar a API exposta pelo backend no host:

```env
VITE_API_URL=http://localhost:8000/api
VITE_WS_URL=ws://localhost:8000
```
