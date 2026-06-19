from app.repositories.product_repository import ProductRepository


class ProductService:
    def __init__(self, repository: ProductRepository):
        self.repository = repository

    async def list_available(self):
        return await self.repository.list_available()
