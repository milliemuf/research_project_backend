"""
Knowledge graph integration (Neo4j) for repair pattern learning.

Schema:
  (:Bug {bug_id, error_signature, language, severity})
   -[:RESOLVED_BY]-> (:Fix {fix_id, fixed_code, explanation, applied_at})
  (:Bug)-[:SIMILAR_TO {score}]-(:Bug)
  (:Fix)-[:GENERATED_BY]-(:Agent {agent_id, llm_provider})

The class works in three states:
  * CONNECTED   — Neo4j is reachable and writes succeed
  * UNAVAILABLE — Neo4j was probed but not reachable; calls become no-ops
  * UNINITIALISED — connect() has not been called yet

This means the rest of the system keeps running even if the graph DB is
down — important because the graph is a learning aid, not a correctness
dependency.

Author: Millicent Mufambi (H240624A)
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class KnowledgeGraphState(str, Enum):
    UNINITIALISED = "uninitialised"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"


@dataclass
class SimilarBug:
    bug_id: str
    error_signature: str
    similarity: float
    fix_explanation: Optional[str] = None
    fixed_code: Optional[str] = None


class KnowledgeGraph:
    """
    Thin wrapper around the Neo4j async driver, with graceful degradation.

    Usage:
        kg = KnowledgeGraph()
        await kg.connect()
        await kg.record_repair(repair_outcome)
        similar = await kg.find_similar_bugs(error_signature="...")
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        # Lazy-load settings to avoid a hard import cycle at module load time
        from app.config import settings

        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self.state = KnowledgeGraphState.UNINITIALISED
        self._driver = None
        logger.info("Knowledge graph configured", uri=self.uri, user=self.user)

    # ------------------------------------------------------------------
    async def connect(self) -> KnowledgeGraphState:
        """Probe Neo4j and cache the driver. Safe to call multiple times."""
        if self.state == KnowledgeGraphState.CONNECTED:
            return self.state

        try:
            from neo4j import AsyncGraphDatabase  # type: ignore
        except ImportError:
            logger.warning("neo4j driver not installed; knowledge graph disabled")
            self.state = KnowledgeGraphState.UNAVAILABLE
            return self.state

        try:
            self._driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))
            async with self._driver.session() as session:
                await session.run("RETURN 1")
            await self._ensure_indexes()
            self.state = KnowledgeGraphState.CONNECTED
            logger.info("Knowledge graph connected", uri=self.uri)
        except Exception as e:
            logger.warning("Knowledge graph unreachable; calls will be no-ops", error=str(e))
            self.state = KnowledgeGraphState.UNAVAILABLE
            self._driver = None

        return self.state

    async def close(self) -> None:
        if self._driver is not None:
            try:
                await self._driver.close()
            except Exception:
                pass
            self._driver = None
        self.state = KnowledgeGraphState.UNINITIALISED

    # ------------------------------------------------------------------
    async def _ensure_indexes(self) -> None:
        if self._driver is None:
            return
        async with self._driver.session() as session:
            await session.run("CREATE INDEX bug_id_idx IF NOT EXISTS FOR (b:Bug) ON (b.bug_id)")
            await session.run("CREATE INDEX fix_id_idx IF NOT EXISTS FOR (f:Fix) ON (f.fix_id)")
            await session.run("CREATE INDEX agent_id_idx IF NOT EXISTS FOR (a:Agent) ON (a.agent_id)")

    # ------------------------------------------------------------------
    async def record_repair(self, repair_outcome: Any) -> bool:
        """
        Record a RepairOutcome as graph nodes/edges.

        Returns True if the write succeeded, False otherwise (including
        when the graph is unavailable). Never raises.
        """
        if self.state == KnowledgeGraphState.UNINITIALISED:
            await self.connect()

        if self.state != KnowledgeGraphState.CONNECTED or self._driver is None:
            return False

        try:
            bug_id = getattr(repair_outcome, "bug_id", "")
            fixed_code = getattr(repair_outcome, "fixed_code", "") or ""
            explanation = getattr(repair_outcome, "explanation", "") or ""
            success = bool(getattr(repair_outcome, "success", False))
            consensus = getattr(repair_outcome, "consensus_result", None) or {}

            error_signature = self._signature(bug_id, fixed_code)
            fix_id = hashlib.sha1(fixed_code.encode("utf-8")).hexdigest()[:16] if fixed_code else ""

            async with self._driver.session() as session:
                await session.run(
                    """
                    MERGE (b:Bug {bug_id: $bug_id})
                      ON CREATE SET b.error_signature = $sig,
                                    b.first_seen = $now
                    MERGE (f:Fix {fix_id: $fix_id})
                      ON CREATE SET f.fixed_code = $fixed_code,
                                    f.explanation = $explanation,
                                    f.applied_at = $now,
                                    f.success = $success,
                                    f.consensus_prepare_votes = $prepare_votes,
                                    f.consensus_commit_votes = $commit_votes
                    MERGE (b)-[:RESOLVED_BY]->(f)
                    """,
                    bug_id=bug_id or "unknown",
                    sig=error_signature,
                    fix_id=fix_id or "unknown",
                    fixed_code=fixed_code[:5000],
                    explanation=explanation[:2000],
                    now=datetime.utcnow().isoformat(),
                    success=success,
                    prepare_votes=int(consensus.get("prepare_votes", 0)),
                    commit_votes=int(consensus.get("commit_votes", 0)),
                )
            return True
        except Exception as e:
            logger.warning("Knowledge graph record_repair failed", error=str(e))
            return False

    # ------------------------------------------------------------------
    async def find_similar_bugs(
        self,
        error_signature: str,
        limit: int = 5,
    ) -> List[SimilarBug]:
        """
        Return bugs whose signature shares a long common prefix with the
        supplied signature. This is intentionally a simple, cheap heuristic;
        a richer embedding-based similarity is out of scope for the first
        prototype.
        """
        if self.state == KnowledgeGraphState.UNINITIALISED:
            await self.connect()
        if self.state != KnowledgeGraphState.CONNECTED or self._driver is None:
            return []

        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (b:Bug)-[:RESOLVED_BY]->(f:Fix)
                    WHERE b.error_signature STARTS WITH $prefix
                    RETURN b.bug_id AS bug_id,
                           b.error_signature AS sig,
                           f.fixed_code AS fixed_code,
                           f.explanation AS explanation
                    LIMIT $limit
                    """,
                    prefix=error_signature[:32],
                    limit=limit,
                )
                similar = []
                async for row in result:
                    similar.append(SimilarBug(
                        bug_id=row["bug_id"],
                        error_signature=row["sig"],
                        similarity=self._similarity(error_signature, row["sig"]),
                        fix_explanation=row["explanation"],
                        fixed_code=row["fixed_code"],
                    ))
                return similar
        except Exception as e:
            logger.warning("Knowledge graph find_similar_bugs failed", error=str(e))
            return []

    # ------------------------------------------------------------------
    @staticmethod
    def _signature(bug_id: str, code_blob: str) -> str:
        """Produce a stable, content-addressed signature for a bug."""
        h = hashlib.sha256(f"{bug_id}::{code_blob}".encode("utf-8")).hexdigest()
        return h

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Cheap Jaccard-on-trigrams similarity."""
        def trigrams(s: str):
            return {s[i:i + 3] for i in range(max(0, len(s) - 2))}
        ta, tb = trigrams(a), trigrams(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)


# Module-level singleton with graceful degradation.
knowledge_graph = KnowledgeGraph()
