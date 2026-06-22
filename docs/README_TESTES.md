# README_TESTES — Backend


O backend possui três grupos principais de testes:

```text
tests/unit      -> testes unitários de regras de negócio
tests/realtime  -> testes de Redis/WebSocket/serviços em tempo real
tests/e2e       -> teste E2E real do fluxo completo de pedido e entrega
```

## 1. Preparar ambiente

Entre na pasta do backend:

```bash
cd backend
```

Ative o ambiente virtual:

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

## 2. Rodar todos os testes leves

Os testes leves são os unitários e os de realtime. Eles não precisam da API rodando.

```bash
pytest tests/unit tests/realtime -q
```

Ou, com mais detalhes:

```bash
pytest tests/unit tests/realtime -vv
```

## 3. Rodar apenas testes unitários

```bash
pytest tests/unit -q
```

Esses testes validam regras como:

```text
cálculo da taxa de entrega
código de confirmação de 4 dígitos
cálculo de distância/fallback
validação de endereço
```

## 4. Rodar apenas testes de realtime

```bash
pytest tests/realtime -q
```

Esses testes validam partes como:

```text
publicação de eventos em tempo real
tratamento de falha no Redis
gerenciador de conexões WebSocket
broadcast de localização
```

## 5. Rodar todos os testes comuns

```bash
pytest -q
```

Esse comando roda os testes encontrados em `tests/`.

O teste E2E real só executa de verdade quando a variável `RUN_LIVE_E2E=true` está ativa. Sem essa variável, ele é ignorado automaticamente.

## 6. Rodar o teste E2E real

O teste E2E real valida o fluxo completo:

```text
cliente cria pedido
empresa aceita pedido
empresa libera para entrega
entregador visualiza a entrega disponível
entregador aceita a entrega
cliente recebe código de 4 dígitos
entregador tenta código inválido
entregador finaliza com código correto
pedido fica ENTREGUE
entrega fica FINALIZADA
```

### 6.1. Subir PostgreSQL e Redis

Na raiz do repositório principal, rode:

```bash
docker compose up -d postgres redis
```

### 6.2. Rodar o backend

Em outro terminal, dentro da pasta `backend`:

```bash
uvicorn app.main:app --reload
```

Confirme se a API abriu em:

```text
http://localhost:8000/docs
```

### 6.3. Executar o E2E no Git Bash

Em outro terminal, dentro da pasta `backend`:

```bash
RUN_LIVE_E2E=true pytest tests/e2e/test_full_delivery_lifecycle_live.py -q
```

### 6.4. Executar o E2E no PowerShell

```powershell
$env:RUN_LIVE_E2E="true"
pytest tests/e2e/test_full_delivery_lifecycle_live.py -q
```

## 7. Rodar absolutamente tudo

Com PostgreSQL, Redis e backend já rodando, use:

### Git Bash

```bash
RUN_LIVE_E2E=true pytest tests -q
```

### PowerShell

```powershell
$env:RUN_LIVE_E2E="true"
pytest tests -q
```

## 8. Variável opcional do E2E

Por padrão, o E2E usa:

```text
http://localhost:8000/api
```

Se precisar mudar:

### Git Bash

```bash
E2E_API_URL=http://localhost:8000/api RUN_LIVE_E2E=true pytest tests/e2e/test_full_delivery_lifecycle_live.py -q
```

### PowerShell

```powershell
$env:E2E_API_URL="http://localhost:8000/api"
$env:RUN_LIVE_E2E="true"
pytest tests/e2e/test_full_delivery_lifecycle_live.py -q
```

## 9. Comandos rápidos

Rodar unitários:

```bash
pytest tests/unit -q
```

Rodar realtime:

```bash
pytest tests/realtime -q
```

Rodar unitários + realtime:

```bash
pytest tests/unit tests/realtime -q
```

Rodar E2E real:

```bash
RUN_LIVE_E2E=true pytest tests/e2e/test_full_delivery_lifecycle_live.py -q
```

Rodar tudo com E2E:

```bash
RUN_LIVE_E2E=true pytest tests -q
```

## 10. Observação

O teste E2E real é mais pesado porque depende de:

```text
PostgreSQL rodando
Redis rodando
backend rodando
API acessível em localhost:8000
```

Para validação rápida durante desenvolvimento, rode primeiro:

```bash
pytest tests/unit tests/realtime -q
```


Durante a execução do teste e2e, perceba que as rotas são chamadas em tempo real dentro do backend.

Ao se deparar com a requisição:

```
127.0.0.1:58982 - "PATCH /api/deliveries/9/finish HTTP/1.1" 422 Unprocessable Entity
```

Não se preocupe pois é o teste fazendo com que o entregador tente finalizar a rota com o código errado.