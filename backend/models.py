from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum


class UrgencyEnum(str, Enum):
    emergency = "emergency"
    urgent = "urgent"
    routine = "routine"


class StatusEnum(str, Enum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"
    incomplete = "incomplete"


class CreateTicketRequest(BaseModel):
    tenant_id: Optional[str] = None
    urgency: UrgencyEnum
    summary: str
    status: StatusEnum = StatusEnum.open
    confidence: float = Field(ge=0.0, le=1.0)
    instructions: Optional[str] = None
    estimated_duration_minutes: int = Field(ge=5)
    raw_turns: Optional[List[dict]] = None

    @field_validator("estimated_duration_minutes")
    @classmethod
    def must_be_multiple_of_five(cls, v: int) -> int:
        if v % 5 != 0:
            raise ValueError("estimated_duration_minutes must be a multiple of 5")
        return v


class UpdateTicketRequest(BaseModel):
    status: Optional[StatusEnum] = None
    estimated_duration_minutes: Optional[int] = Field(default=None, ge=5)

    @field_validator("estimated_duration_minutes")
    @classmethod
    def must_be_multiple_of_five(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v % 5 != 0:
            raise ValueError("estimated_duration_minutes must be a multiple of 5")
        return v


class CreateAlertRequest(BaseModel):
    ticket_id: str


class UpdateLocationRequest(BaseModel):
    building_id: str
