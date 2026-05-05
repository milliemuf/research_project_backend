"""
Multi-Agent System for Code Repair.

This module implements the three specialized agents:
1. Analyzer Agent: Bug detection and classification
2. Healer Agent: Fix generation using LLMs
3. Validator Agent: Fix verification and safety checking

Key Innovation: Heterogeneous agents using different LLM backends
(Claude, GPT-4, Ollama) for diverse, uncorrelated outputs.
"""

from app.agents.base_agent import BaseAgent, AgentOutput, AgentConfig
from app.agents.analyzer_agent import AnalyzerAgent
from app.agents.healer_agent import HealerAgent
from app.agents.validator_agent import ValidatorAgent
from app.agents.agent_manager import AgentManager

__all__ = [
    "BaseAgent",
    "AgentOutput",
    "AgentConfig",
    "AnalyzerAgent",
    "HealerAgent",
    "ValidatorAgent",
    "AgentManager",
]
