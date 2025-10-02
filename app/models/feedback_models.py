from pydantic import BaseModel
from typing import Optional, Dict


class FeedbackStatusUpdate(BaseModel):
    status: str


class PushPayload(BaseModel):
    uid: str
    title: str
    body: str
    data: Optional[Dict] = None
