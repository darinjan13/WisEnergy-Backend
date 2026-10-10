import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ..utils.firebase import db
from ..services.firmware import local_bin_path

router = APIRouter()
PUBLIC_BASE = os.getenv("BACKEND_PUBLIC_URL", "https://wisenergy-backend.onrender.com")


class ApproveIn(BaseModel):
    uid: str
    device_id: str
    version: str


def _assert_owner(uid: str, device_id: str):
    dev = db.reference(f"/devices/{device_id}").get() or {}
    if dev.get("owner") != uid:
        raise HTTPException(status_code=403, detail="Not your device")


@router.post("/firmware/approve")
def approve_firmware(body: ApproveIn):
    _assert_owner(body.uid, body.device_id)
    latest = db.reference("/firmware/20A/latest").get() or {}
    if latest.get("version") != body.version:
        raise HTTPException(status_code=409, detail="Version is not latest")
    path = local_bin_path(body.version)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Binary not mirrored yet")
    url = f"{PUBLIC_BASE}/firmware/download/20A/{body.version}?device={body.device_id}"
    db.reference(f"/devices/{body.device_id}/fw_command").set({
        "version": body.version,
        "url": url,
        "md5": latest.get("md5", ""),
        "approved": True,
    })
    return {"ok": True, "url": url}


@router.get("/firmware/download/20A/{version}")
def download_firmware(version: str, device: str):
    cmd = db.reference(f"/devices/{device}/fw_command").get() or {}
    if not (cmd.get("approved") is True and cmd.get("version") == version):
        raise HTTPException(status_code=403, detail="No approval for this version")
    path = local_bin_path(version)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Binary not mirrored yet")
    return FileResponse(path, media_type="application/octet-stream",
                        filename=f"wisenergy-20a-{version}.bin")


@router.get("/firmware/latest/20A")
def latest_firmware():
    return db.reference("/firmware/20A/latest").get() or {}
