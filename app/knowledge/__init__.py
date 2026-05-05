"""
Knowledge graph module — stores past repairs in Neo4j so the system can
query "have we seen this kind of bug before?" on incoming reports.

The implementation degrades gracefully: if Neo4j is not reachable the
calls become no-ops with a warning, so the rest of the pipeline keeps
working.

Author: Millicent Mufambi (H240624A)
"""
from app.knowledge.graph import (
    KnowledgeGraph,
    KnowledgeGraphState,
    knowledge_graph,
)

__all__ = ["KnowledgeGraph", "KnowledgeGraphState", "knowledge_graph"]
