from pydantic import BaseModel, EmailStr
from typing import Optional


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
    ocation: Optional[str] = None
    role: str


class UserUpdate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    location: Optional[str] = None


class AdminLoginRequest(BaseModel):
    email: str
    password: str
