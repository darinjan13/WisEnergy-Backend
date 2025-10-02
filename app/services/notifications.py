import requests
from fastapi import HTTPException
from ..utils.firebase import db

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
