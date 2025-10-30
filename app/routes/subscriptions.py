from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from ..utils.firebase import db

router = APIRouter()


def derive_plan_type(amount: float | None):
    """Infer plan type based on amount."""
    if not amount:
        return "Monthly"
    if amount >= 900:
        return "Yearly"
    return "Monthly"


def compute_status(start_str: str, plan_type: str):
    """Compute status and end date from start date."""
    try:
        start_date = datetime.fromisoformat(start_str.replace("Z", ""))
    except:
        return {"status": "Pending", "end_date": None}

    if plan_type.lower() == "monthly":
        end_date = start_date + timedelta(days=30)
    elif plan_type.lower() == "yearly":
        end_date = start_date + timedelta(days=365)
    else:
        end_date = None

    now = datetime.now()
    if end_date and now > end_date:
        status = "Expired"
    else:
        status = "Active"

    return {
        "status": status,
        "end_date": end_date.strftime("%Y-%m-%d") if end_date else "—",
    }


@router.get("/")
def list_subscriptions():
    """Return all subscriptions formatted for admin dashboard."""
    subs = db.reference("/subscriptions").get() or {}
    if not subs:
        raise HTTPException(status_code=404, detail="No subscriptions found")

    result = []
    count = 1

    for uid, data in subs.items():
        payment_id = data.get("premium_payment_id", "—")
        amount = data.get("premium_amount", 0)
        start_date = data.get("premium_date")

        plan_type = derive_plan_type(amount)
        computed = compute_status(start_date, plan_type)

        result.append(
            {
                "subscription_id": f"SUB{count:03d}",
                "user_id": uid[:7].upper(),
                "plan_type": plan_type,
                "start_date": start_date.split("T")[0] if start_date else "—",
                "end_date": computed["end_date"],
                "status": computed["status"],
                "payment_reference": payment_id,
                "amount": amount,
            }
        )
        count += 1

    return {"total": len(result), "subscriptions": result}
