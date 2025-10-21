import requests
import base64
from fastapi import APIRouter, HTTPException
from ..models.paymongo_models import PaymentRequest
from ..config import PAYMONGO_SECRET_KEY

router = APIRouter()


def get_auth_header():
    encoded = base64.b64encode(f"{PAYMONGO_SECRET_KEY}:".encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# -------------------------------
#  CREATE QRPH PAYMENT INTENT
# -------------------------------
@router.post("/create-payment-intent")
def create_qrph_payment(req: PaymentRequest):
    headers = get_auth_header()

    # Step 1: Create PaymentIntent
    intent_payload = {
        "data": {
            "attributes": {
                "amount": int(req.amount * 100),
                "currency": "PHP",
                "description": req.description,
                "payment_method_allowed": ["qrph"],
                "statement_descriptor": "WisEnergy Premium",
            }
        }
    }

    intent_res = requests.post(
        "https://api.paymongo.com/v1/payment_intents",
        headers=headers,
        json=intent_payload,
    ).json()

    intent_id = intent_res.get("data", {}).get("id")
    if not intent_id:
        raise HTTPException(status_code=400, detail="❌ Failed to create PaymentIntent")

    # Step 2: Create PaymentMethod (QRPH)
    method_payload = {
        "data": {
            "attributes": {
                "type": "qrph",
                "billing": {"email": req.email, "name": "WisEnergy User"},
            }
        }
    }

    method_res = requests.post(
        "https://api.paymongo.com/v1/payment_methods",
        headers=headers,
        json=method_payload,
    ).json()

    method_id = method_res.get("data", {}).get("id")
    if not method_id:
        raise HTTPException(status_code=400, detail="❌ Failed to create PaymentMethod")

    # Step 3: Attach to generate QR
    attach_payload = {
        "data": {
            "attributes": {
                "payment_method": method_id,
                "return_url": "https://wisenergy.ngrok-free.app/paymongo/redirect",
            }
        }
    }

    attach_res = requests.post(
        f"https://api.paymongo.com/v1/payment_intents/{intent_id}/attach",
        headers=headers,
        json=attach_payload,
    ).json()

    # Step 4: Extract QR code details
    qr_data = attach_res.get("data", {}).get("attributes", {}).get("next_action", {})
    if not qr_data:
        raise HTTPException(status_code=500, detail="❌ QR data not found")

    # Return QR data and intent reference
    return attach_res


# -------------------------------
#  CHECK QR STATUS ENDPOINT
# -------------------------------
@router.get("/check-payment-status/{intent_id}")
def check_payment_status(intent_id: str):
    headers = get_auth_header()

    # 1️⃣ Check PaymentIntent for linked payments
    intent_res = requests.get(
        f"https://api.paymongo.com/v1/payment_intents/{intent_id}",
        headers=headers,
    ).json()

    payments = intent_res.get("data", {}).get("attributes", {}).get("payments", [])
    if not payments:
        return {"status": "pending", "message": "Awaiting payment..."}

    payment_id = payments[0]["id"]

    # 2️⃣ Fetch Payment resource details
    pay_res = requests.get(
        f"https://api.paymongo.com/v1/payments/{payment_id}",
        headers=headers,
    ).json()

    pay_attr = pay_res.get("data", {}).get("attributes", {})
    status = pay_attr.get("status", "unknown")
    amount = pay_attr.get("amount", 0) / 100
    paid_at = pay_attr.get("paid_at", None)
    fee = pay_attr.get("fee", 0) / 100
    net = pay_attr.get("net_amount", 0) / 100

    return {
        "status": status,
        "payment_id": payment_id,
        "amount": amount,
        "net_amount": net,
        "fee": fee,
        "paid_at": paid_at,
    }
