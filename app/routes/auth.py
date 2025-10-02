from fastapi import APIRouter, HTTPException
from firebase_admin import auth
from ..models import PasswordResetRequest, OTPRequest
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
        auth.get_user_by_email(req.email)
    except auth.UserNotFoundError:
        raise HTTPException(status_code=500, detail=f"{req.email} is not registered.")

    otp = generate_otp_code()
    save_otp(req.email, otp)
    send_otp_email(req.email, otp, req.userVerification)
    return {"message": f"OTP sent to {req.email}"}
