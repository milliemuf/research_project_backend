"""
Consensus Lab API routes.

Provides a "consensus only" entry point: the user supplies the bug context
AND a candidate fix; the route runs the validator agents (Ollama, free)
and drives PBFT consensus on the result. The Analyzer and Healer LLM
stages are skipped, so this route works today without OpenAI quota.

Returns a rich phase-by-phase event log so the frontend can animate the
consensus run.

Endpoints:
  GET  /api/v1/consensus-lab/info      backend config + registered agents
  POST /api/v1/consensus-lab/run       run validators + consensus on a fix

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.base_agent import AgentConfig, AgentType, LLMProvider
from app.agents.healer_agent import FixCandidate
from app.agents.validator_agent import ValidationInput, ValidatorAgent
from app.api.websockets import broadcast_lab_event
from app.config import settings
from app.consensus.message_types import FixProposal
from app.consensus.pbft import AgentInfo, PBFTConsensus

logger = structlog.get_logger(__name__)

router = APIRouter()

# --- Module-level state -----------------------------------------------------
# Four validator agents, each wired to a different Ollama model where one
# is available. This gives genuine model heterogeneity for the consensus
# experiment, without needing any cloud LLM.
_VALIDATOR_PRESETS = [
    ("validator-llama3", "llama3.1:8b"),
    ("validator-codellama", "codellama:7b"),
    ("validator-mistral", "mistral:7b"),
    ("validator-llama3-b", "llama3.1:8b"),
]

_validators: List[ValidatorAgent] = []
_consensus: Optional[PBFTConsensus] = None
_recent_runs: Deque[Dict[str, Any]] = deque(maxlen=20)


def _ensure_initialised() -> None:
    """Lazy initialisation so importing the module is cheap."""
    global _consensus
    if _validators:
        return

    for agent_id, model in _VALIDATOR_PRESETS:
        # Encode "url|model" so base_agent._call_ollama uses the right model
        model_field = f"{settings.ollama_base_url}|{model}"
        v = ValidatorAgent(AgentConfig(
            agent_id=agent_id,
            agent_type=AgentType.VALIDATOR,
            llm_provider=LLMProvider.OLLAMA,
            model_name=model_field,
            temperature=0.1,
            max_tokens=512,
        ))
        v.set_llm_client(object())  # any non-None placeholder; ollama uses URL
        _validators.append(v)

    _consensus = PBFTConsensus(f=1, timeout_ms=30000)
    for v in _validators:
        _consensus.register_agent(AgentInfo(
            agent_id=v.agent_id,
            agent_type="validator",
            llm_provider="ollama",
        ))

    logger.info(
        "Consensus lab initialised",
        agents=[v.agent_id for v in _validators],
        f=_consensus.f,
        quorum=_consensus.quorum,
    )


# --- Schemas ---------------------------------------------------------------
class ConsensusRunRequest(BaseModel):
    bug_id: Optional[str] = Field(None, description="Optional caller-supplied identifier")
    client_request_id: Optional[str] = Field(
        None,
        description="Client-supplied UUID that the backend echoes in every WS event for this run. "
                    "Lets the frontend filter live events to its own request.",
    )
    error_message: str
    stack_trace: str = ""
    original_code: str
    fixed_code: str
    explanation: str = "user-supplied candidate"
    file_path: str = "candidate.py"
    line_number: int = 1
    language: str = "python"
    confidence_score: float = Field(0.8, ge=0.0, le=1.0)


class AgentVote(BaseModel):
    agent_id: str
    llm_provider: str
    is_valid: bool
    confidence: float
    reason: str
    issues: List[str]
    latency_ms: float
    syntax_valid: bool
    safety_score: float


class PhaseEvent(BaseModel):
    phase: str
    started_at: str
    ended_at: str
    duration_ms: float
    description: str


class ConsensusRunResponse(BaseModel):
    bug_id: str
    success: bool
    decision: str                       # "approved" | "rejected"
    decision_reason: str
    sequence: int
    view: int
    quorum_required: int
    prepare_votes: int
    commit_votes: int
    duration_ms: float
    phases: List[PhaseEvent]
    votes: List[AgentVote]
    timestamp: str


# --- Endpoints --------------------------------------------------------------
@router.get("/info")
async def consensus_lab_info() -> Dict[str, Any]:
    _ensure_initialised()
    assert _consensus is not None
    return {
        "f": _consensus.f,
        "n_required": _consensus.n_required,
        "quorum": _consensus.quorum,
        "registered_agents": [
            {
                "agent_id": v.agent_id,
                "llm_provider": v.llm_provider.value,
                "model_name": v.config.model_name.split("|", 1)[-1] if "|" in v.config.model_name else v.config.model_name,
                "reputation": v.reputation_score,
                "total_tasks": v.total_tasks,
                "accuracy": v.accuracy,
            }
            for v in _validators
        ],
        "stats": _consensus.get_stats(),
        "recent_runs": list(_recent_runs),
    }


@router.post("/run", response_model=ConsensusRunResponse)
async def run_consensus(req: ConsensusRunRequest) -> ConsensusRunResponse:
    """
    Run validators + PBFT consensus on the supplied fix candidate.

    The four Ollama validator agents each evaluate the candidate fix; their
    votes feed the PBFT three-phase protocol. This endpoint does NOT call
    Claude or GPT-4, so it works without those keys.
    """
    _ensure_initialised()
    assert _consensus is not None

    bug_id = req.bug_id or f"lab-{int(datetime.utcnow().timestamp() * 1000)}"
    run_id = req.client_request_id or f"run-{int(datetime.utcnow().timestamp() * 1000)}"
    started_at = datetime.utcnow()
    phases: List[PhaseEvent] = []
    votes: List[AgentVote] = []

    await broadcast_lab_event("lab_run_started", run_id, {
        "bug_id": bug_id,
        "agents": [v.agent_id for v in _validators],
        "quorum": _consensus.quorum,
        "n_required": _consensus.n_required,
    })

    # --------- Phase 0: stage the FixProposal -----------
    stage_start = datetime.utcnow()
    fix_proposal = FixProposal(
        bug_id=bug_id,
        original_code=req.original_code,
        fixed_code=req.fixed_code,
        explanation=req.explanation,
        proposing_agent_id="lab-user",
        confidence_score=req.confidence_score,
        language=req.language,
        file_path=req.file_path,
        line_number=req.line_number,
    )
    phases.append(PhaseEvent(
        phase="proposal",
        started_at=stage_start.isoformat(),
        ended_at=datetime.utcnow().isoformat(),
        duration_ms=(datetime.utcnow() - stage_start).total_seconds() * 1000,
        description="user-supplied fix proposal staged",
    ))
    await broadcast_lab_event("phase_finished", run_id, {
        "phase": "proposal",
        "duration_ms": (datetime.utcnow() - stage_start).total_seconds() * 1000,
    })

    # --------- Phase 1-3: validators run + PBFT consensus ----------
    candidate = FixCandidate(
        fixed_code=req.fixed_code,
        explanation=req.explanation,
        confidence=req.confidence_score,
        changes_description="user-supplied",
        potential_side_effects=[],
    )
    validation_input = ValidationInput(
        original_code=req.original_code,
        fix_candidate=candidate,
        language=req.language,
        file_path=req.file_path,
    )

    validate_phase_start = datetime.utcnow()
    import asyncio

    async def run_validator_with_events(validator):
        """Wrap one validator call so it broadcasts start/finish on the WS channel."""
        await broadcast_lab_event("validator_started", run_id, {
            "agent_id": validator.agent_id,
            "model": validator.config.model_name.split("|", 1)[-1] if "|" in validator.config.model_name else validator.config.model_name,
        })
        try:
            vo = await validator.process(validation_input)
            r = vo.result
            await broadcast_lab_event("validator_finished", run_id, {
                "agent_id": validator.agent_id,
                "is_valid": getattr(r, "is_valid", False),
                "confidence": getattr(r, "confidence", 0.0),
                "latency_ms": vo.latency_ms,
                "issues": list(getattr(r, "issues", []) or [])[:3],
                "syntax_valid": getattr(r, "syntax_valid", False),
                "safety_score": getattr(r, "safety_score", 0.0),
                "reason": (vo.reasoning or "")[:200],
            })
            return vo
        except Exception as e:
            await broadcast_lab_event("validator_failed", run_id, {
                "agent_id": validator.agent_id,
                "error": str(e)[:200],
            })
            raise

    # Run validators concurrently; each one streams its own events.
    validator_outputs = await asyncio.gather(
        *(run_validator_with_events(v) for v in _validators),
        return_exceptions=True,
    )
    phases.append(PhaseEvent(
        phase="validation",
        started_at=validate_phase_start.isoformat(),
        ended_at=datetime.utcnow().isoformat(),
        duration_ms=(datetime.utcnow() - validate_phase_start).total_seconds() * 1000,
        description=f"{len(_validators)} validator agents evaluated the fix",
    ))
    await broadcast_lab_event("phase_finished", run_id, {
        "phase": "validation",
        "duration_ms": (datetime.utcnow() - validate_phase_start).total_seconds() * 1000,
    })

    # Build per-agent vote records
    for validator, vo in zip(_validators, validator_outputs):
        if isinstance(vo, Exception):
            votes.append(AgentVote(
                agent_id=validator.agent_id,
                llm_provider=validator.llm_provider.value,
                is_valid=False,
                confidence=0.0,
                reason=f"validator failed: {vo}",
                issues=[str(vo)],
                latency_ms=0.0,
                syntax_valid=False,
                safety_score=0.0,
            ))
        else:
            r = vo.result
            votes.append(AgentVote(
                agent_id=validator.agent_id,
                llm_provider=validator.llm_provider.value,
                is_valid=getattr(r, "is_valid", False),
                confidence=getattr(r, "confidence", 0.0),
                reason=vo.reasoning or "",
                issues=list(getattr(r, "issues", []) or []),
                latency_ms=vo.latency_ms,
                syntax_valid=getattr(r, "syntax_valid", False),
                safety_score=getattr(r, "safety_score", 0.0),
            ))

    # --------- Phase 4-6: PBFT pre-prepare → prepare → commit ----------
    pbft_phase_start = datetime.utcnow()
    await broadcast_lab_event("phase_started", run_id, {"phase": "pbft"})

    # The validate_fn here just looks up the already-computed validator vote
    vote_by_id = {v.agent_id: v for v in votes}

    async def validate_for_consensus(fix: FixProposal, agent_id: str):
        v = vote_by_id.get(agent_id)
        if v is None:
            return True, 0.5, "no validator output"
        return v.is_valid, v.confidence, "; ".join(v.issues) or "ok"

    consensus_result = await _consensus.propose_fix(fix_proposal, validate_fn=validate_for_consensus)

    phases.append(PhaseEvent(
        phase="pbft",
        started_at=pbft_phase_start.isoformat(),
        ended_at=datetime.utcnow().isoformat(),
        duration_ms=(datetime.utcnow() - pbft_phase_start).total_seconds() * 1000,
        description=f"PBFT three-phase: pre-prepare → prepare ({consensus_result.prepare_votes} votes) → commit ({consensus_result.commit_votes} votes)",
    ))
    await broadcast_lab_event("phase_finished", run_id, {
        "phase": "pbft",
        "duration_ms": (datetime.utcnow() - pbft_phase_start).total_seconds() * 1000,
        "prepare_votes": consensus_result.prepare_votes,
        "commit_votes": consensus_result.commit_votes,
        "quorum_required": _consensus.quorum,
    })

    total_duration_ms = (datetime.utcnow() - started_at).total_seconds() * 1000

    response = ConsensusRunResponse(
        bug_id=bug_id,
        success=consensus_result.success,
        decision="approved" if consensus_result.success else "rejected",
        decision_reason=consensus_result.decision_reason,
        sequence=consensus_result.sequence,
        view=consensus_result.view,
        quorum_required=_consensus.quorum,
        prepare_votes=consensus_result.prepare_votes,
        commit_votes=consensus_result.commit_votes,
        duration_ms=total_duration_ms,
        phases=phases,
        votes=votes,
        timestamp=datetime.utcnow().isoformat(),
    )

    # Compact summary for the recent-runs widget
    _recent_runs.appendleft({
        "bug_id": bug_id,
        "timestamp": response.timestamp,
        "decision": response.decision,
        "prepare_votes": response.prepare_votes,
        "commit_votes": response.commit_votes,
        "quorum_required": response.quorum_required,
        "duration_ms": round(total_duration_ms, 1),
        "decision_reason": response.decision_reason,
        "language": req.language,
        "file_path": req.file_path,
    })

    await broadcast_lab_event("lab_run_decided", run_id, {
        "bug_id": bug_id,
        "success": response.success,
        "decision": response.decision,
        "decision_reason": response.decision_reason,
        "prepare_votes": response.prepare_votes,
        "commit_votes": response.commit_votes,
        "quorum_required": response.quorum_required,
        "duration_ms": total_duration_ms,
    })

    return response
