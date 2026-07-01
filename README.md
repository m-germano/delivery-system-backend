# DishDash / Delivery System — Backend

API backend do **DishDash / Delivery System**, desenvolvida com **FastAPI**, **PostgreSQL** e **Redis**.
O backend concentra autenticação, cadastro de empresas, catálogo de produtos, pedidos, entrega/retirada, pagamentos via Mercado Pago, avaliações de restaurantes, acompanhamento em tempo real e regras operacionais do sistema.

## Sumário

- [Principais funcionalidades](#principais-funcionalidades)
- [Tecnologias utilizadas](#tecnologias-utilizadas)
- [Serviços externos](#serviços-externos)
- [Pré-requisitos](#pré-requisitos)
- [Configuração do ambiente](#configuração-do-ambiente)
- [Rodando com Docker Compose](#rodando-com-docker-compose)
- [Rodando manualmente](#rodando-manualmente)
- [Integração Mercado Pago](#integração-mercado-pago)
- [Webhook Mercado Pago com ngrok](#webhook-mercado-pago-com-ngrok)
- [Fluxo de pagamento Pix online](#fluxo-de-pagamento-pix-online)
- [Entrega, retirada e pedidos](#entrega-retirada-e-pedidos)
- [Avaliações de restaurantes](#avaliações-de-restaurantes)
- [Testes](#testes)
- [Observações de segurança](#observações-de-segurança)

## Principais funcionalidades

### Autenticação e perfis

- Cadastro e login de usuários.
- Autenticação com JWT.
- Controle de perfis como cliente, empresa/restaurante e entregador.
- Hash de senha com Argon2.
- Fluxo de completar cadastro conforme perfil.

### Empresas/restaurantes

- Cadastro e gerenciamento de empresas.
- Endereço da empresa.
- Catálogo de produtos.
- Configurações operacionais da empresa:
  - aceitar delivery;
  - aceitar retirada;
  - aceitar ambos;
  - configurar valor mínimo de pedido;
  - configurar desconto percentual para retirada.

### Pedidos

- Criação de pedidos para delivery e retirada.
- Cálculo de subtotal, desconto, taxa de entrega e total.
- Pedido mínimo configurável por empresa.
- Fluxo de status para delivery.
- Fluxo de status para retirada.
- Código de confirmação para entrega/retirada.
- Cancelamento e recusa de pedido.
- Histórico de status.

### Delivery e motoboy

- Cadastro de entregador.
- Controle de disponibilidade.
- Listagem de entregas disponíveis.
- Aceite de entrega.
- Rastreamento de localização.
- Atualizações via WebSocket.
- Pedidos de retirada **não** geram registros de entrega e **não aparecem para motoboy**.

### Retirada na loja

- Cliente pode escolher retirada no checkout quando a empresa aceitar esse modo.
- Retirada não exige endereço do cliente.
- Retirada não cobra taxa de entrega.
- Pode aplicar desconto configurado pela loja.
- Pode ter pagamento presencial ou Pix online Mercado Pago.
- Quando o pedido fica pronto, o sistema gera um código para o cliente informar à loja.
- A loja precisa informar o código correto para marcar o pedido como retirado.

### Pagamentos Mercado Pago

- Conexão da conta Mercado Pago da empresa via OAuth.
- Armazenamento criptografado dos tokens.
- Pix online para delivery e retirada.
- Webhook para atualização de status do pagamento.
- Fallback no status de pagamento para evitar pedido travado.
- Reembolso automático ao recusar/cancelar pedidos pagos pela plataforma.

### Avaliações de restaurantes

- Cliente pode avaliar uma empresa após finalizar um pedido.
- Avaliação com 1 a 5 estrelas e comentário.
- Uma avaliação por pedido.
- Média de avaliações por empresa.
- Listagem pública de avaliações da empresa.
- Tela de avaliações para a empresa visualizar feedbacks recebidos.

## Tecnologias utilizadas

- **Python 3.11**
- **FastAPI** para API REST e WebSockets
- **Uvicorn** como servidor ASGI
- **SQLAlchemy 2 Async** para acesso ao banco
- **asyncpg** como driver PostgreSQL assíncrono
- **PostgreSQL** como banco principal
- **Redis Pub/Sub** para eventos em tempo real
- **Pydantic / pydantic-settings** para schemas e configurações
- **PyJWT** para autenticação JWT
- **pwdlib[argon2]** para hash de senhas
- **cryptography/Fernet** para criptografia de tokens sensíveis
- **httpx** para chamadas HTTP externas
- **pytest** para testes

## Serviços externos

- **Mercado Pago**
  - OAuth para conectar contas das empresas.
  - Pix online.
  - Webhooks de pagamento.
  - Reembolso automático.
- **ViaCEP**
  - Busca de endereço por CEP.
- **Nominatim / OpenStreetMap**
  - Geocodificação de endereços.
- **OSRM**
  - Cálculo de distância real por ruas.
- **ngrok**
  - Exposição local do backend via HTTPS para testes de OAuth e webhook Mercado Pago.

## Pré-requisitos

- Python 3.11+
- Docker e Docker Compose
- PostgreSQL, caso rode sem Docker
- Redis, caso rode sem Docker
- Conta Mercado Pago Developers, se for testar Pix online
- ngrok, se for testar OAuth/webhook localmente

## Configuração do ambiente

Crie o arquivo `.env` na raiz do backend a partir do exemplo:

```bash
cp .env.example .env
```

Gere a chave de criptografia usada para proteger tokens do Mercado Pago:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copie o valor gerado para:

```env
TOKEN_ENCRYPTION_KEY=
```

Use uma `SECRET_KEY` forte, com pelo menos 32 caracteres.

## Rodando com Docker Compose

Na raiz do backend:

```bash
docker compose up --build
```

Para recriar os containers:

```bash
docker compose down
docker compose up --build --force-recreate
```

A API ficará disponível em:

```text
http://localhost:8000
```

Documentação Swagger:

```text
http://localhost:8000/docs
```

## Rodando manualmente

Crie e ative o ambiente virtual:

```bash
python3 -m venv venv
source venv/bin/activate
```

No Windows com Git Bash:

```bash
python -m venv venv
source venv/Scripts/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Suba PostgreSQL e Redis, ou configure `DATABASE_URL` e `REDIS_URL` apontando para serviços já existentes.

Execute a API:

```bash
uvicorn app.main:app --reload
```

## Integração Mercado Pago

### 1. Criar aplicação no Mercado Pago Developers

No painel do Mercado Pago Developers, crie uma aplicação para pagamentos online.

Configurações usadas no projeto:

- Tipo de integração: desenvolvimento próprio.
- Pagamentos online.
- Checkout/API de pagamentos.
- OAuth habilitado para conectar contas das empresas.
- Webhooks habilitados para evento de pagamentos.

### 2. Configurar OAuth

No `.env`, configure:

```env
MERCADO_PAGO_CLIENT_ID=
MERCADO_PAGO_CLIENT_SECRET=
MERCADO_PAGO_USE_PKCE=true
MERCADO_PAGO_REDIRECT_URI=https://SUA_URL_HTTPS/api/payment-accounts/mercado-pago/callback
MERCADO_PAGO_OAUTH_AUTHORIZE_URL=https://auth.mercadopago.com.br/authorization
MERCADO_PAGO_OAUTH_TOKEN_URL=https://api.mercadopago.com/oauth/token
FRONTEND_MERCADO_PAGO_SUCCESS_URL=http://localhost:5173/company/mercado-pago?connected=true
FRONTEND_MERCADO_PAGO_ERROR_URL=http://localhost:5173/company/mercado-pago?connected=false
```

A `MERCADO_PAGO_REDIRECT_URI` deve ser a mesma cadastrada no portal Mercado Pago.

Em ambiente local, o Mercado Pago exige HTTPS, então use ngrok.

### 3. Conectar conta da empresa

Com backend e frontend rodando:

1. Acesse a área da empresa no frontend.
2. Abra a tela de integração Mercado Pago.
3. Clique para conectar.
4. O usuário será redirecionado ao Mercado Pago.
5. Após autorizar, o Mercado Pago chama o callback do backend.
6. O backend salva os tokens criptografados.

## Webhook Mercado Pago com ngrok

Instale e configure o ngrok. Link para download: https://ngrok.com/download

Configure seu authtoken com o comando abaixo:
```bash
ngrok config add-authtoken "<YOUR_AUTHTOKEN>"
```
Para testar webhooks localmente, rode:

```bash
ngrok http 8000
```

O ngrok exibirá uma URL parecida com:

```text
https://sua-url.ngrok-free.dev -> http://localhost:8000
```

Configure no `.env`:

```env
MERCADO_PAGO_REDIRECT_URI=https://sua-url.ngrok-free.dev/api/payment-accounts/mercado-pago/callback
MERCADO_PAGO_WEBHOOK_URL=https://sua-url.ngrok-free.dev/api/payments/mercado-pago/webhook
```

No portal do Mercado Pago, configure:

```text
Redirect URL:
https://sua-url.ngrok-free.dev/api/payment-accounts/mercado-pago/callback
```

```text
Webhook URL:
https://sua-url.ngrok-free.dev/api/payments/mercado-pago/webhook
```

Evento do webhook:

```text
Pagamentos
```

Depois de alterar o `.env`, recrie o backend:

```bash
docker compose down
docker compose up --build --force-recreate
```

### Assinatura secreta do webhook

O Mercado Pago pode gerar uma assinatura secreta para validação do webhook.

Configure:

```env
MERCADO_PAGO_WEBHOOK_SECRET=
```

Essa chave permite validar que a notificação recebida veio do Mercado Pago. Nunca exponha essa chave em commits, prints públicos ou logs.

## Fluxo de pagamento Pix online

1. Cliente escolhe delivery ou retirada.
2. Cliente escolhe Pix online, se a empresa tiver Mercado Pago conectado.
3. Backend cria pedido com status de aguardando pagamento.
4. Backend cria cobrança Pix no Mercado Pago.
5. Frontend exibe QR Code e Pix copia e cola.
6. Mercado Pago notifica o backend via webhook.
7. Backend consulta o pagamento no Mercado Pago antes de confiar no evento.
8. Se aprovado:
   - payment vira `approved`;
   - pedido é liberado para a loja;
   - pedido deixa de ficar aguardando pagamento.
9. Se a loja recusar ou cancelar um pedido pago online:
   - backend solicita reembolso no Mercado Pago;
   - payment vira `refunded` se o reembolso for confirmado.

## Entrega, retirada e pedidos

A empresa pode configurar se aceita:

- somente delivery;
- somente retirada;
- delivery e retirada.

### Delivery

- Exige endereço do cliente.
- Calcula distância.
- Calcula taxa de entrega.
- Pode usar Pix online.
- Pode gerar entrega para motoboy.

### Retirada

- Não exige endereço do cliente.
- Não cobra taxa de entrega.
- Pode aplicar desconto.
- Pode usar pagamento presencial ou Pix online.
- Não gera entrega para motoboy.
- Não aparece em rotas de entregas disponíveis.
- Quando fica pronto, gera código para retirada.

## Avaliações de restaurantes

Após finalizar o pedido, o cliente pode avaliar a empresa:

- estrelas de 1 a 5;
- comentário;
- vínculo com pedido, cliente e empresa.

A média aparece nas listagens e detalhes da empresa. A empresa também possui uma tela para visualizar avaliações recebidas com paginação.

## Banco de dados

O projeto segue o padrão atual de inicialização automática:

- `Base.metadata.create_all()`
- SQL manual de compatibilidade no startup
- verificação de tabelas ao iniciar

As opções são controladas por:

```env
AUTO_CREATE_TABLES=true
VERIFY_TABLES_ON_STARTUP=true
```

## Testes

Rodar todos os testes:

```bash
pytest -q
```

Rodar testes dentro do Docker:

```bash
docker compose run --rm --no-deps backend pytest -q
```

## Observações de segurança

- Não commite `.env`.
- Não exponha `MERCADO_PAGO_CLIENT_SECRET`.
- Não exponha `MERCADO_PAGO_WEBHOOK_SECRET`.
- Não exponha `TOKEN_ENCRYPTION_KEY`.
- Não logue access tokens, refresh tokens ou headers Authorization.
- Depois de expor credenciais em chats, prints ou documentos, regenere-as no painel do Mercado Pago.
- Em produção, restrinja `CORS_ORIGINS` para os domínios reais do frontend.

## Comandos úteis

Entrar no PostgreSQL do Docker:

```bash
docker compose exec postgres psql -U delivery_user -d delivery_db
```

Ver variáveis Mercado Pago carregadas no backend:

```bash
docker compose exec backend printenv | grep MERCADO_PAGO
```

Subir ngrok:

```bash
ngrok http 8000
```
