import random
from datetime import datetime, timedelta
from fastapi import HTTPException
from sendgrid.helpers.mail import Mail
from ..config import EMAIL_ADDRESS, sendgrid_client
from ..utils.firebase import fs


def generate_otp_code():
    return f"{random.randint(10000, 99999)}"


def send_otp_email(to_email: str, otp: str, userVerification: bool):
    if userVerification:
        subject = "Verify Your WisEnergy Account"
        body = (
            f"Hello,\n\n"
            f"Thanks for signing up! Please use the following code to verify your account:\n\n"
            f"Verification Code: {otp}\n\n"
            f"This code will expire in 5 minutes.\n\n"
            f"Welcome to WisEnergy!"
        )
    else:
        subject = "Your WisEnergy Password Reset Code"
        body = (
            f"Hello,\n\n"
            f"We received a request to reset your password. Use the code below to proceed:\n\n"
            f"Reset Code: {otp}\n\n"
            f"This code will expire in 5 minutes.\n\n"
            f"If you didn't request this, please ignore this email."
        )

    message = Mail(
        from_email="noreply@wisenergy.site",
        to_emails=to_email,
        subject=subject,
        plain_text_content=body,
    )

    try:
        sendgrid_client.send(message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email send failed: {str(e)}")


def save_otp(email: str, otp: str):
    expires = datetime.utcnow() + timedelta(minutes=5)
    email_id = email.replace(".", "_")
    fs.collection("otp-verification").document(email_id).set(
        {"otp": otp, "expires_at": expires.isoformat()}
    )
