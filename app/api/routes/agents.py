"""
Agent Management API Routes.

Endpoints for monitoring and managing the multi-agent system.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

router = APIRouter()


class AgentType(str, Enum):
    """Types of agents in the system."""
    ANALYZER = "analyzer"
    HEALER = "healer"
    VALIDATOR = "validator"


class AgentStatus(str, Enum):
    """Agent operational status."""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"


class LLMProvider(str, Enum):
    """LLM backend providers."""
    CLAUDE = "claude"
    GPT4 = "gpt4"
    OLLAMA = "ollama"


class AgentResponse(BaseModel):
    """Schema for agent information."""
    id: str
    name: str
    agent_type: AgentType
    llm_provider: LLMProvider
    status: AgentStatus
    reputation_score: float = Field(ge=0.0, le=1.0)
    total_tasks: int
    successful_tasks: int
    average_latency_ms: float
    last_active: datetime
    current_task: Optional[str] = None


class AgentMetrics(BaseModel):
    """Detailed metrics for an agent."""
    agent_id: str
    accuracy_rate: float
    average_confidence: float
    tasks_last_hour: int
    consensus_participation_rate: float
    error_rate: float


# In-memory agent registry (initialized on startup)
agents_registry: dict = {}


def initialize_default_agents():
    """Initialize the default agent configuration."""
    now = datetime.utcnow()

    default_agents = [
        AgentResponse(
            id="analyzer-claude-01",
            name="Analyzer Agent (Claude)",
            agent_type=AgentType.ANALYZER,
            llm_provider=LLMProvider.CLAUDE,
            status=AgentStatus.ONLINE,
            reputation_score=1.0,
            total_tasks=0,
            successful_tasks=0,
            average_latency_ms=0.0,
            last_active=now,
        ),
        AgentResponse(
            id="healer-gpt4-01",
            name="Healer Agent (GPT-4)",
            agent_type=AgentType.HEALER,
            llm_provider=LLMProvider.GPT4,
            status=AgentStatus.ONLINE,
            reputation_score=1.0,
            total_tasks=0,
            successful_tasks=0,
            average_latency_ms=0.0,
            last_active=now,
        ),
        AgentResponse(
            id="validator-ollama-01",
            name="Validator Agent (Ollama)",
            agent_type=AgentType.VALIDATOR,
            llm_provider=LLMProvider.OLLAMA,
            status=AgentStatus.ONLINE,
            reputation_score=1.0,
            total_tasks=0,
            successful_tasks=0,
            average_latency_ms=0.0,
            last_active=now,
        ),
        # Additional agents for BFT (need 3f+1 = 4 for f=1)
        AgentResponse(
            id="validator-ollama-02",
            name="Validator Agent 2 (Ollama)",
            agent_type=AgentType.VALIDATOR,
            llm_provider=LLMProvider.OLLAMA,
            status=AgentStatus.ONLINE,
            reputation_score=1.0,
            total_tasks=0,
            successful_tasks=0,
            average_latency_ms=0.0,
            last_active=now,
        ),
    ]

    for agent in default_agents:
        agents_registry[agent.id] = agent


# Initialize on module load
initialize_default_agents()


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    agent_type: Optional[AgentType] = None,
    status: Optional[AgentStatus] = None,
):
    """List all agents with optional filtering."""
    agents = list(agents_registry.values())

    if agent_type:
        agents = [a for a in agents if a.agent_type == agent_type]
    if status:
        agents = [a for a in agents if a.status == status]

    return agents


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """Get details of a specific agent."""
    if agent_id not in agents_registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agents_registry[agent_id]


@router.get("/{agent_id}/metrics", response_model=AgentMetrics)
async def get_agent_metrics(agent_id: str):
    """Get detailed metrics for an agent."""
    if agent_id not in agents_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent = agents_registry[agent_id]

    # Calculate metrics
    accuracy = agent.successful_tasks / max(agent.total_tasks, 1)

    return AgentMetrics(
        agent_id=agent_id,
        accuracy_rate=accuracy,
        average_confidence=0.85,  # TODO: Calculate from actual data
        tasks_last_hour=0,  # TODO: Calculate from actual data
        consensus_participation_rate=1.0,  # TODO: Calculate from actual data
        error_rate=1.0 - accuracy,
    )


@router.get("/consensus/status")
async def get_consensus_status():
    """
    Get current consensus system status.

    Returns information about the PBFT configuration and agent readiness.
    """
    from app.config import settings

    online_agents = [a for a in agents_registry.values() if a.status == AgentStatus.ONLINE]

    return {
        "fault_tolerance_level": settings.pbft_fault_tolerance,
        "required_votes": settings.required_consensus_votes,
        "min_agents_required": settings.min_total_agents,
        "current_online_agents": len(online_agents),
        "consensus_ready": len(online_agents) >= settings.min_total_agents,
        "agents_by_type": {
            "analyzer": len([a for a in online_agents if a.agent_type == AgentType.ANALYZER]),
            "healer": len([a for a in online_agents if a.agent_type == AgentType.HEALER]),
            "validator": len([a for a in online_agents if a.agent_type == AgentType.VALIDATOR]),
        },
    }


@router.post("/{agent_id}/restart")
async def restart_agent(agent_id: str):
    """Restart an agent that is in error state."""
    if agent_id not in agents_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent = agents_registry[agent_id]

    # TODO: Actually restart the agent
    agent.status = AgentStatus.ONLINE
    agent.last_active = datetime.utcnow()

    return {"status": "restarted", "agent_id": agent_id}
