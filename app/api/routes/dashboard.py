"""
Dashboard API Routes.

Endpoints for the monitoring dashboard.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List

router = APIRouter()


class SystemHealth(BaseModel):
    """Overall system health status."""
    status: str
    uptime_seconds: float
    bugs_detected_today: int
    bugs_resolved_today: int
    active_consensus_rounds: int
    average_repair_time_ms: float


class TimeSeriesPoint(BaseModel):
    """Single point in a time series."""
    timestamp: datetime
    value: float


class DashboardMetrics(BaseModel):
    """Aggregated dashboard metrics."""
    total_bugs: int
    resolved_bugs: int
    pending_bugs: int
    success_rate: float
    average_consensus_time_ms: float
    agents_online: int
    agents_total: int


# Track system start time
SYSTEM_START_TIME = datetime.utcnow()


@router.get("/health", response_model=SystemHealth)
async def get_system_health():
    """Get overall system health status."""
    from app.api.routes.bugs import bugs_db, BugStatus
    from app.api.routes.agents import agents_registry, AgentStatus

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    bugs = list(bugs_db.values())
    bugs_today = [b for b in bugs if b.detected_at >= today_start]
    resolved_today = [b for b in bugs_today if b.status == BugStatus.RESOLVED]

    online_agents = len([a for a in agents_registry.values() if a.status == AgentStatus.ONLINE])
    min_agents = 4  # 3f+1 for f=1

    status = "healthy" if online_agents >= min_agents else "degraded"

    return SystemHealth(
        status=status,
        uptime_seconds=(now - SYSTEM_START_TIME).total_seconds(),
        bugs_detected_today=len(bugs_today),
        bugs_resolved_today=len(resolved_today),
        active_consensus_rounds=0,  # TODO: Track active consensus
        average_repair_time_ms=0.0,  # TODO: Calculate from actual data
    )


@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics():
    """Get aggregated metrics for dashboard display."""
    from app.api.routes.bugs import bugs_db, BugStatus
    from app.api.routes.agents import agents_registry, AgentStatus

    bugs = list(bugs_db.values())
    total = len(bugs)
    resolved = len([b for b in bugs if b.status == BugStatus.RESOLVED])
    pending = len([b for b in bugs if b.status not in [BugStatus.RESOLVED, BugStatus.FAILED]])

    agents = list(agents_registry.values())
    online = len([a for a in agents if a.status == AgentStatus.ONLINE])

    return DashboardMetrics(
        total_bugs=total,
        resolved_bugs=resolved,
        pending_bugs=pending,
        success_rate=resolved / max(total, 1),
        average_consensus_time_ms=0.0,  # TODO: Calculate
        agents_online=online,
        agents_total=len(agents),
    )


@router.get("/timeline/bugs")
async def get_bug_timeline(hours: int = 24) -> List[TimeSeriesPoint]:
    """Get bug detection timeline for the specified period."""
    from app.api.routes.bugs import bugs_db

    now = datetime.utcnow()
    start = now - timedelta(hours=hours)

    # Group bugs by hour
    hourly_counts = {}
    for bug in bugs_db.values():
        if bug.detected_at >= start:
            hour = bug.detected_at.replace(minute=0, second=0, microsecond=0)
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

    # Fill in missing hours with 0
    points = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= now:
        points.append(TimeSeriesPoint(
            timestamp=current,
            value=hourly_counts.get(current, 0)
        ))
        current += timedelta(hours=1)

    return points


@router.get("/timeline/repairs")
async def get_repair_timeline(hours: int = 24) -> List[TimeSeriesPoint]:
    """Get successful repair timeline for the specified period."""
    from app.api.routes.fixes import fixes_db, FixStatus

    now = datetime.utcnow()
    start = now - timedelta(hours=hours)

    # Group fixes by hour
    hourly_counts = {}
    for fix in fixes_db.values():
        if fix.status == FixStatus.APPLIED and fix.applied_at and fix.applied_at >= start:
            hour = fix.applied_at.replace(minute=0, second=0, microsecond=0)
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

    # Fill in missing hours
    points = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= now:
        points.append(TimeSeriesPoint(
            timestamp=current,
            value=hourly_counts.get(current, 0)
        ))
        current += timedelta(hours=1)

    return points


@router.get("/recent-activity")
async def get_recent_activity(limit: int = 10):
    """Get recent system activity for the dashboard feed."""
    from app.api.routes.bugs import bugs_db
    from app.api.routes.fixes import fixes_db

    activities = []

    # Add recent bugs
    for bug in sorted(bugs_db.values(), key=lambda x: x.detected_at, reverse=True)[:limit]:
        activities.append({
            "type": "bug_detected",
            "timestamp": bug.detected_at,
            "message": f"Bug detected: {bug.bug_type.value} in {bug.file_path}",
            "severity": bug.severity.value,
            "id": bug.id,
        })

    # Add recent fixes
    for fix in sorted(fixes_db.values(), key=lambda x: x.created_at, reverse=True)[:limit]:
        activities.append({
            "type": "fix_proposed",
            "timestamp": fix.created_at,
            "message": f"Fix proposed by {fix.agent_type} agent",
            "status": fix.status.value,
            "id": fix.id,
        })

    # Sort all activities by timestamp
    activities.sort(key=lambda x: x["timestamp"], reverse=True)

    return activities[:limit]
