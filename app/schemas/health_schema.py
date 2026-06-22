from pydantic import BaseModel


class HealthResponse(BaseModel):
    app: str
    version: str
    env: str
    database: str
    missing_tables: list[str]
