from pydantic import BaseModel


class PaymentRequest(BaseModel):
    email: str
    amount: float  # e.g., 249 for monthly, 2499 for yearly
    description: str
    payment_method: str  # e.g., "gcash", "paymaya", "card"


class ConfirmPaymentRequest(BaseModel):
    payment_intent_id: str
    payment_method_id: str
