from fastapi import APIRouter
from ..utils.firebase import db

router = APIRouter()


@router.get("/devices")
def get_devices():
    devices_ref = db.reference("/devices")
    devices_data = devices_ref.get()
    if not devices_data:
        return []
    return [{"id": device_id, **details} for device_id, details in devices_data.items()]
