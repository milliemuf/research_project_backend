"""
Base Agent Abstract Class.

Defines the interface that all agents must implement.
Supports multiple LLM backends for heterogeneous BFT.

Author: Millicent Mufambi (H240624A)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, Dict
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    GPT4 = "gpt4"
    OLLAMA = "ollama"


class AgentType(str, Enum):
    """Types of agents in the system."""
    ANALYZER = "analyzer"
    HEALER = "healer"
    VALIDATOR = "validator"


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    agent_id: str
    agent_type: AgentType
    llm_provider: LLMProvider
    model_name: str = ""  # e.g., "claude-3-opus", "gpt-4", "llama3"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_seconds: int = 30


@dataclass
class AgentOutput:
    """Standard output format for all agents."""
    agent_id: str
    agent_type: AgentType
    success: bool
    result: Any
    confidence: float = 0.0
    reasoning: str = ""
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """
    Abstract base class for all agents.

    All agents share:
    - An LLM client for generating responses
    - A reputation score that affects consensus weight
    - Standard input/output interfaces
    - Logging and metrics

    Subclasses implement:
    - process(): The main agent logic
    - _build_prompt(): Create the LLM prompt for the specific task
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.agent_id = config.agent_id
        self.agent_type = config.agent_type
        self.llm_provider = config.llm_provider

        # Reputation tracking (affects consensus weight)
        self.reputation_score = 1.0
        self.total_tasks = 0
        self.successful_tasks = 0

        # LLM client (initialized in subclass or via set_llm_client)
        self._llm_client = None

        # Metrics
        self._total_latency_ms = 0.0

        logger.info(
            "Agent initialized",
            agent_id=self.agent_id,
            agent_type=self.agent_type.value,
            llm_provider=self.llm_provider.value
        )

    def set_llm_client(self, client: Any):
        """Set the LLM client for this agent."""
        self._llm_client = client

    @abstractmethod
    async def process(self, input_data: Any) -> AgentOutput:
        """
        Process input and produce output.

        This is the main entry point for agent operations.
        Must be implemented by subclasses.

        Args:
            input_data: Task-specific input data

        Returns:
            AgentOutput with the results
        """
        pass

    @abstractmethod
    def _build_prompt(self, input_data: Any) -> str:
        """
        Build the prompt for the LLM.

        Must be implemented by subclasses to create task-specific prompts.

        Args:
            input_data: Task-specific input

        Returns:
            Formatted prompt string
        """
        pass

    async def _call_llm(self, prompt: str) -> str:
        """
        Call the configured LLM and return the response.

        Handles different providers transparently. Ollama uses an HTTP
        endpoint and does not need a Python client object, so it is
        exempt from the client-presence check.
        """
        if self.llm_provider != LLMProvider.OLLAMA and self._llm_client is None:
            raise RuntimeError(f"LLM client not configured for agent {self.agent_id}")

        start_time = datetime.utcnow()

        try:
            if self.llm_provider == LLMProvider.CLAUDE:
                response = await self._call_claude(prompt)
            elif self.llm_provider == LLMProvider.GPT4:
                response = await self._call_gpt4(prompt)
            elif self.llm_provider == LLMProvider.OLLAMA:
                response = await self._call_ollama(prompt)
            else:
                raise ValueError(f"Unknown LLM provider: {self.llm_provider}")

            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            self._total_latency_ms += latency

            logger.debug(
                "LLM call completed",
                agent_id=self.agent_id,
                provider=self.llm_provider.value,
                latency_ms=latency
            )

            return response

        except Exception as e:
            logger.error(
                "LLM call failed",
                agent_id=self.agent_id,
                error=str(e)
            )
            raise

    async def _call_claude(self, prompt: str) -> str:
        """Call Claude API."""
        # Using anthropic library
        response = await self._llm_client.messages.create(
            model=self.config.model_name or "claude-3-sonnet-20240229",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    async def _call_gpt4(self, prompt: str) -> str:
        """Call OpenAI GPT-4 API."""
        # Using openai library
        response = await self._llm_client.chat.completions.create(
            model=self.config.model_name or "gpt-4",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    async def _call_ollama(self, prompt: str) -> str:
        """Call local Ollama instance."""
        import aiohttp
        from app.config import settings

        # Allow model_name to be either:
        #   * "url|model"  (preferred — fully explicit)
        #   * a bare URL   (legacy — uses settings.ollama_model)
        #   * a model name (uses settings.ollama_base_url)
        #   * empty        (uses both settings)
        model_name = self.config.model_name or ""
        if "|" in model_name:
            base_url, ollama_model = model_name.split("|", 1)
        elif model_name.startswith("http"):
            base_url = model_name
            ollama_model = settings.ollama_model
        else:
            base_url = settings.ollama_base_url
            ollama_model = model_name or settings.ollama_model

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/api/generate",
                json={
                    "model": ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.config.temperature,
                        "num_predict": self.config.max_tokens,
                    }
                }
            ) as resp:
                result = await resp.json()
                return result.get("response", "")

    def update_reputation(self, success: bool):
        """
        Update agent reputation based on task outcome.

        Reputation affects weight in consensus voting.
        """
        self.total_tasks += 1
        if success:
            self.successful_tasks += 1
            # Increase reputation (bounded at 1.0)
            self.reputation_score = min(1.0, self.reputation_score + 0.01)
        else:
            # Decrease reputation (bounded at 0.1)
            self.reputation_score = max(0.1, self.reputation_score - 0.05)

    @property
    def accuracy(self) -> float:
        """Calculate agent accuracy rate."""
        if self.total_tasks == 0:
            return 1.0
        return self.successful_tasks / self.total_tasks

    @property
    def average_latency_ms(self) -> float:
        """Calculate average latency per task."""
        if self.total_tasks == 0:
            return 0.0
        return self._total_latency_ms / self.total_tasks

    def get_stats(self) -> dict:
        """Get agent statistics."""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "llm_provider": self.llm_provider.value,
            "reputation_score": self.reputation_score,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "accuracy": self.accuracy,
            "average_latency_ms": self.average_latency_ms,
        }
