import requests
from fastapi import HTTPException
from ..utils.firebase import db
from datetime import datetime, timedelta
from ..utils.timezone import PH_TZ

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_notification(payload):
    tokens_ref = db.reference(f"/tokens/{payload.uid}")
    tokens = tokens_ref.get()
    if not tokens:
        raise HTTPException(status_code=404, detail="No tokens found for this user")

    results = []
    for token in tokens:
        message = {
            "to": token,
            "sound": "default",
            "title": payload.title,
            "body": payload.body,
            "data": payload.data or {},
        }
        response = requests.post(EXPO_PUSH_URL, json=message)
        results.append({"token": token, "response": response.json()})
    return {"results": results}


def notify_user(uid: str, title: str, body: str, data: dict | None = None):
    tokens_ref = db.reference(f"/tokens/{uid}")
    tokens = tokens_ref.get()
    if not tokens:
        print(f"⚠️ No tokens registered for {uid}")
        return
    for token in tokens:
        requests.post(
            EXPO_PUSH_URL,
            json={
                "to": token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {},
            },
        )


def save_notification(user_id, title, message, ntype="system"):
    try:
        notif_ref = db.reference(f"/notifications/{user_id}")
        notif_ref.push(
            {
                "title": title,
                "message": message,
                "type": ntype,
                "created_at": datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "read_at": None,
            }
        )
        print(f"💾 Notification saved for {user_id}")
    except Exception as e:
        print(f"⚠️ Failed to save notification for {user_id}: {e}")


def can_send_alert(user_id: str, appliance: str, now_ph: datetime, db):
    """
    Check if a high usage alert can be sent (cooldown of 4 hours per appliance).

    Args:
        user_id (str): User ID.
        appliance (str): Appliance name.
        now_ph (datetime): Current timestamp in PH timezone.
        db: Database reference.

    Returns:
        bool: True if an alert can be sent, False if within cooldown.
    """
    last_alert = (
        db.reference(f"/notifications/{user_id}")
        .order_by_child("appliance")
        .equal_to(appliance)
        .order_by_child("created_at")
        .limit_to_last(1)
        .get()
    )
    if last_alert:
        last_alert_time = list(last_alert.values())[0].get("created_at")
        try:
            last_alert_dt = datetime.strptime(last_alert_time, "%Y-%m-%d %H:%M:%S")
            if (now_ph - last_alert_dt).total_seconds() < 4 * 3600:
                print(f"⏳ Cooldown active for {appliance} alert for {user_id}")
                return False
        except Exception as e:
            print(f"⚠️ Error checking cooldown for {appliance}: {e}")
    return True
