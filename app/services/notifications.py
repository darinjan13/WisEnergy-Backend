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


def save_notification(user_id, title, message, ntype="system", appliance=None):
    try:
        payload = {
            "title": title,
            "message": message,
            "type": ntype,
            "created_at": datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "read_at": None,
        }
        if appliance:
            payload["appliance"] = appliance

        notif_ref = db.reference(f"/notifications/{user_id}")
        notif_ref.push(payload)
        print(f"💾 Notification saved for {user_id}")
    except Exception as e:
        print(f"⚠️ Failed to save notification for {user_id}: {e}")


def can_send_alert(user_id: str, appliance: str, now_ph: datetime, db) -> bool:
    """
    Determines if a high-usage alert for a specific appliance can be sent.
    Prevents duplicates within a 4-hour cooldown window.
    """
    try:
        notif_ref = (
            db.reference(f"/notifications/{user_id}")
            .order_by_child("created_at")
            .limit_to_last(20)  # small batch for performance
        )
        recent_notifs = notif_ref.get() or {}

        for n in reversed(list(recent_notifs.values())):
            if n.get("type") == "high_usage_alert" and n.get("appliance") == appliance:
                last_time = n.get("created_at")
                last_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
                diff_hr = (now_ph - last_dt).total_seconds() / 3600
                if diff_hr < 4:
                    print(f"⏳ Cooldown active for {appliance}: {diff_hr:.2f}h ago")
                    return False
                break
        return True

    except Exception as e:
        print(f"⚠️ Error checking cooldown for {appliance}: {e}")
        return True  # fail-open to avoid blocking all alerts


def already_notified_this_month(user_id: str, notif_type: str) -> bool:
    """
    Check if a notification of the given type was already sent this month.
    Prevents duplicate budget alerts.
    """
    try:
        notif_ref = db.reference(f"/notifications/{user_id}")
        notifications = notif_ref.get() or {}
        current_month = datetime.now(PH_TZ).strftime("%Y-%m")

        for n in notifications.values():
            if n.get("type") == notif_type and n.get("created_at", "").startswith(
                current_month
            ):
                return True
        return False
    except Exception as e:
        print(f"⚠️ Error checking duplicate notification for {user_id}: {e}")
        return False


def check_budget_threshold(user_id: str, total_kwh: float):
    """
    Checks the user's real-time monthly energy consumption against their set budget (in kWh),
    based on the structure:
    /user_monthly_budget/{uid}/{year}/{month}/budget_kwh
    """
    try:
        now = datetime.now(PH_TZ)
        y, m = str(now.year), f"{now.month:02d}"

        # 🔹 Fetch budget entry from user_monthly_budget
        budget_ref = db.reference(f"/user_monthly_budget/{user_id}/{y}/{m}")
        budget_data = budget_ref.get() or {}

        user_budget_kwh = float(budget_data.get("budget_kwh", 0.0))
        if user_budget_kwh <= 0:
            print(f"ℹ️ No active budget found for {user_id} ({y}-{m})")
            return

        progress = (total_kwh / user_budget_kwh) * 100
        print(
            f"📊 [Budget Check] {user_id}: {progress:.2f}% used ({total_kwh:.2f} / {user_budget_kwh:.2f} kWh)"
        )

        if progress >= 120 and not already_notified_this_month(user_id, "budget_120"):
            _send_budget_alert(
                user_id,
                "🚨 Over Budget",
                "You’ve exceeded your monthly energy budget.",
                "budget_120",
            )
        elif progress >= 100 and not already_notified_this_month(user_id, "budget_100"):
            _send_budget_alert(
                user_id,
                "❗ Budget Limit Reached",
                "You’ve reached your monthly energy limit.",
                "budget_100",
            )
        elif progress >= 80 and not already_notified_this_month(user_id, "budget_80"):
            _send_budget_alert(
                user_id,
                "⚠️ Budget Alert",
                "You’ve used 80% of your monthly energy budget.",
                "budget_80",
            )

    except Exception as e:
        print(f"⚠️ Error in budget threshold check for {user_id}: {e}")


def _send_budget_alert(user_id: str, title: str, message: str, ntype: str):
    """
    Internal helper for budget notifications: sends both push and database notification.
    """
    notify_user(
        uid=user_id,
        title=title,
        body=message,
        data={"screen": "notifications", "type": ntype},
    )
    save_notification(
        user_id=user_id,
        title=title,
        message=message,
        ntype=ntype,
    )
    print(f"📬 Budget alert ({ntype}) sent to {user_id}")
