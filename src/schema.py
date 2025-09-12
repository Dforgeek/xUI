from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class Start360Request(BaseModel):
    manager_telegram_id: int

class RespondRequest(BaseModel):
    invitation_id: int
    content: str

class SurveyOut(BaseModel):
    id: int
    manager_id: int
    department_id: int
    status: str
    created_at: Optional[datetime]
    summary: Optional[str]

    class Config:
        orm_mode = True

class InvitationOut(BaseModel):
    id: int
    survey_id: int
    user_id: int
    sent_at: Optional[datetime]
    responded_at: Optional[datetime]
    reminder_sent: bool

    class Config:
        orm_mode = True

