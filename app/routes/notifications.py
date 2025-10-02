from fastapi import APIRouter, HTTPException
import requests
from ..models import PushPayload
from ..utils.firebase import db

router = APIRouter()
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@router.post("/send-notification/")
async def send_notification(payload: PushPayload):
    tokens_ref = db.reference(f"/tokens/{payload.uid}")
    tokens = tokens_ref.get()

    if not tokens:
        raise HTTPException(status_code=404, detail="No tokens found for this user")

    if not isinstance(tokens, list):
        tokens = [tokens]

    results = []
    for token in tokens:
        message = {
            "to": token,
            "sound": "default",
            "title": payload.title,
            "body": payload.body,
            "data": payload.data or {},
        }
        try:
            response = requests.post(EXPO_PUSH_URL, json=message)
            results.append({"token": token, "expo_response": response.json()})
        except Exception as e:
            results.append({"token": token, "error": str(e)})
    return {"results": results}
