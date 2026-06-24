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

## Variável para criptografia de tokens

As contas de pagamento salvam `access_token` e `refresh_token` criptografados.
Para desenvolvimento local, o `docker-compose.yml` já define `TOKEN_ENCRYPTION_KEY`.

Para gerar uma nova chave Fernet:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Ou, se sua máquina usa `python3`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Endpoints iniciais de contas de pagamento

Esta etapa conecta a conta Mercado Pago da empresa via OAuth, sem criar cobrança, checkout ou Pix real.

- `GET /api/companies/{company_id}/payment-accounts/mercado-pago/connect-url`
- `GET /api/payment-accounts/mercado-pago/callback`
- `GET /api/companies/{company_id}/payment-accounts`
- `DELETE /api/companies/{company_id}/payment-accounts/{account_id}`

O endpoint `connect-url` retorna a URL de autorização do Mercado Pago. Após a autorização, o Mercado Pago chama o callback do backend, que troca o `code` por tokens reais, salva os tokens criptografados e redireciona para o frontend.

Configure estas variáveis para usar OAuth real:

```env
MERCADO_PAGO_CLIENT_ID=
MERCADO_PAGO_CLIENT_SECRET=
MERCADO_PAGO_USE_PKCE=true
MERCADO_PAGO_REDIRECT_URI=http://localhost:8000/api/payment-accounts/mercado-pago/callback
MERCADO_PAGO_OAUTH_AUTHORIZE_URL=https://auth.mercadopago.com.br/authorization
MERCADO_PAGO_OAUTH_TOKEN_URL=https://api.mercadopago.com/oauth/token
MERCADO_PAGO_PAYMENTS_URL=https://api.mercadopago.com/v1/payments
MERCADO_PAGO_WEBHOOK_URL=https://seu-tunel-publico/api/payments/mercado-pago/webhook
MERCADO_PAGO_PIX_EXPIRATION_MINUTES=30
FRONTEND_MERCADO_PAGO_SUCCESS_URL=http://localhost:5173/company/mercado-pago?connected=true
FRONTEND_MERCADO_PAGO_ERROR_URL=http://localhost:5173/company/mercado-pago?connected=false
```

Quando `MERCADO_PAGO_USE_PKCE=true`, o backend gera `code_verifier` e `code_challenge` no fluxo OAuth. O `code_verifier` fica apenas no backend e nunca é retornado ao frontend.

Os tokens nunca são retornados nas respostas e não devem ser enviados manualmente pelo frontend.

## Pix online Mercado Pago

Fluxo implementado no backend:

1. Cliente escolhe Pix online.
2. Backend cria o pedido como `AGUARDANDO_PAGAMENTO`.
3. Backend cria a cobrança Pix no Mercado Pago usando a conta conectada da empresa.
4. Frontend exibe QR Code e código Pix copia e cola.
5. Webhook/polling confirma o pagamento.
6. Quando o Mercado Pago retorna `approved`, o pedido vira `ABERTO` e é liberado para a empresa.

Endpoints principais:

- `GET /api/companies/{company_id}/payment-availability`
- `POST /api/orders/pix`
- `GET /api/orders/{order_id}/payment-status`
- `POST /api/orders/{order_id}/payments/pix/cancel`
- `POST /api/orders/{order_id}/payments/pix/regenerate`
- `PATCH /api/orders/{order_id}/payments/switch-to-delivery`
- `POST /api/payments/mercado-pago/webhook`

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
