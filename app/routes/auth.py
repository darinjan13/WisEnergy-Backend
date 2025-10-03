from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from firebase_admin import auth
from ..utils.firebase import fs
from ..models.user_models import PasswordResetRequest, OTPRequest, OTPRequestWithCode
from ..services.otp import generate_otp_code, send_otp_email, save_otp

router = APIRouter()


@router.post("/reset-password")
def reset_password(data: PasswordResetRequest):
    try:
        user = auth.get_user_by_email(data.email)
        auth.update_user(user.uid, password=data.new_password)
        return {"message": "Password updated Successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/generate-otp")
def generate_otp(req: OTPRequest):
    try:
        # If OTP is for FORGOT PASSWORD, user must exist
        if not req.userVerification:
            auth.get_user_by_email(req.email)

        # If OTP is for REGISTRATION, skip user existence check
    except auth.UserNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"{req.email} is not yet registered."
        )

    otp = generate_otp_code()
    save_otp(req.email, otp)
    send_otp_email(req.email, otp, req.userVerification)

    return {"success": True, "message": f"OTP sent to {req.email}"}


@router.post("/verify-otp")
def verify_otp(req: OTPRequestWithCode):
    email_id = req.email.replace(".", "_")
    ref = fs.collection("otp-verification").document(email_id)
    snap = ref.get()

    if not snap.exists:
        raise HTTPException(status_code=404, detail="No OTP request found.")

    data = snap.to_dict()

    # Parse expiry
    expires_at = datetime.fromisoformat(data["expires_at"])
    now = datetime.utcnow()

    if now > expires_at:
        # ⏰ Expired -> delete automatically
        ref.delete()
        raise HTTPException(
            status_code=400, detail="OTP expired. Please request a new one."
        )

    if req.code != data["otp"]:
        raise HTTPException(status_code=400, detail="Invalid OTP code.")

    # ✅ OTP valid -> delete immediately after use
    ref.delete()

    return {"success": True, "message": "OTP verified"}
