from pydantic import BaseModel, EmailStr


class OTPRequest(BaseModel):
    email: EmailStr
    userVerification: bool


class PasswordResetRequest(BaseModel):
    email: str
    new_password: str


class User(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    location: str
    role: str
