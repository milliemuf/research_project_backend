"""Bug data models."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class BugSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BugStatus(str, Enum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    FIX_PROPOSED = "fix_proposed"
    CONSENSUS_PENDING = "consensus_pending"
    FIXING = "fixing"
    RESOLVED = "resolved"
    FAILED = "failed"


class BugCreate(BaseModel):
    """Schema for creating a bug."""
    error_message: str
    stack_trace: str
    code_context: str
    file_path: str
    line_number: int
    language: str = "python"


class Bug(BaseModel):
    """Full bug model."""
    id: str
    error_message: str
    stack_trace: str
    code_context: str
    file_path: str
    line_number: int
    language: str
    bug_type: str
    severity: BugSeverity
    status: BugStatus
    confidence_score: float
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    fix_id: Optional[str] = None

    class Config:
        from_attributes = True
