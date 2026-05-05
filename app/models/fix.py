"""Fix data models."""

from pydantic import BaseModel, Field
from typing import Optional, Dict
from datetime import datetime
from enum import Enum


class FixStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATING = "validating"
    CONSENSUS_PENDING = "consensus_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


class FixCreate(BaseModel):
    """Schema for creating a fix."""
    bug_id: str
    original_code: str
    fixed_code: str
    explanation: str
    agent_id: str


class Fix(BaseModel):
    """Full fix model."""
    id: str
    bug_id: str
    original_code: str
    fixed_code: str
    explanation: str
    agent_id: str
    agent_type: str
    confidence_score: float
    status: FixStatus
    consensus_votes: Dict = Field(default_factory=dict)
    created_at: datetime
    applied_at: Optional[datetime] = None

    class Config:
        from_attributes = True
