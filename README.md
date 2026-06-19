# Delivery System Backend

Backend do Sistema de Delivery com Python, FastAPI e PostgreSQL.

## Estrutura

```txt
app/
├── controllers/
├── services/
├── repositories/
├── models/
├── schemas/
├── core/
└── db/
```

## Setup local

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Acesse: http://localhost:8000/docs

## Testes

```bash
pytest
```
