"""
WebSocket endpoints for real-time updates.

Provides live updates for:
- Bug detection events
- Consensus progress
- Fix application status
- Agent health changes
"""

from typing import List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
from datetime import datetime

websocket_router = APIRouter()


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Supports multiple channels:
    - bugs: Bug detection and status updates
    - consensus: Consensus round progress
    - agents: Agent status changes
    - all: All events
    """

    def __init__(self):
        self.active_connections: dict[str, Set[WebSocket]] = {
            "bugs": set(),
            "consensus": set(),
            "agents": set(),
            "all": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str = "all"):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        if channel not in self.active_connections:
            channel = "all"
        self.active_connections[channel].add(websocket)
        self.active_connections["all"].add(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from all channels."""
        for channel in self.active_connections.values():
            channel.discard(websocket)

    async def broadcast(self, message: dict, channel: str = "all"):
        """Broadcast a message to all connections in a channel."""
        message["timestamp"] = datetime.utcnow().isoformat()
        json_message = json.dumps(message)

        connections = self.active_connections.get(channel, set())
        if channel != "all":
            connections = connections.union(self.active_connections["all"])

        disconnected = set()
        for connection in connections:
            try:
                await connection.send_text(json_message)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific connection."""
        message["timestamp"] = datetime.utcnow().isoformat()
        await websocket.send_text(json.dumps(message))


# Global connection manager
manager = ConnectionManager()


@websocket_router.websocket("/live")
async def websocket_endpoint(websocket: WebSocket, channel: str = "all"):
    """
    Main WebSocket endpoint for real-time updates.

    Query params:
        channel: Filter events by channel (bugs, consensus, agents, all)

    Message format (sent to client):
    {
        "event": "bug_detected" | "consensus_started" | "fix_applied" | etc.,
        "data": { ... event-specific data ... },
        "timestamp": "ISO timestamp"
    }
    """
    await manager.connect(websocket, channel)

    # Send initial connection confirmation
    await manager.send_personal_message({
        "event": "connected",
        "data": {"channel": channel, "message": "Connected to CodeFlow AI live updates"}
    }, websocket)

    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Handle ping/pong for keepalive
            if data == "ping":
                await manager.send_personal_message({"event": "pong", "data": {}}, websocket)
            else:
                # Handle other client messages if needed
                try:
                    message = json.loads(data)
                    if message.get("action") == "subscribe":
                        new_channel = message.get("channel", "all")
                        manager.active_connections[new_channel].add(websocket)
                        await manager.send_personal_message({
                            "event": "subscribed",
                            "data": {"channel": new_channel}
                        }, websocket)
                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        manager.disconnect(websocket)


# Helper functions for broadcasting events (called from other modules)

async def broadcast_bug_detected(bug_data: dict):
    """Broadcast a bug detection event."""
    await manager.broadcast({
        "event": "bug_detected",
        "data": bug_data,
    }, channel="bugs")


async def broadcast_consensus_update(consensus_data: dict):
    """Broadcast a consensus progress update."""
    await manager.broadcast({
        "event": "consensus_update",
        "data": consensus_data,
    }, channel="consensus")


async def broadcast_fix_applied(fix_data: dict):
    """Broadcast a fix application event."""
    await manager.broadcast({
        "event": "fix_applied",
        "data": fix_data,
    }, channel="bugs")


async def broadcast_agent_status(agent_data: dict):
    """Broadcast an agent status change."""
    await manager.broadcast({
        "event": "agent_status_change",
        "data": agent_data,
    }, channel="agents")


async def broadcast_lab_event(event_name: str, run_id: str, data: dict):
    """
    Broadcast a Consensus Lab event so the live UI can animate phases.

    Each event is tagged with the client-supplied run_id so the frontend
    can pick out the events that belong to its current run.
    """
    await manager.broadcast({
        "event": event_name,
        "run_id": run_id,
        "data": data,
    }, channel="consensus")
