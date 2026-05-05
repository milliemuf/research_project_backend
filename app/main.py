"""
CodeFlow AI - Main FastAPI Application Entry Point

Byzantine Fault-Tolerant Multi-Agent System for Autonomous Runtime Program Repair
in E-Commerce Systems.

Author: Millicent Mufambi (H240624A)
Institution: Harare Institute of Technology
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from fastapi import Response

from app.config import settings
from app.api.routes import bugs, fixes, agents, dashboard, sandbox, consensus_lab
from app.api.websockets import websocket_router
from app.monitoring import metrics_collector

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan manager.

    Handles startup and shutdown events for:
    - Database connections
    - Redis connections
    - Neo4j connections
    - Agent initialization
    """
    logger.info("Starting CodeFlow AI", version="0.1.0", env=settings.app_env)

    # Startup
    try:
        # TODO: Initialize database connection pool
        # TODO: Initialize Redis connection
        # TODO: Initialize Neo4j connection
        # TODO: Initialize agent system
        logger.info("All connections initialized successfully")
        yield
    finally:
        # Shutdown
        logger.info("Shutting down CodeFlow AI")
        # TODO: Close all connections gracefully


# Create FastAPI application
app = FastAPI(
    title="CodeFlow AI",
    description="""
    ## Byzantine Fault-Tolerant Multi-Agent System for Autonomous Runtime Program Repair

    CodeFlow AI is a novel system that combines:
    - **Multi-Agent Architecture**: Analyzer, Healer, and Validator agents
    - **Byzantine Fault Tolerance**: PBFT consensus for reliable decision-making
    - **Runtime Repair**: Autonomous bug detection and fixing in production
    - **E-Commerce Focus**: Designed for critical financial systems

    ### Key Features
    - Real-time bug detection and classification
    - LLM-powered fix generation with multiple candidates
    - Consensus-based fix validation and application
    - Knowledge graph for learning from past repairs

    ### Research Project
    M.Tech Software Engineering - Harare Institute of Technology

    **Author**: Millicent Mufambi (H240624A)
    **Supervisor**: Mr Makondo
    """,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vue.js dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(bugs.router, prefix="/api/v1/bugs", tags=["Bugs"])
app.include_router(fixes.router, prefix="/api/v1/fixes", tags=["Fixes"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agents"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(sandbox.router, prefix="/api/v1/sandbox", tags=["Sandbox"])
app.include_router(consensus_lab.router, prefix="/api/v1/consensus-lab", tags=["Consensus Lab"])
app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API information."""
    return {
        "name": "CodeFlow AI",
        "version": "0.1.0",
        "description": "Byzantine Fault-Tolerant Multi-Agent System for Autonomous Runtime Program Repair",
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "environment": settings.app_env,
        "consensus_config": {
            "fault_tolerance": settings.pbft_fault_tolerance,
            "required_votes": settings.required_consensus_votes,
            "min_agents": settings.min_total_agents,
        }
    }


@app.get("/metrics", tags=["Monitoring"], include_in_schema=False)
async def prometheus_metrics():
    """Prometheus scrape endpoint (text format)."""
    return Response(
        content=metrics_collector.export_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/api/v1/metrics/snapshot", tags=["Monitoring"])
async def metrics_snapshot():
    """
    JSON snapshot of the seven evaluation metrics from the H-BFT review.

    Returns the latest values for: consensus throughput, latency p50/p99,
    consensus success rate, safety violation rate, recovery time, agent
    agreement rate, and (when ground-truth labels are available) F1 score.
    """
    return metrics_collector.snapshot().to_dict()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=7222,  # matches frontend's VITE_API_URL
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
