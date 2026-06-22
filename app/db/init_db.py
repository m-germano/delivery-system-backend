from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.enums import RoleId, RoleName
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models import (  # noqa: F401 - garante registro dos models no metadata
    Company,
    CompanyAddress,
    Courier,
    CustomerAddress,
    Delivery,
    DeliveryFeeRule,
    DeliveryStatusHistory,
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    ProductCategory,
    Role,
    User,
)

REQUIRED_TABLES = {
    "roles",
    "users",
    "companies",
    "company_addresses",
    "product_categories",
    "products",
    "customer_addresses",
    "delivery_fee_rules",
    "orders",
    "order_items",
    "order_status_history",
    "couriers",
    "deliveries",
    "delivery_status_history",
}

INITIAL_ROLES = [
    {"id": RoleId.ADMIN, "name": RoleName.ADMIN, "description": "Administrador do sistema"},
    {"id": RoleId.COMPANY, "name": RoleName.COMPANY, "description": "Empresa/restaurante"},
    {"id": RoleId.COURIER, "name": RoleName.COURIER, "description": "Entregador"},
    {"id": RoleId.CUSTOMER, "name": RoleName.CUSTOMER, "description": "Cliente"},
]


async def check_database_connection() -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        return result.scalar_one() == 1


async def create_database_schema(db_engine: AsyncEngine = engine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_initial_roles() -> None:
    async with AsyncSessionLocal() as session:
        await _seed_initial_roles_with_session(session)


async def _seed_initial_roles_with_session(session: AsyncSession) -> None:
    for role_data in INITIAL_ROLES:
        role = await session.get(Role, int(role_data["id"]))
        if role is None:
            session.add(
                Role(
                    id=int(role_data["id"]),
                    name=str(role_data["name"]),
                    description=str(role_data["description"]),
                )
            )
    await session.commit()


async def list_existing_tables(db_engine: AsyncEngine = engine) -> set[str]:
    async with db_engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    return set(table_names)


async def get_missing_tables(db_engine: AsyncEngine = engine) -> set[str]:
    existing_tables = await list_existing_tables(db_engine)
    return REQUIRED_TABLES - existing_tables


async def ensure_schema_compatibility(db_engine: AsyncEngine = engine) -> None:
    """Pequena compatibilização para bancos locais criados antes da etapa de pedidos.

    O MVP iniciou com status CRIADO. A etapa atual usa ABERTO como status inicial.
    Como ainda não estamos usando Alembic, mantemos esta atualização simples para desenvolvimento.
    """
    existing_tables = await list_existing_tables(db_engine)
    if "orders" not in existing_tables:
        return

    async with db_engine.begin() as conn:
        await conn.execute(text("UPDATE orders SET status = 'ABERTO' WHERE status = 'CRIADO'"))
        await conn.execute(text("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'ABERTO'"))
        await conn.execute(text("UPDATE orders SET payment_method = 'PIX' WHERE payment_method IS NULL"))
        await conn.execute(text("ALTER TABLE orders ALTER COLUMN payment_method SET DEFAULT 'PIX'"))
        await conn.execute(text("ALTER TABLE orders ALTER COLUMN payment_method SET NOT NULL"))
        await conn.execute(text("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_status"))
        await conn.execute(text("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_payment_method"))
        await conn.execute(
            text(
                """
                ALTER TABLE orders
                ADD CONSTRAINT ck_orders_status
                CHECK (status IN ('ABERTO','ACEITO','EM_PREPARO','AGUARDANDO_ENTREGADOR','EM_ENTREGA','ENTREGUE','CANCELADO','RECUSADO'))
                """
            )
        )
        await conn.execute(
            text(
                """
                ALTER TABLE orders
                ADD CONSTRAINT ck_orders_payment_method
                CHECK (payment_method IN ('CREDITO','DEBITO','PIX','DINHEIRO'))
                """
            )
        )


async def verify_required_tables(db_engine: AsyncEngine = engine) -> None:
    missing_tables = await get_missing_tables(db_engine)
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise RuntimeError(f"Tabelas obrigatórias não encontradas: {missing}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Role.id))
        existing_role_ids = {row[0] for row in result.all()}

    expected_role_ids = {int(role["id"]) for role in INITIAL_ROLES}
    missing_roles = expected_role_ids - existing_role_ids
    if missing_roles:
        missing = ", ".join(str(role_id) for role_id in sorted(missing_roles))
        raise RuntimeError(f"Roles obrigatórias não encontradas: {missing}")
