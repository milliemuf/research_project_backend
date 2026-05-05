"""
Fix Management API Routes.

Endpoints for viewing and managing bug fixes.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

router = APIRouter()


class FixStatus(str, Enum):
    """Fix lifecycle status."""
    PROPOSED = "proposed"
    VALIDATING = "validating"
    CONSENSUS_PENDING = "consensus_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


class FixResponse(BaseModel):
    """Schema for fix response."""
    id: str
    bug_id: str
    original_code: str
    fixed_code: str
    explanation: str
    agent_id: str
    agent_type: str  # analyzer, healer, validator
    confidence_score: float
    status: FixStatus
    consensus_votes: dict = Field(default_factory=dict)
    created_at: datetime
    applied_at: Optional[datetime] = None


class FixListResponse(BaseModel):
    """Schema for paginated fix list."""
    total: int
    page: int
    per_page: int
    fixes: List[FixResponse]


class ConsensusVote(BaseModel):
    """Schema for consensus vote."""
    agent_id: str
    vote: bool  # True = approve, False = reject
    confidence: float
    reason: Optional[str] = None


# In-memory storage for demo
fixes_db: dict = {}


@router.get("", response_model=FixListResponse)
async def list_fixes(
    bug_id: Optional[str] = Query(None, description="Filter by bug ID"),
    status: Optional[FixStatus] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List all fixes with optional filtering."""
    filtered = list(fixes_db.values())

    if bug_id:
        filtered = [f for f in filtered if f.bug_id == bug_id]
    if status:
        filtered = [f for f in filtered if f.status == status]

    filtered.sort(key=lambda x: x.created_at, reverse=True)

    start = (page - 1) * per_page
    end = start + per_page

    return FixListResponse(
        total=len(filtered),
        page=page,
        per_page=per_page,
        fixes=filtered[start:end],
    )


@router.get("/{fix_id}", response_model=FixResponse)
async def get_fix(fix_id: str):
    """Get details of a specific fix."""
    if fix_id not in fixes_db:
        raise HTTPException(status_code=404, detail="Fix not found")
    return fixes_db[fix_id]


@router.get("/{fix_id}/diff")
async def get_fix_diff(fix_id: str):
    """Get unified diff of the fix."""
    if fix_id not in fixes_db:
        raise HTTPException(status_code=404, detail="Fix not found")

    fix = fixes_db[fix_id]

    # Generate unified diff
    import difflib
    diff = difflib.unified_diff(
        fix.original_code.splitlines(keepends=True),
        fix.fixed_code.splitlines(keepends=True),
        fromfile="original",
        tofile="fixed",
    )

    return {
        "fix_id": fix_id,
        "diff": "".join(diff),
        "original_lines": len(fix.original_code.splitlines()),
        "fixed_lines": len(fix.fixed_code.splitlines()),
    }


@router.post("/{fix_id}/vote")
async def submit_vote(fix_id: str, vote: ConsensusVote):
    """
    Submit a consensus vote for a fix.

    This is called by validator agents during the PBFT consensus process.
    """
    if fix_id not in fixes_db:
        raise HTTPException(status_code=404, detail="Fix not found")

    fix = fixes_db[fix_id]
    fix.consensus_votes[vote.agent_id] = {
        "vote": vote.vote,
        "confidence": vote.confidence,
        "reason": vote.reason,
    }

    # TODO: Check if consensus is reached
    # from app.consensus.pbft import check_consensus
    # if check_consensus(fix.consensus_votes):
    #     fix.status = FixStatus.APPROVED

    return {"status": "vote_recorded", "total_votes": len(fix.consensus_votes)}


@router.post("/{fix_id}/apply")
async def apply_fix(fix_id: str):
    """
    Apply an approved fix to the running system.

    Only fixes with APPROVED status can be applied.
    """
    if fix_id not in fixes_db:
        raise HTTPException(status_code=404, detail="Fix not found")

    fix = fixes_db[fix_id]

    if fix.status != FixStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Fix must be approved before applying. Current status: {fix.status}"
        )

    # TODO: Apply the fix using hot-patching
    # from app.repair.patch_applier import apply_patch
    # await apply_patch(fix)

    fix.status = FixStatus.APPLIED
    fix.applied_at = datetime.utcnow()

    return {"status": "applied", "fix_id": fix_id, "applied_at": fix.applied_at}


@router.post("/{fix_id}/rollback")
async def rollback_fix(fix_id: str):
    """Rollback a previously applied fix."""
    if fix_id not in fixes_db:
        raise HTTPException(status_code=404, detail="Fix not found")

    fix = fixes_db[fix_id]

    if fix.status != FixStatus.APPLIED:
        raise HTTPException(
            status_code=400,
            detail="Can only rollback applied fixes"
        )

    # TODO: Rollback using stored original
    # from app.repair.patch_applier import rollback_patch
    # await rollback_patch(fix)

    fix.status = FixStatus.ROLLED_BACK

    return {"status": "rolled_back", "fix_id": fix_id}
