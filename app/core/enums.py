from enum import IntEnum, StrEnum


class RoleId(IntEnum):
    ADMIN = 1
    COMPANY = 2
    COURIER = 3
    CUSTOMER = 4


class RoleName(StrEnum):
    ADMIN = "ADMIN"
    COMPANY = "COMPANY"
    COURIER = "COURIER"
    CUSTOMER = "CUSTOMER"


class OrderStatus(StrEnum):
    OPEN = "ABERTO"
    ACCEPTED = "ACEITO"
    IN_PREPARATION = "EM_PREPARO"
    WAITING_COURIER = "AGUARDANDO_ENTREGADOR"
    OUT_FOR_DELIVERY = "EM_ENTREGA"
    DELIVERED = "ENTREGUE"
    CANCELED = "CANCELADO"
    REJECTED = "RECUSADO"


class DeliveryStatus(StrEnum):
    AVAILABLE = "DISPONIVEL"
    ACCEPTED = "ACEITA"
    PICKED_UP = "RETIRADA"
    ON_ROUTE = "EM_ROTA"
    FINISHED = "FINALIZADA"
    CANCELED = "CANCELADA"


class PaymentMethod(StrEnum):
    CREDIT = "CREDITO"
    DEBIT = "DEBITO"
    PIX = "PIX"
    CASH = "DINHEIRO"
