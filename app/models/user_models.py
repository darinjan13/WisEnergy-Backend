from pydantic import BaseModel, EmailStr


class OTPRequest(BaseModel):
    email: EmailStr
    userVerification: bool


class OTPRequestWithCode(BaseModel):
    email: EmailStr
    code: str


class PasswordResetRequest(BaseModel):
    email: str
    new_password: str


class User(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    location: str
    role: str


class AdminLoginRequest(BaseModel):
    email: str
    password: str
