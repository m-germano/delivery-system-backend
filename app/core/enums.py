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
    PENDING_PAYMENT = "AGUARDANDO_PAGAMENTO"
    OPEN = "ABERTO"
    ACCEPTED = "ACEITO"
    IN_PREPARATION = "EM_PREPARO"
    READY_FOR_PICKUP = "PRONTO_PARA_RETIRADA"
    WAITING_COURIER = "AGUARDANDO_ENTREGADOR"
    OUT_FOR_DELIVERY = "EM_ENTREGA"
    DELIVERED = "ENTREGUE"
    PICKED_UP = "RETIRADO"
    CANCELED = "CANCELADO"
    REJECTED = "RECUSADO"


class FulfillmentType(StrEnum):
    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"


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
    PIX_ONLINE = "PIX_ONLINE"
    CASH = "DINHEIRO"


class PaymentProvider(StrEnum):
    MERCADO_PAGO = "mercado_pago"
    MANUAL = "manual"
    SIMULATED = "simulated"


class PaymentAccountProvider(StrEnum):
    MERCADO_PAGO = "mercado_pago"


class PaymentTransactionMethod(StrEnum):
    PIX = "pix"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CASH = "cash"
    SIMULATED = "simulated"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    IN_PROCESS = "in_process"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    FAILED = "failed"
    EXPIRED = "expired"
